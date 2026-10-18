"""
EIOS Filesystem Router
-----------------------
Exposes the real EIOS workspace directory as a navigable, readable filesystem.
Maps the EIOS directory structure into the OS-like drive shown in the UI.

Endpoints:
  GET /api/fs/list?path=   – list directory contents
  GET /api/fs/read?path=   – read file content (text only, size-capped)
  GET /api/fs/tree         – full EIOS drive tree
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger("eios.fs")

router = APIRouter(prefix="/api/fs", tags=["filesystem"])

# ── EIOS Workspace Root ───────────────────────────────────────────────────────
# The root that gets exposed as "EIOS Drive" in the UI.
# Override via env var EIOS_WORKSPACE_ROOT.

_default_root = Path(__file__).resolve().parent.parent   # eios/ folder
WORKSPACE_ROOT = Path(os.getenv("EIOS_WORKSPACE_ROOT", str(_default_root))).resolve()

MAX_FILE_BYTES = 512 * 1024  # 512 KB read cap


def _safe_path(rel: str) -> Path:
    """Resolve a user-supplied relative path, ensuring it stays inside WORKSPACE_ROOT."""
    # Normalise and strip leading slashes / drive letters
    rel = rel.lstrip("/\\").replace("\\", "/")
    resolved = (WORKSPACE_ROOT / rel).resolve()
    if not resolved.is_relative_to(WORKSPACE_ROOT):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if any(part.startswith('.') or part.lower() in ('secrets','credentials','node_modules') for part in resolved.relative_to(WORKSPACE_ROOT).parts):
        raise HTTPException(status_code=403, detail='Hidden files and secret/dependency directories are not accessible')
    return resolved


def _file_entry(path: Path, root: Path) -> dict:
    """Convert a Path to a serialisable entry."""
    stat = path.stat()
    rel = str(path.relative_to(root)).replace("\\", "/")
    mime, _ = mimetypes.guess_type(path.name)
    ext = path.suffix.lower().lstrip(".")
    return {
        "name": path.name,
        "path": rel,
        "type": "directory" if path.is_dir() else "file",
        "size": stat.st_size if path.is_file() else None,
        "size_human": _human_size(stat.st_size) if path.is_file() else None,
        "modified": stat.st_mtime,
        "extension": ext,
        "mime": mime or "",
        "is_text": _is_text(mime, ext),
    }


def _human_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b //= 1024
    return f"{b} TB"


def _is_text(mime: str | None, ext: str) -> bool:
    text_exts = {
        "py", "ts", "tsx", "js", "jsx", "json", "yaml", "yml", "toml",
        "ini", "cfg", "conf", "md", "txt", "sh", "ps1", "sql", "env",
        "gitignore", "dockerfile", "html", "css", "lock", "log", "csv",
    }
    if ext in text_exts:
        return True
    if mime and mime.startswith("text/"):
        return True
    return False


# Skip noisy directories
SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".venv", "venv",
    ".parcel-cache", ".turbo",
}


@router.get("/list")
def list_dir(path: str = Query("", description="Relative path inside EIOS workspace")) -> dict:
    """List directory contents at the given path."""
    target = _safe_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path!r}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name in SKIP_DIRS:
                continue
            try:
                entries.append(_file_entry(child, WORKSPACE_ROOT))
            except OSError:
                pass
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {
        "path": str(target.relative_to(WORKSPACE_ROOT)).replace("\\", "/") or "/",
        "entries": entries,
        "total": len(entries),
    }


@router.get("/read")
def read_file(path: str = Query(..., description="Relative path to file")) -> dict:
    """Read and return file content (text files only, max 512 KB)."""
    target = _safe_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    stat = target.stat()
    if stat.st_size > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({_human_size(stat.st_size)}). Max is 512 KB.",
        )

    ext = target.suffix.lower().lstrip(".")
    mime, _ = mimetypes.guess_type(target.name)

    if not _is_text(mime, ext):
        raise HTTPException(status_code=415, detail="Binary files cannot be displayed as text")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {
        "path": str(target.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "name": target.name,
        "content": content,
        "size": stat.st_size,
        "size_human": _human_size(stat.st_size),
        "mime": mime or "text/plain",
        "extension": ext,
        "modified": stat.st_mtime,
    }


@router.get("/tree")
def full_tree(depth: int = Query(3, ge=1, le=6)) -> dict:
    """Return the full EIOS workspace tree up to `depth` levels."""

    def _walk(path: Path, current_depth: int) -> dict:
        entry = _file_entry(path, WORKSPACE_ROOT)
        if path.is_dir() and current_depth < depth:
            children = []
            try:
                for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    if child.name in SKIP_DIRS:
                        continue
                    try:
                        children.append(_walk(child, current_depth + 1))
                    except OSError:
                        pass
            except PermissionError:
                pass
            entry["children"] = children
        return entry

    return _walk(WORKSPACE_ROOT, 0)


@router.get("/info")
def workspace_info() -> dict:
    """Return metadata about the EIOS workspace."""
    try:
        import psutil
        usage = psutil.disk_usage(str(WORKSPACE_ROOT))
        disk = {
            "total_gb": round(usage.total / 1024**3, 2),
            "used_gb": round(usage.used / 1024**3, 2),
            "free_gb": round(usage.free / 1024**3, 2),
            "percent": usage.percent,
        }
    except Exception:
        disk = {}

    return {
        "root": str(WORKSPACE_ROOT),
        "exists": WORKSPACE_ROOT.exists(),
        "disk": disk,
    }
