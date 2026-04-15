"""
_cli.py — just-buildit command-line interface.
"""

from __future__ import annotations

import sys
from pathlib import Path


_USAGE = """\
Usage: just-buildit <command> [options]

Commands:
  inspect        Dry-run: show build configuration and what would happen
  build [DIR]    Build wheel into DIR (default: dist/)
  sdist [DIR]    Build source distribution into DIR (default: dist/)
  help           Show this message
"""


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(_USAGE, end="")
    elif args[0] == "inspect":
        _inspect()
    elif args[0] == "build":
        _build(args[1:])
    elif args[0] == "sdist":
        _sdist_cmd(args[1:])
    else:
        print(f"just-buildit: unknown command '{args[0]}'", file=sys.stderr)
        print("Run 'just-buildit help' for usage.", file=sys.stderr)
        sys.exit(1)


def _inspect() -> None:
    from . import _build, _meta
    from ._wheel import _abi_tag, _normalize_name, _normalize_version, _platform_tag, _python_tag
    import sysconfig

    project_root = Path.cwd()
    try:
        config = _meta.load(project_root)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    norm_name = _normalize_name(config.name)
    norm_version = _normalize_version(config.version)
    package = config.package or norm_name
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ""
    include_dir = sysconfig.get_path("include")

    print(f"just-buildit inspect  {project_root}")
    print()
    print(f"  name:            {config.name}")
    print(f"  version:         {config.version}")
    if config.summary:
        print(f"  summary:         {config.summary}")
    if config.requires_python:
        print(f"  requires-python: {config.requires_python}")
    print(f"  package dir:     {package}")
    if config.editable_path:
        print(f"  editable_path:   {config.editable_path}")
    if config.exclude:
        print(f"  exclude:         {config.exclude}")
    print()

    # Build mode
    if config.command is None:
        src_dir = project_root / "src" / package
        c_files = sorted(src_dir.rglob("*.c")) if src_dir.is_dir() else []
        pure = not bool(c_files)
        print(f"  build mode:      zero-config  (src/{package}/)")
        if c_files:
            print(f"  sources:")
            for f in c_files:
                print(f"    {f.relative_to(project_root)}")
        else:
            print(f"  sources:         (none — pure Python)")
    else:
        pure = False  # can't determine without running the build
        ldflags = " ".join(_build._ldflags())
        libs = " ".join(_build._python_link_flags())
        print(f"  build mode:      custom command")
        print(f"  command:         {config.command}")
        print(f"  env vars:")
        print(f"    JUST_BUILDIT_NAME        = {config.name}")
        print(f"    JUST_BUILDIT_PYTHON      = {sys.executable}")
        print(f"    JUST_BUILDIT_INCLUDE_DIR = {include_dir}")
        print(f"    JUST_BUILDIT_OUTPUT_DIR  = <tempdir>/output")
        print(f"    JUST_BUILDIT_EXT_SUFFIX  = {ext_suffix}")
        print(f"    JUST_BUILDIT_LDFLAGS     = {ldflags}")
        if libs:
            print(f"    JUST_BUILDIT_LIBS        = {libs}")
    print()

    # Repair
    if config.repair is False:
        print(f"  repair:          disabled")
    elif config.repair is None:
        auto = _build._auto_repair_command()
        print(f"  repair:          auto → {auto or '(none for this platform)'}")
    else:
        print(f"  repair:          {config.repair}")
    print()

    # Predicted wheel filename
    if pure:
        wheel_name = f"{norm_name}-{norm_version}-py3-none-any.whl"
    else:
        wheel_name = (
            f"{norm_name}-{norm_version}"
            f"-{_python_tag()}-{_abi_tag()}-{_platform_tag()}.whl"
        )
    print(f"  wheel:           {wheel_name}")
    if config.command is not None:
        print(f"  (platform tag is pre-repair; auditwheel/delocate may upgrade it)")


def _build(rest: list[str]) -> None:
    from . import build_wheel

    wheel_dir = Path(rest[0]) if rest else Path("dist")
    wheel_dir.mkdir(parents=True, exist_ok=True)

    try:
        name = build_wheel(str(wheel_dir))
        print(f"just-buildit: {wheel_dir / name}")
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def _sdist_cmd(rest: list[str]) -> None:
    from . import build_sdist

    sdist_dir = Path(rest[0]) if rest else Path("dist")
    sdist_dir.mkdir(parents=True, exist_ok=True)

    try:
        name = build_sdist(str(sdist_dir))
        print(f"just-buildit: {sdist_dir / name}")
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
