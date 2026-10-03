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
import os
import platform
import re
import sysconfig
import time
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _normalize_name(name: str) -> str:
    """PEP 427 wheel name normalization: lowercase, [^A-Za-z0-9]+ -> '_'."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).lower()


def _normalize_version(version: str) -> str:
    """Wheel filename version: '-' -> '_' only (dots are valid, required)."""
    return version.replace("-", "_")


def _python_tag() -> str:
    v = platform.python_version_tuple()
    return f"cp{v[0]}{v[1]}"


def _abi_tag(soabi: str | None = None) -> str:
    """Return the wheel ABI tag for this interpreter (``cp313``, ``cp313t``).

    ``SOABI`` has two spellings and the tag is in a different slot of each:

    - Linux/macOS: ``cpython-312-x86_64-linux-gnu`` -- tag is ``parts[1]``.
    - Windows, CPython >= 3.13: ``cp313-win_amd64`` -- the tag is already
      ``parts[0]``. Reading ``parts[1]`` here gave ``cpwin_amd64`` (gh-68).

    Windows before 3.13 has no ``SOABI`` at all, and falls through to the
    python tag. ``soabi`` is a parameter only so every shape can be tested
    on one machine; callers pass nothing.
    """
    tag = sysconfig.get_config_var("SOABI") if soabi is None else soabi
    if tag:
        parts = tag.split("-")
        if parts[0] == "cpython" and len(parts) >= 2:
            return f"cp{parts[1]}"
        if re.fullmatch(r"cp\d+t?", parts[0]):
            return parts[0]
    return _python_tag()


def _platform_tag() -> str:
    tag = sysconfig.get_platform()
    return tag.replace("-", "_").replace(".", "_")


def _zip_date_time() -> tuple[int, int, int, int, int, int]:
    """Return the zip date_time tuple for all entries.

    Reads SOURCE_DATE_EPOCH from the environment if set; otherwise uses the
    zip minimum epoch (1980-01-01) for reproducible output.
    """
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    t = time.gmtime(int(raw)) if raw is not None else time.gmtime(315532800)
    return (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


_ALWAYS_EXCLUDE = ("**/__pycache__/**", "**/*.pyc", "**/*.pyo")


def _is_excluded(rel_path: str, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatch(rel_path, pat) for pat in (*_ALWAYS_EXCLUDE, *patterns)
    )


def _sha256_record(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    import base64

    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _format_contact(person: dict[str, str], header: str) -> str | None:
    """Return a single METADATA contact header line, or None if empty."""
    name = person.get("name", "").strip()
    email = person.get("email", "").strip()
    if name and email:
        return f"{header}-email: {name} <{email}>"
    if name:
        return f"{header}: {name}"
    if email:
        return f"{header}-email: {email}"
    return None


def _metadata_bytes(
    name: str,
    version: str,
    summary: str | None = None,
    readme_text: str | None = None,
    readme_content_type: str | None = None,
    requires_python: str | None = None,
    classifiers: list[str] | None = None,
    keywords: list[str] | None = None,
    urls: dict[str, str] | None = None,
    dependencies: list[str] | None = None,
    license_expression: str | None = None,
    license_files: list[str] | None = None,
    authors: list[dict[str, str]] | None = None,
    maintainers: list[dict[str, str]] | None = None,
    optional_dependencies: dict[str, list[str]] | None = None,
) -> bytes:
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
    ]
    if summary:
        lines.append(f"Summary: {summary}")
    if license_expression:
        lines.append(f"License: {license_expression}")
    if requires_python:
        lines.append(f"Requires-Python: {requires_python}")
    for classifier in classifiers or []:
        lines.append(f"Classifier: {classifier}")
    if keywords:
        lines.append(f"Keywords: {','.join(keywords)}")
    for label, url in (urls or {}).items():
        lines.append(f"Project-URL: {label}, {url}")
    for person in authors or []:
        line = _format_contact(person, "Author")
        if line:
            lines.append(line)
    for person in maintainers or []:
        line = _format_contact(person, "Maintainer")
        if line:
            lines.append(line)
    for dep in dependencies or []:
        lines.append(f"Requires-Dist: {dep}")
    for extra, extra_deps in (optional_dependencies or {}).items():
        lines.append(f"Provides-Extra: {extra}")
        for dep in extra_deps:
            lines.append(f'Requires-Dist: {dep} ; extra == "{extra}"')
    for lf in license_files or []:
        lines.append(f"License-File: {lf}")
    if readme_content_type:
        lines.append(f"Description-Content-Type: {readme_content_type}")
    lines.append("")  # blank line before body
    if readme_text:
        lines.append(readme_text)
    return "\n".join(lines).encode()


def _entry_points_bytes(scripts: dict[str, str]) -> bytes:
    """Return entry_points.txt content for a console_scripts mapping."""
    lines = ["[console_scripts]"]
    lines += [f"{name} = {ref}" for name, ref in sorted(scripts.items())]
    return ("\n".join(lines) + "\n").encode()


def _wheel_meta_bytes(
    py_tag: str, abi_tag: str, plat_tag: str, pure: bool = False
) -> bytes:
    return (
        f"Wheel-Version: 1.0\n"
        f"Generator: just-buildit\n"
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
    classifiers: list[str] | None = None,
    keywords: list[str] | None = None,
    urls: dict[str, str] | None = None,
    dependencies: list[str] | None = None,
    license_expression: str | None = None,
    license_files: list[str] | None = None,
    authors: list[dict[str, str]] | None = None,
    maintainers: list[dict[str, str]] | None = None,
    optional_dependencies: dict[str, list[str]] | None = None,
    scripts: dict[str, str] | None = None,
) -> Path:
    """Write a .dist-info directory for prepare_metadata_for_build_wheel."""
    norm_name = _normalize_name(name)
    norm_version = _normalize_version(version)
    dist_info = metadata_dir / f"{norm_name}-{norm_version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_bytes(
        _metadata_bytes(
            name,
            version,
            summary=summary,
            readme_text=readme_text,
            readme_content_type=readme_content_type,
            requires_python=requires_python,
            classifiers=classifiers,
            keywords=keywords,
            urls=urls,
            dependencies=dependencies,
            license_expression=license_expression,
            license_files=license_files,
            authors=authors,
            maintainers=maintainers,
            optional_dependencies=optional_dependencies,
        )
    )
    (dist_info / "WHEEL").write_bytes(
        _wheel_meta_bytes(_python_tag(), _abi_tag(), _platform_tag())
    )
    if scripts:
        (dist_info / "entry_points.txt").write_bytes(
            _entry_points_bytes(scripts)
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
    classifiers: list[str] | None = None,
    keywords: list[str] | None = None,
    urls: dict[str, str] | None = None,
    dependencies: list[str] | None = None,
    license_expression: str | None = None,
    license_files: list[str] | None = None,
    authors: list[dict[str, str]] | None = None,
    maintainers: list[dict[str, str]] | None = None,
    optional_dependencies: dict[str, list[str]] | None = None,
    scripts: dict[str, str] | None = None,
) -> Path:
    """Package everything in output_dir into a wheel and write it to wheel_dir.

    output_dir is the wheel content root — directory structure is
    preserved. Returns the path to the wheel file.
    """
    norm_name = _normalize_name(name)
    norm_version = _normalize_version(version)

    _exclude = exclude or []
    content_paths = sorted(
        p
        for p in output_dir.rglob("*")
        if p.is_file()
        and not _is_excluded(str(p.relative_to(output_dir)), _exclude)
    )

    # Read each content file once; reuse the bytes for RECORD and zip writing.
    content = [
        (str(p.relative_to(output_dir)), p.read_bytes()) for p in content_paths
    ]

    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ""
    pure = not any(arcname.endswith(ext_suffix) for arcname, _ in content)

    if pure:
        py_tag, abi_tag, plat_tag = "py3", "none", "any"
    else:
        py_tag = _python_tag()
        abi_tag = _abi_tag()
        plat_tag = _platform_tag()

    wheel_name = (
        f"{norm_name}-{norm_version}-{py_tag}-{abi_tag}-{plat_tag}.whl"
    )
    wheel_path = wheel_dir / wheel_name
    dist_info = f"{norm_name}-{norm_version}.dist-info"

    metadata = _metadata_bytes(
        name,
        version,
        summary=summary,
        readme_text=readme_text,
        readme_content_type=readme_content_type,
        requires_python=requires_python,
        classifiers=classifiers,
        keywords=keywords,
        urls=urls,
        dependencies=dependencies,
        license_expression=license_expression,
        license_files=license_files,
        authors=authors,
        maintainers=maintainers,
        optional_dependencies=optional_dependencies,
    )
    wheel_meta = _wheel_meta_bytes(py_tag, abi_tag, plat_tag, pure=pure)
    entry_points = _entry_points_bytes(scripts) if scripts else None

    record_entries: list[tuple[str, str, int]] = []

    def _record(arcname: str, data: bytes) -> None:
        record_entries.append((arcname, _sha256_record(data), len(data)))

    for arcname, data in content:
        _record(arcname, data)
    _record(f"{dist_info}/METADATA", metadata)
    _record(f"{dist_info}/WHEEL", wheel_meta)
    if entry_points:
        _record(f"{dist_info}/entry_points.txt", entry_points)

    record_arcname = f"{dist_info}/RECORD"
    record_buf = io.StringIO()
    writer = csv.writer(record_buf)
    for entry in record_entries:
        writer.writerow(entry)
    writer.writerow([record_arcname, "", ""])
    record_data = record_buf.getvalue().encode()

    date_time = _zip_date_time()
    wheel_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(
        wheel_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as zf:

        def _write(arcname: str, data: bytes) -> None:
            zi = zipfile.ZipInfo(arcname, date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, data)

        for arcname, data in content:
            _write(arcname, data)
        _write(f"{dist_info}/METADATA", metadata)
        _write(f"{dist_info}/WHEEL", wheel_meta)
        if entry_points:
            _write(f"{dist_info}/entry_points.txt", entry_points)
        _write(record_arcname, record_data)

    print(f"just-buildit: wrote raw wheel -> {wheel_path}", flush=True)
    return wheel_path
