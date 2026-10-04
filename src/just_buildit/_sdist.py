"""
_sdist.py — build a PEP 625 source distribution (.tar.gz).

Produces {name}-{version}.tar.gz with a top-level {name}-{version}/ directory.
Includes all project files except build artifacts, VCS data, and caches.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _meta

_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        # The underscore spelling is just as conventional as `build` and was
        # missing, so an sdist built in a tree where anything had been
        # compiled swept the artifacts in. Measured on this repo: a local
        # 0.3.11 sdist carried 92 entries under `examples/`, 62 of them object
        # files, ninja logs and meson caches from `examples/*/_build/`. The
        # published one has 30, because CI builds from a fresh checkout --
        # which is exactly why the release path could not see this.
        "_build",
        ".tox",
        ".venv",
        "venv",
        "env",
    }
)
_EXCLUDE_SUFFIXES = frozenset({".pyc", ".pyo"})


def _build_epoch() -> int:
    """Return the timestamp to use for all archive entries.

    Reads SOURCE_DATE_EPOCH from the environment if set; otherwise returns the
    zip/tar minimum epoch (1980-01-01 00:00:00 UTC) for reproducible output.
    """
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw is not None:
        return int(raw)
    return 315532800  # 1980-01-01 00:00:00 UTC


def _collect_files(project_root: Path) -> list[Path]:
    """Walk project_root, pruning excluded dirs; return files for the sdist."""
    files = []
    for dirpath, dirs, filenames in os.walk(project_root, topdown=True):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in _EXCLUDE_DIRS and not d.endswith(".egg-info")
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix in _EXCLUDE_SUFFIXES:
                continue
            files.append(path)
    return files


def build_sdist(
    project_root: Path, sdist_dir: Path, config: _meta.BuildConfig
) -> Path:
    """Build a .tar.gz source distribution. Returns the path to the archive."""
    from ._wheel import _metadata_bytes, _normalize_name, _normalize_version

    norm_name = _normalize_name(config.name)
    norm_version = _normalize_version(config.version)
    top = f"{norm_name}-{norm_version}"
    sdist_path = sdist_dir / f"{top}.tar.gz"

    pkg_info = _metadata_bytes(
        config.name,
        config.version,
        summary=config.summary,
        readme_text=config.readme_text,
        readme_content_type=config.readme_content_type,
        requires_python=config.requires_python,
        classifiers=config.classifiers or None,
        keywords=config.keywords or None,
        urls=config.urls or None,
        dependencies=config.dependencies or None,
        license_expression=config.license_expression,
        license_files=config.license_files or None,
        authors=config.authors or None,
        maintainers=config.maintainers or None,
        optional_dependencies=config.optional_dependencies or None,
    )

    mtime = _build_epoch()

    with tarfile.open(sdist_path, "w:gz") as tf:
        # PKG-INFO first (convention)
        info = tarfile.TarInfo(f"{top}/PKG-INFO")
        info.size = len(pkg_info)
        info.mtime = mtime
        tf.addfile(info, io.BytesIO(pkg_info))

        for file_path in _collect_files(project_root):
            rel = file_path.relative_to(project_root)
            data = file_path.read_bytes()
            # as_posix: tar member names are always '/'-separated.
            ti = tarfile.TarInfo(name=f"{top}/{rel.as_posix()}")
            ti.size = len(data)
            ti.mtime = mtime
            ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(data))

    print(f"just-buildit: wrote sdist -> {sdist_path}", flush=True)
    return sdist_path
