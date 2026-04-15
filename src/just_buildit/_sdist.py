"""
_sdist.py — build a PEP 625 source distribution (.tar.gz).

Produces {name}-{version}.tar.gz with a top-level {name}-{version}/ directory.
Includes all project files except build artifacts, VCS data, and caches.
"""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

_EXCLUDE_DIRS = frozenset({
    ".git", ".hg", ".svn",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build",
    ".tox", ".venv", "venv", "env",
})
_EXCLUDE_SUFFIXES = frozenset({".pyc", ".pyo"})


def _collect_files(project_root: Path) -> list[Path]:
    """Walk project_root and return source files to include in the sdist."""
    files = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_root)
        parts = rel.parts
        if any(p in _EXCLUDE_DIRS for p in parts):
            continue
        if any(p.endswith(".egg-info") for p in parts):
            continue
        if path.suffix in _EXCLUDE_SUFFIXES:
            continue
        files.append(path)
    return files


def build_sdist(project_root: Path, sdist_dir: Path, config) -> Path:
    """Build a .tar.gz source distribution. Returns the path to the archive."""
    from ._wheel import _metadata_bytes, _normalize_name, _normalize_version

    norm_name = _normalize_name(config.name)
    norm_version = _normalize_version(config.version)
    top = f"{norm_name}-{norm_version}"
    sdist_path = sdist_dir / f"{top}.tar.gz"

    pkg_info = _metadata_bytes(
        config.name, config.version,
        summary=config.summary,
        readme_text=config.readme_text,
        readme_content_type=config.readme_content_type,
        requires_python=config.requires_python,
    )

    mtime = int(time.time())

    with tarfile.open(sdist_path, "w:gz") as tf:
        # PKG-INFO first (convention)
        info = tarfile.TarInfo(f"{top}/PKG-INFO")
        info.size = len(pkg_info)
        info.mtime = mtime
        tf.addfile(info, io.BytesIO(pkg_info))

        for file_path in _collect_files(project_root):
            rel = file_path.relative_to(project_root)
            tf.add(str(file_path), arcname=f"{top}/{rel}")

    print(f"just-buildit: wrote sdist -> {sdist_path}", flush=True)
    return sdist_path
