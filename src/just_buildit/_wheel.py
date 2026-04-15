"""
_wheel.py — assemble a PEP 427 wheel from a compiled extension.

Produces a structurally correct wheel (zip archive) containing:
  - The compiled extension (.so / .pyd)
  - {name}-{version}.dist-info/METADATA
  - {name}-{version}.dist-info/WHEEL
  - {name}-{version}.dist-info/RECORD

Platform tag is derived from sysconfig; auditwheel/delocate will upgrade
it to the appropriate manylinux/universal2 tag during the repair step.
"""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import io
import platform
import re
import sysconfig
import zipfile
from pathlib import Path


def _normalize_name(name: str) -> str:
    """PEP 427 wheel name normalization: lowercase, replace runs of [^A-Za-z0-9] with '_'."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).lower()


def _normalize_version(version: str) -> str:
    """Wheel filename version: replace '-' with '_' only (dots are valid and required)."""
    return version.replace("-", "_")


def _python_tag() -> str:
    v = platform.python_version_tuple()
    return f"cp{v[0]}{v[1]}"


def _abi_tag() -> str:
    tag = sysconfig.get_config_var("SOABI")
    if tag:
        # SOABI is like "cpython-312-x86_64-linux-gnu"; we want "cp312"
        parts = tag.split("-")
        if len(parts) >= 2:
            return f"cp{parts[1]}"
    return _python_tag()


def _platform_tag() -> str:
    tag = sysconfig.get_platform()
    return tag.replace("-", "_").replace(".", "_")


_ALWAYS_EXCLUDE = ("**/__pycache__/**", "**/*.pyc", "**/*.pyo")


def _is_excluded(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pat) for pat in (*_ALWAYS_EXCLUDE, *patterns))


def _sha256_record(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    import base64
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _metadata_bytes(
    name: str,
    version: str,
    summary: str | None = None,
    readme_text: str | None = None,
    readme_content_type: str | None = None,
    requires_python: str | None = None,
) -> bytes:
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
    ]
    if summary:
        lines.append(f"Summary: {summary}")
    if requires_python:
        lines.append(f"Requires-Python: {requires_python}")
    if readme_content_type:
        lines.append(f"Description-Content-Type: {readme_content_type}")
    lines.append("")  # blank line before body
    if readme_text:
        lines.append(readme_text)
    return "\n".join(lines).encode()


def _wheel_meta_bytes(py_tag: str, abi_tag: str, plat_tag: str, pure: bool = False) -> bytes:
    return (
        f"Wheel-Version: 1.0\n"
        f"Generator: just-build\n"
        f"Root-Is-Purelib: {'true' if pure else 'false'}\n"
        f"Tag: {py_tag}-{abi_tag}-{plat_tag}\n"
    ).encode()


def _write_dist_info(
    *,
    name: str,
    version: str,
    metadata_dir: Path,
    summary: str | None = None,
    readme_text: str | None = None,
    readme_content_type: str | None = None,
    requires_python: str | None = None,
) -> Path:
    """Write a .dist-info directory for prepare_metadata_for_build_wheel."""
    norm_name = _normalize_name(name)
    norm_version = _normalize_version(version)
    dist_info = metadata_dir / f"{norm_name}-{norm_version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_bytes(_metadata_bytes(
        name, version,
        summary=summary,
        readme_text=readme_text,
        readme_content_type=readme_content_type,
        requires_python=requires_python,
    ))
    (dist_info / "WHEEL").write_bytes(
        _wheel_meta_bytes(_python_tag(), _abi_tag(), _platform_tag())
    )
    return dist_info


def build_wheel(
    *,
    name: str,
    version: str,
    output_dir: Path,
    wheel_dir: Path,
    exclude: list[str] | None = None,
    summary: str | None = None,
    readme_text: str | None = None,
    readme_content_type: str | None = None,
    requires_python: str | None = None,
) -> Path:
    """
    Package everything in output_dir into a wheel and write it to wheel_dir.
    output_dir is the wheel content root — directory structure is preserved.
    Returns the path to the wheel file.
    """
    norm_name = _normalize_name(name)
    norm_version = _normalize_version(version)

    # Collect all files from output_dir, preserving tree structure
    _exclude = exclude or []
    content_files = sorted(
        p for p in output_dir.rglob("*")
        if p.is_file() and not _is_excluded(str(p.relative_to(output_dir)), _exclude)
    )

    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ""
    pure = not any(str(p).endswith(ext_suffix) for p in content_files)

    if pure:
        py_tag, abi_tag, plat_tag = "py3", "none", "any"
    else:
        py_tag = _python_tag()
        abi_tag = _abi_tag()
        plat_tag = _platform_tag()

    wheel_name = f"{norm_name}-{norm_version}-{py_tag}-{abi_tag}-{plat_tag}.whl"
    wheel_path = wheel_dir / wheel_name
    dist_info = f"{norm_name}-{norm_version}.dist-info"

    metadata = _metadata_bytes(
        name, version,
        summary=summary,
        readme_text=readme_text,
        readme_content_type=readme_content_type,
        requires_python=requires_python,
    )
    wheel_meta = _wheel_meta_bytes(py_tag, abi_tag, plat_tag, pure=pure)

    record_entries: list[tuple[str, str, int]] = []

    def add(arcname: str, data: bytes) -> None:
        record_entries.append((arcname, _sha256_record(data), len(data)))

    for path in content_files:
        add(str(path.relative_to(output_dir)), path.read_bytes())
    add(f"{dist_info}/METADATA", metadata)
    add(f"{dist_info}/WHEEL", wheel_meta)
    # RECORD itself has an empty hash entry per spec
    record_arcname = f"{dist_info}/RECORD"

    record_buf = io.StringIO()
    writer = csv.writer(record_buf)
    for entry in record_entries:
        writer.writerow(entry)
    writer.writerow([record_arcname, "", ""])
    record_data = record_buf.getvalue().encode()

    wheel_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in content_files:
            zf.writestr(str(path.relative_to(output_dir)), path.read_bytes())
        zf.writestr(f"{dist_info}/METADATA", metadata)
        zf.writestr(f"{dist_info}/WHEEL", wheel_meta)
        zf.writestr(record_arcname, record_data)

    print(f"just-build: wrote raw wheel -> {wheel_path}", flush=True)
    return wheel_path
