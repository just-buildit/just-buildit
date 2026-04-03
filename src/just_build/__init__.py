"""
just-build — minimum viable PEP 517 build backend for C extensions.

Public surface (PEP 517):
  get_requires_for_build_wheel()
  prepare_metadata_for_build_wheel()
  build_wheel()
  build_editable()
"""

from __future__ import annotations

__version__ = "0.1.0"

import tempfile
from pathlib import Path

from . import _build, _meta, _wheel
from ._wheel import _normalize_name


def get_requires_for_build_wheel(config_settings=None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings=None,
) -> str:
    config = _meta.load(Path.cwd())
    from . import _wheel as w
    dist_info = w._write_dist_info(
        name=config.name,
        version=config.version,
        metadata_dir=Path(metadata_directory),
        summary=config.summary,
        readme_text=config.readme_text,
        readme_content_type=config.readme_content_type,
        requires_python=config.requires_python,
    )
    return dist_info.name


def build_editable(
    wheel_directory: str,
    config_settings=None,
    metadata_directory: str | None = None,
) -> str:
    project_root = Path.cwd()
    wheel_dir = Path(wheel_directory)
    config = _meta.load(project_root)

    if config.editable_path is None:
        # No editable_path configured — fall back to a full wheel build.
        return build_wheel(wheel_directory, config_settings, metadata_directory)

    # Fast path: write a .pth file pointing at the source tree.
    # No build command is run; the C extension must already be compiled in place.
    with tempfile.TemporaryDirectory(prefix="just-build-") as tmp:
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()

        pth_target = (project_root / config.editable_path).resolve()
        pth_name = _normalize_name(config.name) + ".pth"
        (output_dir / pth_name).write_text(str(pth_target) + "\n", encoding="utf-8")

        wheel_path = _wheel.build_wheel(
            name=config.name,
            version=config.version,
            output_dir=output_dir,
            wheel_dir=wheel_dir,
            exclude=[],
            summary=config.summary,
            readme_text=config.readme_text,
            readme_content_type=config.readme_content_type,
            requires_python=config.requires_python,
        )

    return wheel_path.name


def build_wheel(
    wheel_directory: str,
    config_settings=None,
    metadata_directory: str | None = None,
) -> str:
    project_root = Path.cwd()
    wheel_dir = Path(wheel_directory)

    config = _meta.load(project_root)

    with tempfile.TemporaryDirectory(prefix="just-build-") as tmp:
        output_dir = Path(tmp) / "output"

        # Step 1: build → output_dir (the wheel content root)
        package = config.package or _normalize_name(config.name)
        output_dir = _build.run_build(
            name=config.name,
            package=package,
            command=config.command,
            output_dir=output_dir,
            project_root=project_root,
        )

        # Step 2: assemble wheel from everything in output_dir
        raw_wheel = _wheel.build_wheel(
            name=config.name,
            version=config.version,
            output_dir=output_dir,
            wheel_dir=wheel_dir,
            exclude=config.exclude,
            summary=config.summary,
            readme_text=config.readme_text,
            readme_content_type=config.readme_content_type,
            requires_python=config.requires_python,
        )

        # Step 3: repair (auditwheel / delocate / delvewheel)
        final_wheel = _build.run_repair(
            wheel_path=raw_wheel,
            wheel_dir=wheel_dir,
            repair_command=config.repair,
        )

    return final_wheel.name
