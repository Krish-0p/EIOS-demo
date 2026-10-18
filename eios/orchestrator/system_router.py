"""
EIOS System Metrics Router
---------------------------
Provides real host-level metrics (CPU, RAM, disk, network) via psutil.
Also exposes Kubernetes workload discovery via the K8s API.

Endpoints:
  GET /api/system/metrics    – CPU, RAM, disk, network (real, from psutil)
  GET /api/system/processes  – top processes by CPU
  GET /api/k8s/workloads     – K8s pods/deployments (if cluster reachable)
  GET /api/k8s/namespaces    – available namespaces
"""

from __future__ import annotations

import logging
import os
import platform
import time
from typing import Any

from fastapi import APIRouter, HTTPException

log = logging.getLogger("eios.system")

router = APIRouter(tags=["system"])

# ── psutil (safe import) ──────────────────────────────────────────────────────
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    log.warning("psutil not installed; system metrics will be unavailable")

# ── Kubernetes client (safe import) ──────────────────────────────────────────
try:
    from kubernetes import client as k8s_client, config as k8s_config
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False
    log.warning("kubernetes client not installed; K8s discovery disabled")


# ── System Metrics ─────────────────────────────────────────────────────────────

@router.get("/api/system/metrics")
def system_metrics() -> dict:
    """Return real host system metrics via psutil."""
    if not PSUTIL_AVAILABLE:
        raise HTTPException(status_code=503, detail="psutil not available. Run: pip install psutil")

    cpu_pct = psutil.cpu_percent(interval=0.3)
    cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    cpu_freq = psutil.cpu_freq()
    cpu_count = psutil.cpu_count(logical=True)
    cpu_physical = psutil.cpu_count(logical=False)

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_gb": round(usage.total / 1024**3, 2),
                "used_gb": round(usage.used / 1024**3, 2),
                "free_gb": round(usage.free / 1024**3, 2),
                "percent": usage.percent,
            })
        except (PermissionError, OSError):
            pass

    # Network I/O
    net_before = psutil.net_io_counters()
    time.sleep(0.2)
    net_after = psutil.net_io_counters()
    net_rx_kbps = round((net_after.bytes_recv - net_before.bytes_recv) / 0.2 / 1024, 1)
    net_tx_kbps = round((net_after.bytes_sent - net_before.bytes_sent) / 0.2 / 1024, 1)

    # Per-interface stats
    net_ifaces = []
    try:
        counters = psutil.net_io_counters(pernic=True)
        for iface, c in counters.items():
            net_ifaces.append({
                "interface": iface,
                "bytes_sent": c.bytes_sent,
                "bytes_recv": c.bytes_recv,
                "packets_sent": c.packets_sent,
                "packets_recv": c.packets_recv,
                "errin": c.errin,
                "errout": c.errout,
            })
    except Exception:
        pass

    return {
        "cpu": {
            "percent": cpu_pct,
            "per_core": cpu_per_core,
            "count_logical": cpu_count,
            "count_physical": cpu_physical,
            "freq_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
            "freq_max_mhz": round(cpu_freq.max, 0) if cpu_freq else None,
        },
        "memory": {
            "total_gb": round(mem.total / 1024**3, 2),
            "available_gb": round(mem.available / 1024**3, 2),
            "used_gb": round(mem.used / 1024**3, 2),
            "percent": mem.percent,
            "cached_gb": round(getattr(mem, "cached", 0) / 1024**3, 2),
            "buffers_gb": round(getattr(mem, "buffers", 0) / 1024**3, 2),
        },
        "swap": {
            "total_gb": round(swap.total / 1024**3, 2),
            "used_gb": round(swap.used / 1024**3, 2),
            "percent": swap.percent,
        },
        "disk": disks,
        "network": {
            "rx_kbps": net_rx_kbps,
            "tx_kbps": net_tx_kbps,
            "interfaces": net_ifaces,
        },
        "platform": {
            "system": platform.system(),
            "node": platform.node(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
    }


@router.get("/api/system/processes")
def system_processes(limit: int = 20) -> list[dict]:
    """Return top processes by CPU usage."""
    if not PSUTIL_AVAILABLE:
        raise HTTPException(status_code=503, detail="psutil not available")

    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent",
                                   "memory_info", "status", "username", "cmdline"]):
        try:
            info = p.info
            procs.append({
                "pid": info["pid"],
                "name": info["name"] or "",
                "cpu_pct": round(info.get("cpu_percent") or 0, 2),
                "mem_pct": round(info.get("memory_percent") or 0, 2),
                "mem_mb": round((info.get("memory_info").rss if info.get("memory_info") else 0) / 1024 / 1024, 1),
                "status": info.get("status", ""),
                "user": info.get("username", ""),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Sort by CPU descending
    procs.sort(key=lambda x: x["cpu_pct"], reverse=True)
    return procs[:limit]


# ── Kubernetes Workloads ──────────────────────────────────────────────────────

def _load_k8s() -> bool:
    """Try to load K8s config (in-cluster first, then kubeconfig)."""
    if not K8S_AVAILABLE:
        return False
    try:
        k8s_config.load_incluster_config()
        return True
    except Exception:
        pass
    try:
        k8s_config.load_kube_config()
        return True
    except Exception:
        return False


@router.get("/api/k8s/workloads")
def k8s_workloads(namespace: str = "default") -> dict:
    """Discover real Kubernetes workloads (pods, deployments, services)."""
    if not _load_k8s():
        return {
            "available": False,
            "reason": "Kubernetes cluster not reachable or client not installed",
            "pods": [],
            "deployments": [],
            "services": [],
        }

    try:
        core = k8s_client.CoreV1Api()
        apps = k8s_client.AppsV1Api()

        # Pods
        pod_list = core.list_namespaced_pod(namespace) if namespace != "all" \
                   else core.list_pod_for_all_namespaces()
        pods = []
        for pod in pod_list.items:
            containers = pod.spec.containers or []
            pods.append({
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase or "Unknown",
                "ready": sum(1 for cs in (pod.status.container_statuses or []) if cs.ready),
                "total_containers": len(containers),
                "node": pod.spec.node_name,
                "images": [c.image for c in containers],
                "restart_count": sum(
                    cs.restart_count for cs in (pod.status.container_statuses or [])
                ),
                "pod_ip": pod.status.pod_ip,
                "created": str(pod.metadata.creation_timestamp),
            })

        # Deployments
        dep_list = apps.list_namespaced_deployment(namespace) if namespace != "all" \
                   else apps.list_deployment_for_all_namespaces()
        deployments = []
        for dep in dep_list.items:
            deployments.append({
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas": dep.spec.replicas or 0,
                "ready_replicas": dep.status.ready_replicas or 0,
                "available_replicas": dep.status.available_replicas or 0,
                "image": (dep.spec.template.spec.containers or [{}])[0].image if dep.spec.template.spec.containers else "",
            })

        # Services
        svc_list = core.list_namespaced_service(namespace) if namespace != "all" \
                   else core.list_service_for_all_namespaces()
        services = []
        for svc in svc_list.items:
            ports = [f"{p.port}:{p.target_port}" for p in (svc.spec.ports or [])]
            services.append({
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "ports": ", ".join(str(p) for p in ports),
            })

        return {
            "available": True,
            "namespace": namespace,
            "pods": pods,
            "deployments": deployments,
            "services": services,
        }

    except Exception as e:
        log.exception("K8s query failed")
        return {
            "available": False,
            "reason": str(e),
            "pods": [],
            "deployments": [],
            "services": [],
        }


@router.get("/api/k8s/namespaces")
def k8s_namespaces() -> list[str]:
    """List available Kubernetes namespaces."""
    if not _load_k8s():
        return []
    try:
        core = k8s_client.CoreV1Api()
        ns_list = core.list_namespace()
        return [ns.metadata.name for ns in ns_list.items]
    except Exception:
        return []
