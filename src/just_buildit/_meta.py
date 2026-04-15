"""
_meta.py — parse pyproject.toml for just-buildit.

Extracts:
  - project.name
  - project.version
  - project.description           (optional → METADATA Summary)
  - project.readme                (optional → METADATA Description + content-type)
  - project.requires-python       (optional → METADATA Requires-Python)
  - tool.just-buildit.command        (optional; omit for zero-config src/{name}/ default)
  - tool.just-buildit.repair         (optional; auto-detected if omitted, False to skip)
  - tool.just-buildit.editable_path  (optional; src root for .pth editable installs)
"""

from __future__ import annotations

import tomllib

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

_CONTENT_TYPES = {".md": "text/markdown", ".rst": "text/x-rst", ".txt": "text/plain"}


@dataclass
class BuildConfig:
    name: str
    version: str
    command: str | None                  # None = zero-config src/{package}/ default
    repair: str | Literal[False] | None  # None = auto-detect
    package: str | None = None           # package dir name; defaults to normalized project name
    exclude: list[str] = field(default_factory=list)
    editable_path: str | None = None     # src root for .pth-file editable installs
    summary: str | None = None
    readme_text: str | None = None
    readme_content_type: str | None = None
    requires_python: str | None = None


_MISSING = object()


def _read_readme(project_root: Path, raw: str | dict) -> tuple[str | None, str | None]:
    """Return (text, content_type) from a project.readme value."""
    if isinstance(raw, str):
        path = project_root / raw
        text = path.read_text(encoding="utf-8") if path.exists() else None
        content_type = _CONTENT_TYPES.get(Path(raw).suffix.lower(), "text/plain")
        return text, content_type
    # table form: {file = "..."} or {text = "...", content-type = "..."}
    content_type = raw.get("content-type", "text/plain")
    if "file" in raw:
        path = project_root / raw["file"]
        text = path.read_text(encoding="utf-8") if path.exists() else None
    else:
        text = raw.get("text")
    return text, content_type


def load(project_root: Path) -> BuildConfig:
    toml_path = project_root / "pyproject.toml"
    if not toml_path.exists():
        raise FileNotFoundError(f"No pyproject.toml found in {project_root}")

    with toml_path.open("rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})

    name = project.get("name")
    if not name:
        raise ValueError("[project] name is required in pyproject.toml")

    version = project.get("version")
    if not version:
        raise ValueError("[project] version is required in pyproject.toml")

    jb = data.get("tool", {}).get("just-buildit", {})

    command = jb.get("command") or None        # None → zero-config src/{package}/ default
    package = jb.get("package") or None        # override package dir name for src/ lookup
    editable_path = jb.get("editable_path") or None  # src root for .pth editable installs
    exclude = jb.get("exclude", [])

    raw_repair = jb.get("repair", _MISSING)
    if raw_repair is _MISSING:
        repair = None  # auto-detect
    elif raw_repair is False:
        repair = False  # explicitly disabled
    else:
        repair = str(raw_repair)

    readme_text, readme_content_type = None, None
    raw_readme = project.get("readme")
    if raw_readme:
        readme_text, readme_content_type = _read_readme(project_root, raw_readme)

    return BuildConfig(
        name=name,
        version=version,
        command=command,
        repair=repair,
        package=package,
        exclude=exclude,
        editable_path=editable_path,
        summary=project.get("description") or None,
        readme_text=readme_text,
        readme_content_type=readme_content_type,
        requires_python=project.get("requires-python") or None,
    )
