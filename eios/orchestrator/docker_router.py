"""
EIOS Docker Integration Layer
------------------------------
Uses the official Docker Python SDK (docker-py) which handles both
Windows named pipes (//./pipe/docker_engine) and Unix sockets transparently.

Endpoints:
  GET  /api/docker/containers        – list all containers with status
  GET  /api/docker/containers/{id}/stats – live CPU/mem for one container
  GET  /api/docker/stats             – aggregate stats for all running containers
  POST /api/docker/containers/{id}/start
  POST /api/docker/containers/{id}/stop
  POST /api/docker/containers/{id}/restart
  GET  /api/docker/networks          – list Docker networks
  GET  /api/docker/volumes           – list Docker volumes
  GET  /api/docker/info              – Docker Engine system info
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

log = logging.getLogger("eios.docker")

router = APIRouter(prefix="/api/docker", tags=["docker"])

# ── Docker SDK client (lazy, cached) ─────────────────────────────────────────
_docker_client = None


def _get_client():
    """Return a cached docker.DockerClient, or raise 503 if unavailable."""
    global _docker_client
    try:
        import docker
        if _docker_client is None:
            _docker_client = docker.from_env(timeout=10)
        # Ping to verify connection
        _docker_client.ping()
        return _docker_client
    except ImportError:
        raise HTTPException(status_code=503, detail="docker package not installed. Run: pip install docker")
    except Exception as e:
        _docker_client = None  # Reset so next call retries
        raise HTTPException(status_code=503, detail=f"Docker Engine not reachable: {e}. Ensure Docker Desktop is running.")


def _parse_container(c) -> dict:
    """Normalize a docker-py Container object into EIOS format."""
    attrs = c.attrs or {}
    config = attrs.get("Config", {}) or {}
    network_settings = attrs.get("NetworkSettings", {}) or {}
    host_config = attrs.get("HostConfig", {}) or {}
    state = attrs.get("State", {}) or {}

    # Ports from NetworkSettings
    ports_map = network_settings.get("Ports") or {}
    port_parts = []
    for container_port, bindings in ports_map.items():
        if bindings:
            for b in bindings:
                host_port = b.get("HostPort", "")
                if host_port:
                    port_parts.append(f"{host_port}:{container_port.split('/')[0]}")
    port_str = ", ".join(port_parts) or "—"

    status = c.status.lower()
    running = state.get("Running", False)

    labels = config.get("Labels") or {}
    compose_service = labels.get("com.docker.compose.service", "")
    compose_project = labels.get("com.docker.compose.project", "")

    name = c.name or c.short_id or ""
    image_tag = ""
    try:
        tags = c.image.tags
        image_tag = tags[0] if tags else (c.image.short_id or "")
    except Exception:
        image_tag = config.get("Image", "")

    return {
        "id": c.short_id,
        "full_id": c.id,
        "name": name,
        "image": image_tag,
        "status": status,
        "state": "running" if running else status,
        "ports": port_str,
        "created": attrs.get("Created", ""),
        "uptime": state.get("StartedAt", ""),
        "compose_service": compose_service,
        "compose_project": compose_project,
        "labels": labels,
        "otlp_connected": any(
            kw in (image_tag + name).lower()
            for kw in ["otel", "opentelemetry", "jaeger", "prometheus"]
        ),
        "category": _infer_category(name, image_tag, labels),
    }


def _infer_category(name: str, image: str, labels: dict) -> str:
    combined = (name + image).lower()
    if any(kw in combined for kw in ["postgres", "mysql", "redis", "mongo", "valkey", "db"]):
        return "database"
    if any(kw in combined for kw in ["kafka", "zookeeper", "collector", "prometheus", "jaeger",
                                      "grafana", "otel", "opensearch", "flagd"]):
        return "infra"
    return "app"

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/containers")
def list_containers(all: bool = True) -> list[dict]:
    """List all Docker containers (running + stopped if all=True)."""
    client = _get_client()
    containers = client.containers.list(all=all)
    return [_parse_container(c) for c in containers]


@router.get("/containers/{container_id}/stats")
def container_stats(container_id: str) -> dict:
    """Get real-time CPU & memory for a single container (one-shot, no stream)."""
    client = _get_client()
    try:
        container = client.containers.get(container_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Container not found: {e}")

    try:
        data = container.stats(stream=False)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not fetch stats: {e}")

    # CPU calculation
    try:
        cpu_delta = data["cpu_stats"]["cpu_usage"]["total_usage"] - \
                    data["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = data["cpu_stats"].get("system_cpu_usage", 0) - \
                       data["precpu_stats"].get("system_cpu_usage", 0)
        num_cpus = data["cpu_stats"].get("online_cpus") or \
                   len(data["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
        cpu_pct = (cpu_delta / system_delta * num_cpus * 100.0) if system_delta > 0 else 0.0
    except (KeyError, ZeroDivisionError):
        cpu_pct = 0.0

    # Memory
    mem = data.get("memory_stats", {})
    mem_usage = mem.get("usage", 0)
    # Docker reports cache inside stats; subtract to get true RSS
    mem_cache = mem.get("stats", {}).get("cache", 0) or mem.get("stats", {}).get("inactive_file", 0)
    mem_real = max(0, mem_usage - mem_cache)
    mem_limit = mem.get("limit", 1)
    mem_pct = (mem_real / mem_limit * 100.0) if mem_limit > 0 else 0.0

    return {
        "id": container_id,
        "cpu_pct": round(cpu_pct, 2),
        "memory_bytes": mem_real,
        "memory_mb": round(mem_real / 1024 / 1024, 1),
        "memory_limit_mb": round(mem_limit / 1024 / 1024, 1),
        "memory_pct": round(mem_pct, 2),
        "networks": {
            k: {
                "rx_bytes": v.get("rx_bytes", 0),
                "tx_bytes": v.get("tx_bytes", 0),
            }
            for k, v in data.get("networks", {}).items()
        },
    }


@router.get("/stats")
def all_container_stats() -> list[dict]:
    """Lightweight CPU/memory summary for all running containers."""
    client = _get_client()
    containers = client.containers.list(all=False)  # running only

    results = []
    for c in containers:
        try:
            s = container_stats(c.short_id)
            s["id"] = c.short_id
            results.append(s)
        except Exception:
            results.append({"id": c.short_id, "cpu_pct": 0.0, "memory_mb": 0, "memory_pct": 0.0})
    return results


@router.post("/containers/{container_id}/start")
def start_container(container_id: str) -> dict:
    client = _get_client()
    try:
        container = client.containers.get(container_id)
        container.start()
        log.info("started container %s", container_id)
        return {"id": container_id, "action": "start", "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start container: {e}")


@router.post("/containers/{container_id}/stop")
def stop_container(container_id: str) -> dict:
    client = _get_client()
    try:
        container = client.containers.get(container_id)
        container.stop()
        log.info("stopped container %s", container_id)
        return {"id": container_id, "action": "stop", "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop container: {e}")


@router.post("/containers/{container_id}/restart")
def restart_container(container_id: str) -> dict:
    client = _get_client()
    try:
        container = client.containers.get(container_id)
        container.restart()
        log.info("restarted container %s", container_id)
        return {"id": container_id, "action": "restart", "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart container: {e}")


@router.get("/networks")
def list_networks() -> list[dict]:
    client = _get_client()
    try:
        networks = client.networks.list()
        return [
            {
                "id": n.id[:12] if n.id else "",
                "name": n.name or "",
                "driver": n.attrs.get("Driver", ""),
                "scope": n.attrs.get("Scope", ""),
                "containers": len(n.attrs.get("Containers", {})),
            }
            for n in networks
        ]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to list networks: {e}")


@router.get("/volumes")
def list_volumes() -> list[dict]:
    client = _get_client()
    try:
        vols = client.volumes.list()
        return [
            {
                "name": v.name or "",
                "driver": v.attrs.get("Driver", ""),
                "mountpoint": v.attrs.get("Mountpoint", ""),
                "created": v.attrs.get("CreatedAt", ""),
            }
            for v in vols
        ]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to list volumes: {e}")


@router.get("/info")
def docker_info() -> dict:
    """Return Docker Engine system info."""
    client = _get_client()
    try:
        data = client.info()
        return {
            "containers": data.get("Containers", 0),
            "containers_running": data.get("ContainersRunning", 0),
            "containers_paused": data.get("ContainersPaused", 0),
            "containers_stopped": data.get("ContainersStopped", 0),
            "images": data.get("Images", 0),
            "server_version": data.get("ServerVersion", ""),
            "os": data.get("OperatingSystem", ""),
            "architecture": data.get("Architecture", ""),
            "mem_total_gb": round(data.get("MemTotal", 0) / 1024 / 1024 / 1024, 2),
            "cpus": data.get("NCPU", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to fetch Docker info: {e}")
