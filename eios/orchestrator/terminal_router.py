"""
EIOS Terminal Router
---------------------
Controlled, whitelisted terminal execution for the EIOS OS shell.
Only approved commands can run — no arbitrary shell execution.

Endpoints:
  POST /api/terminal/exec    – execute a whitelisted EIOS command
  GET  /api/terminal/history – last N command results
"""

from __future__ import annotations

import asyncio
import logging
import json
import shlex
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("eios.terminal")

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

# Rolling history (most recent 200 entries, in-memory)
_history: deque[dict] = deque(maxlen=200)


# ── Whitelist ─────────────────────────────────────────────────────────────────
# Pattern → (display_description, actual_command_template)
# Use {args} as placeholder for sanitized user arguments.

ALLOWED_COMMANDS: dict[str, dict] = {
    # Docker
    "docker ps": {"desc": "List running containers", "exec": ["docker", "ps", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]},
    "docker ps -a": {"desc": "List all containers", "exec": ["docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}"]},
    "docker images": {"desc": "List Docker images", "exec": ["docker", "images"]},
    "docker stats --no-stream": {"desc": "Container resource usage", "exec": ["docker", "stats", "--no-stream", "--format", "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"]},
    "docker network ls": {"desc": "List Docker networks", "exec": ["docker", "network", "ls"]},
    "docker volume ls": {"desc": "List Docker volumes", "exec": ["docker", "volume", "ls"]},
    "docker info": {"desc": "Docker system info", "exec": ["docker", "info"]},
    # EIOS system
    "eios status": {"desc": "EIOS system status", "exec": None, "builtin": "eios_status"},
    "eios services": {"desc": "Active EIOS services", "exec": None, "builtin": "eios_services"},
    "eios incidents": {"desc": "Recent incidents", "exec": None, "builtin": "eios_incidents"},
    "eios health": {"desc": "Full health check", "exec": None, "builtin": "eios_health"},
    "eios version": {"desc": "EIOS version", "exec": None, "builtin": "eios_version"},
    # System
    "whoami": {"desc": "Current user", "exec": ["whoami"]},
    "hostname": {"desc": "System hostname", "exec": ["hostname"]},
    "uptime": {"desc": "System uptime", "exec": None, "builtin": "uptime_builtin"},
    "df -h": {"desc": "Orchestrator disk usage", "exec": None, "builtin": "df_builtin"},
    "free -h": {"desc": "Orchestrator runtime memory usage", "exec": None, "builtin": "mem_builtin"},
    "help": {"desc": "Show available commands", "exec": None, "builtin": "help_builtin"},
    "clear": {"desc": "Clear terminal", "exec": None, "builtin": "clear_builtin"},
}


def _builtin_eios_status() -> str:
    return (
        "┌─ EIOS Enterprise Status ─────────────────────────────┐\n"
        "│  Core        : RUNNING  (pid orchestrator)           │\n"
        "│  Ingest      : ACTIVE   (kafka + prometheus taps)    │\n"
        "│  Detect      : ACTIVE   (rules engine)               │\n"
        "│  Security    : ENFORCED (zero-trust + audit chain)   │\n"
        "│  API         : http://127.0.0.1:8000                 │\n"
        "│  Dashboard   : http://127.0.0.1:5173                 │\n"
        "└───────────────────────────────────────────────────────┘"
    )


def _builtin_eios_version() -> str:
    return "EIOS Enterprise v1.0.0-rc  |  Build 2026.10  |  Kernel: 5.2.1-eios"


def _builtin_help() -> str:
    lines = ["Available EIOS Shell Commands:", ""]
    for cmd, meta in ALLOWED_COMMANDS.items():
        lines.append(f"  {cmd:<35} {meta['desc']}")
    lines.append("")
    lines.append("Type any command above to execute it.")
    return "\n".join(lines)


def _builtin_uptime() -> str:
    try:
        import psutil
        boot = psutil.boot_time()
        import time
        up_secs = int(time.time() - boot)
        days = up_secs // 86400
        hours = (up_secs % 86400) // 3600
        mins = (up_secs % 3600) // 60
        return f"System uptime: {days}d {hours}h {mins}m"
    except Exception:
        return "uptime: psutil not available"


def _builtin_df() -> str:
    try:
        import psutil
        lines = [f"{'Filesystem':<20} {'Size':>8} {'Used':>8} {'Avail':>8} {'Use%':>6} {'Mounted on'}"]
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(
                    f"{part.device:<20} "
                    f"{usage.total//1024//1024//1024:>6}G "
                    f"{usage.used//1024//1024//1024:>6}G "
                    f"{usage.free//1024//1024//1024:>6}G "
                    f"{usage.percent:>5}% "
                    f"{part.mountpoint}"
                )
            except Exception:
                pass
        return "\n".join(lines)
    except Exception:
        return "df: psutil not available"


def _builtin_mem() -> str:
    try:
        import psutil
        m = psutil.virtual_memory()
        s = psutil.swap_memory()
        return (
            f"              total        used        free      shared  buff/cache   available\n"
            f"Mem:    {m.total//1024//1024//1024:>8}G "
            f"{m.used//1024//1024//1024:>10}G "
            f"{m.available//1024//1024//1024:>10}G "
            f"          -             -\n"
            f"Swap:   {s.total//1024//1024//1024:>8}G "
            f"{s.used//1024//1024//1024:>10}G "
            f"{s.free//1024//1024//1024:>10}G"
        )
    except Exception:
        return "free: psutil not available"


BUILTINS: dict[str, Any] = {
    "eios_status": _builtin_eios_status,
    "eios_services": lambda: "Use the System Monitor window for live service list.",
    "eios_incidents": lambda: "Use the EIOS Dashboard to view incidents in real-time.",
    "eios_health": lambda: f"{_builtin_eios_status()}\n\n{_builtin_uptime()}",
    "eios_version": _builtin_eios_version,
    "help_builtin": _builtin_help,
    "clear_builtin": lambda: "__CLEAR__",
    "uptime_builtin": _builtin_uptime,
    "df_builtin": _builtin_df,
    "mem_builtin": _builtin_mem,
}


# ── Request / Response models ─────────────────────────────────────────────────

class ExecRequest(BaseModel):
    command: str


class ExecResponse(BaseModel):
    command: str
    output: str
    exit_code: int
    timestamp: str
    duration_ms: float


# ── Handler ───────────────────────────────────────────────────────────────────

def _find_command(raw: str) -> tuple[str, dict] | tuple[None, None]:
    """Match complete approved commands; never discard extra arguments."""
    try:
        key = " ".join(shlex.split(raw)).lower()
    except ValueError:
        return None, None
    meta = ALLOWED_COMMANDS.get(key)
    return (key, meta) if meta else (None, None)


def _table(headers, rows):
    rows = [[str(value) for value in row] for row in rows]
    widths = [max(len(header), *(len(row[i]) for row in rows)) for i, header in enumerate(headers)] if rows else list(map(len, headers))
    return "\n".join("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)).rstrip()
                     for row in [headers, *rows])


def _docker_command(command):
    """Read Docker Engine through the existing SDK, without requiring a CLI."""
    from docker_router import _get_client, list_containers, list_networks, list_volumes, docker_info, container_stats

    if command in ("docker ps", "docker ps -a"):
        containers = list_containers(all=command == "docker ps -a")
        return _table(["NAMES", "IMAGE", "STATUS", "PORTS"],
                      [[c["name"], c["image"], c["status"], c["ports"]] for c in containers])
    if command == "docker images":
        return _table(["IMAGE", "IMAGE ID", "SIZE"],
                      [[", ".join(image.get("RepoTags") or ["<none>"]),
                        image["Id"].removeprefix("sha256:")[:12],
                        f'{image.get("Size", 0) / 1024 / 1024:.1f} MiB']
                       for image in _get_client().api.images()])
    if command == "docker network ls":
        return _table(["NETWORK ID", "NAME", "DRIVER", "SCOPE"],
                      [[n["id"], n["name"], n["driver"], n["scope"]] for n in list_networks()])
    if command == "docker volume ls":
        return _table(["DRIVER", "VOLUME NAME"], [[v["driver"], v["name"]] for v in list_volumes()])
    if command == "docker info":
        return json.dumps(docker_info(), indent=2)
    if command == "docker stats --no-stream":
        containers = _get_client().containers.list()

        def sample(container):
            try:
                stats = container_stats(container.id)
                received = sum(n["rx_bytes"] for n in stats["networks"].values())
                sent = sum(n["tx_bytes"] for n in stats["networks"].values())
                return [container.name, f'{stats["cpu_pct"]:.2f}%',
                        f'{stats["memory_mb"]:.1f} / {stats["memory_limit_mb"]:.1f} MiB',
                        f'{received / 1024:.1f} / {sent / 1024:.1f} KiB']
            except Exception:
                return [container.name, "unavailable", "unavailable", "unavailable"]

        with ThreadPoolExecutor(max_workers=8) as executor:
            rows = list(executor.map(sample, containers))
        return _table(["NAME", "CPU %", "MEM USAGE / LIMIT", "NET I/O"], rows)
    raise ValueError("Unsupported Docker command")


@router.post("/exec", response_model=ExecResponse)
async def terminal_exec(req: ExecRequest) -> dict:
    raw = req.command.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty command")

    key, meta = _find_command(raw)
    if not meta:
        # Not whitelisted
        output = (
            f"eios-shell: command not permitted: '{raw}'\n"
            f"Type 'help' to see available commands."
        )
        entry = {
            "command": raw,
            "output": output,
            "exit_code": 127,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": 0.0,
        }
        _history.appendleft(entry)
        return entry

    start = asyncio.get_event_loop().time()
    builtin_key = meta.get("builtin")
    exec_cmd = meta.get("exec")
    exit_code = 0
    output = ""

    try:
        if key.startswith("docker "):
            output = await asyncio.wait_for(asyncio.to_thread(_docker_command, key), timeout=15.0)
        elif builtin_key and builtin_key in BUILTINS:
            output = await asyncio.to_thread(BUILTINS[builtin_key])
        elif exec_cmd:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            output = stdout.decode("utf-8", errors="replace").rstrip()
            exit_code = proc.returncode or 0
        else:
            output = f"Command '{key}' is not available on this platform."
    except asyncio.TimeoutError:
        output = "Command timed out after 15 seconds."
        exit_code = 124
    except FileNotFoundError:
        output = f"Command not found: {exec_cmd[0] if exec_cmd else key}. Ensure Docker CLI is installed."
        exit_code = 127
    except Exception as e:
        output = f"Execution error: {e}"
        exit_code = 1

    duration = (asyncio.get_event_loop().time() - start) * 1000

    entry = {
        "command": raw,
        "output": output,
        "exit_code": exit_code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round(duration, 2),
    }
    _history.appendleft(entry)
    return entry


@router.get("/history")
def terminal_history(limit: int = 50) -> list[dict]:
    """Return recent terminal command history."""
    return list(_history)[:limit]
