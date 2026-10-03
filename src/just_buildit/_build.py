"""
_build.py — invoke the user's build command and verify the output.

Contract:
  - Set JUST_BUILDIT_* env vars
  - Call the user's command via subprocess
  - Verify the expected output file exists
  - Return the path to the built extension

Environment variables set for the build command:
  JUST_BUILDIT_NAME          extension module name (e.g. "hello")
  JUST_BUILDIT_PYTHON        path to the running Python interpreter
  JUST_BUILDIT_INCLUDE_DIR   Python C header directory
  JUST_BUILDIT_OUTPUT_DIR    directory where the .so/.pyd must be placed
  JUST_BUILDIT_EXT_SUFFIX    full extension suffix
                             (e.g. .cpython-312-x86_64-linux-gnu.so)
  JUST_BUILDIT_LDFLAGS       platform link flags (before sources)
  JUST_BUILDIT_LIBS          Python import library (Windows only; clang-cl)
"""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import Literal

_REPAIR_COMMANDS = {
    "Linux": "uvx auditwheel repair",
    "Darwin": "uvx --from delocate delocate-wheel",
    "Windows": "uvx delvewheel repair",
}


def _auto_repair_command() -> str | None:
    """Return the platform-appropriate wheel repair command, or None."""
    return _REPAIR_COMMANDS.get(platform.system())


def _ldflags() -> list[str]:
    """Return platform-appropriate shared-library link flags.

    Windows is clang-cl against native CPython (the MSVC ABI), so the flag
    is MSVC's ``/LD`` (build a DLL), not gcc's ``-shared``.
    """
    if platform.system() == "Darwin":
        return ["-dynamiclib", "-undefined", "dynamic_lookup"]
    if platform.system() == "Windows":
        return ["/LD"]
    return ["-shared", "-fPIC"]


def _python_link_flags() -> list[str]:
    """Return the Python import library a Windows extension must link.

    Linux/macOS resolve Python symbols at runtime (dynamic lookup / system
    linker); Windows requires them at link time, so the one item returned is
    the path to ``python3X.lib`` -- a plain input file to clang-cl, which
    needs no ``-L`` / ``-l`` spelling. Forward slashes, so the path survives
    a Makefile and a POSIX shell unmangled.

    The library lives under ``sys.base_prefix``, NOT next to
    ``sys.executable``: a PEP 517 build runs in an isolated venv, whose
    python.exe sits in ``<venv>/Scripts/`` -- which is every ``pip wheel`` /
    ``uv build`` on Windows. The executable's parent stays as a fallback for
    an interpreter run outside any venv.
    """
    if platform.system() != "Windows":
        return []
    major = sys.version_info.major
    minor = sys.version_info.minor
    install_root = Path(sys.executable).parent
    libs_dirs = list(
        dict.fromkeys([Path(sys.base_prefix) / "libs", install_root / "libs"])
    )
    for libs_dir in libs_dirs:
        lib = libs_dir / f"python{major}{minor}.lib"
        if lib.exists():
            return [lib.as_posix()]

    raise RuntimeError(
        f"Could not find Python {major}.{minor} import library "
        f"(python{major}{minor}.lib) on Windows.\n\n"
        "Searched:\n" + "\n".join(f"  {d}" for d in libs_dirs) + "\n\n"
        "Install CPython from python.org (or `uv python install`) to get a "
        "complete distribution; just-buildit builds Windows extensions "
        "with clang-cl against it."
    )


def _cc() -> str:
    """Return the C compiler: $CC, else clang-cl on Windows, cc elsewhere."""
    return os.environ.get(
        "CC", "clang-cl" if platform.system() == "Windows" else "cc"
    )


# What the MSVC linker leaves beside a DLL build. None belongs in a wheel:
# the import library and export file are for LINKING against the extension,
# which nothing does, and the objects are intermediate.
_WINDOWS_BYPRODUCTS = ("*.exp", "*.obj")


def _drop_windows_byproducts(output_dir: Path, ext_suffix: str) -> None:
    """Remove the files a clang-cl/MSVC DLL link leaves in ``output_dir``.

    ``/LD`` always writes ``<name>.lib`` and ``<name>.exp`` beside the
    ``.pyd``, and ``output_dir`` is packaged verbatim, so without this every
    wheel would carry an import library nothing can use. Only the ``.lib``
    that shares a ``.pyd``'s stem is removed: a package that ships its own
    static library keeps it.
    """
    if platform.system() != "Windows":
        return
    for pyd in output_dir.rglob(f"*{ext_suffix}"):
        pyd.with_suffix(".lib").unlink(missing_ok=True)
    for pattern in _WINDOWS_BYPRODUCTS:
        for f in output_dir.rglob(pattern):
            f.unlink()


def _run_default(cmd: list[str], project_root: Path) -> None:
    """Run the zero-config compile command, failing loudly."""
    print(f"just-buildit: default build: {shlex.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(project_root))
    if result.returncode != 0:
        raise RuntimeError(
            f"Default build failed with exit code {result.returncode}"
        )


def _default_build(
    *,
    name: str,
    package: str,
    output_dir: Path,
    project_root: Path,
    include_dir: str,
    ext_suffix: str,
    pure: bool = False,
) -> bool:
    """Compile all *.c files from src/{package}/; copy the rest verbatim.

    Returns True if C extensions were compiled, False for pure-Python
    packages.

    With pure=True, no compilation happens and the src/{package}/ tree is
    copied verbatim — including any .c/.h files, which are treated as package
    data rather than extension sources.
    """
    src_dir = project_root / "src" / package
    if not src_dir.is_dir():
        raise FileNotFoundError(
            f"No command set in [tool.just-buildit] and no src/{package}/ "
            f"directory found.\n\n"
            f"For zero-config builds, put your sources in src/{package}/\n"
            f"Or set a build command:\n\n"
            f"  [tool.just-buildit]\n"
            f'  command = "make"\n'
        )

    c_files = [] if pure else sorted(src_dir.rglob("*.c"))
    if c_files:
        output = output_dir / f"{name}{ext_suffix}"
        py_libs = _python_link_flags()
        if platform.system() == "Windows":
            # clang-cl spells the output /Fe: and would drop an .obj per
            # source in the project root; /Fo sends them to a scratch dir.
            with tempfile.TemporaryDirectory() as objdir:
                cmd = [
                    _cc(),
                    *_ldflags(),
                    "/O2",
                    f"/I{include_dir}",
                    *[str(f) for f in c_files],
                    f"/Fo{Path(objdir).as_posix()}/",
                    f"/Fe:{output}",
                    *py_libs,
                ]
                _run_default(cmd, project_root)
        else:
            cmd = [
                _cc(),
                *_ldflags(),
                "-O2",
                f"-I{include_dir}",
                *[str(f) for f in c_files],
                "-o",
                str(output),
                *py_libs,
            ]
            _run_default(cmd, project_root)
    elif pure:
        print(
            f"just-buildit: pure-Python package — copying "
            f"src/{package}/ verbatim",
            flush=True,
        )
    else:
        print(
            f"just-buildit: no .c files in src/{package}/ — "
            f"pure Python package",
            flush=True,
        )

    # Copy all non-source files (Python sources, data, etc.) preserving tree
    # structure. .c and .h normally stay behind — they have no place in a
    # wheel — but with pure=True they are kept as package data (e.g. bundled
    # example sources). Pure Python packages go into a {package}/ subdir so
    # `import {package}` works. C extension packages put files at the root
    # alongside the compiled .so.
    _skip: set[str] = set() if pure else {".c", ".h"}
    pkg_out = output_dir / package if not c_files else output_dir
    for src_file in src_dir.rglob("*"):
        if src_file.is_file() and src_file.suffix not in _skip:
            dst = pkg_out / src_file.relative_to(src_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src_file.read_bytes())

    return bool(c_files)


def _make_env(*, name: str, output_dir: Path) -> tuple[dict[str, str], str]:
    """Return (env, ext_suffix) for a build command invocation.

    Sets JUST_BUILDIT_* variables in a copy of os.environ. Raises
    RuntimeError if sysconfig cannot supply required values.
    """
    include_dir = sysconfig.get_path("include")
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not include_dir:
        raise RuntimeError(
            "Could not determine Python include directory via sysconfig."
        )
    if not ext_suffix:
        raise RuntimeError(
            "Could not determine extension suffix via sysconfig."
        )
    env = os.environ.copy()
    # Paths are handed over '/'-separated (as_posix, a no-op off Windows): a
    # build command usually runs them through make and sh, where an unquoted
    # C:\\Users\\... loses its backslashes as escapes and the files land in a
    # garbage relative path. Windows and clang-cl accept '/' everywhere.
    env.update(
        {
            "JUST_BUILDIT_NAME": name,
            "JUST_BUILDIT_PYTHON": Path(sys.executable).as_posix(),
            "JUST_BUILDIT_INCLUDE_DIR": Path(include_dir).as_posix(),
            "JUST_BUILDIT_OUTPUT_DIR": output_dir.as_posix(),
            "JUST_BUILDIT_EXT_SUFFIX": ext_suffix,
            "JUST_BUILDIT_LDFLAGS": " ".join(_ldflags()),
            "JUST_BUILDIT_LIBS": "",
        }
    )
    return env, ext_suffix


def _print_env(env: dict[str, str], ext_suffix: str) -> None:
    print(
        f"  JUST_BUILDIT_NAME        = {env['JUST_BUILDIT_NAME']}", flush=True
    )
    print(
        f"  JUST_BUILDIT_PYTHON      = {env['JUST_BUILDIT_PYTHON']}",
        flush=True,
    )
    print(
        f"  JUST_BUILDIT_INCLUDE_DIR = {env['JUST_BUILDIT_INCLUDE_DIR']}",
        flush=True,
    )
    print(
        f"  JUST_BUILDIT_OUTPUT_DIR  = {env['JUST_BUILDIT_OUTPUT_DIR']}",
        flush=True,
    )
    print(f"  JUST_BUILDIT_EXT_SUFFIX  = {ext_suffix}", flush=True)
    print(
        f"  JUST_BUILDIT_LDFLAGS     = {env['JUST_BUILDIT_LDFLAGS']}",
        flush=True,
    )
    if env["JUST_BUILDIT_LIBS"]:
        print(
            f"  JUST_BUILDIT_LIBS        = {env['JUST_BUILDIT_LIBS']}",
            flush=True,
        )


def run_build(
    *,
    name: str,
    package: str,
    command: str | None,
    output_dir: Path,
    project_root: Path,
    pure: bool = False,
) -> Path:
    """Run the build (user command or zero-config default) with env vars set.

    Returns output_dir — the wheel content root, containing all built
    artifacts.

    pure=True forces the zero-config copy path and compiles nothing, even
    when src/{package}/ contains .c files (they ship as package data).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    env, ext_suffix = _make_env(name=name, output_dir=output_dir)
    include_dir = env["JUST_BUILDIT_INCLUDE_DIR"]

    needs_extension = True

    if pure or command is None:
        needs_extension = _default_build(
            name=name,
            package=package,
            output_dir=output_dir,
            project_root=project_root,
            include_dir=include_dir,
            ext_suffix=ext_suffix,
            pure=pure,
        )
    else:
        # Explicit command: populate JUST_BUILDIT_LIBS now that we know C
        # is involved.
        env["JUST_BUILDIT_LIBS"] = shlex.join(_python_link_flags())
        print(f"just-buildit: running build command: {command}", flush=True)
        _print_env(env, ext_suffix)

        result = subprocess.run(
            shlex.split(command),
            cwd=str(project_root),
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Build command failed with exit code "
                f"{result.returncode}:\n  {command}"
            )

    _drop_windows_byproducts(output_dir, ext_suffix)

    if needs_extension and not list(output_dir.rglob(f"*{ext_suffix}")):
        raise FileNotFoundError(
            f"Build produced no extension (*{ext_suffix}) in {output_dir}\n\n"
            f"Make sure your build command writes extensions to "
            f"$JUST_BUILDIT_OUTPUT_DIR"
        )

    return output_dir


def run_repair(
    *,
    wheel_path: Path,
    wheel_dir: Path,
    repair_command: str | None | Literal[False],
    repair_args: list[str] | None = None,
) -> Path:
    """Run the wheel repair command; return the (possibly repaired) wheel path.

    repair_command:
      None  -> auto-detect by platform
      False -> skip repair
      str   -> use as-is
    """
    if repair_command is False:
        return wheel_path

    if repair_command is None:
        repair_command = _auto_repair_command()
        if repair_command is None:
            print(
                "just-buildit: no repair command detected for this "
                "platform, skipping repair.",
                flush=True,
            )
            return wheel_path

    # On Linux, auditwheel requires patchelf — check early for a clear error.
    if (
        platform.system() == "Linux"
        and "auditwheel" in repair_command
        and not shutil.which("patchelf")
    ):
        raise RuntimeError(
            "auditwheel requires patchelf, but it was not found on PATH.\n\n"
            "Install it with your system package manager:\n"
            "  apt:  sudo apt install patchelf\n"
            "  dnf:  sudo dnf install patchelf\n"
            "  brew: brew install patchelf\n\n"
            "Or disable repair in pyproject.toml:\n"
            "  [tool.just-buildit]\n"
            "  repair = false"
        )

    # Repair into a temp subdirectory so the tool never writes into the same
    # directory as the input wheel — on Windows this causes a PermissionError
    # when pip holds the source file open.
    with tempfile.TemporaryDirectory(
        dir=wheel_dir, prefix="_repair_"
    ) as repair_tmp:
        cmd = (
            shlex.split(repair_command)
            + (repair_args or [])
            + [str(wheel_path), "-w", repair_tmp]
        )
        print(f"just-buildit: repairing wheel: {shlex.join(cmd)}", flush=True)

        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(
                f"Wheel repair failed with exit code "
                f"{result.returncode}:\n  {shlex.join(cmd)}"
            )

        repaired_wheels = sorted(
            Path(repair_tmp).glob("*.whl"), key=lambda p: p.stat().st_mtime
        )
        if not repaired_wheels:
            raise FileNotFoundError(
                f"Repair command ran but no wheel found in {repair_tmp}"
            )

        repaired = repaired_wheels[-1]
        dest = wheel_dir / repaired.name
        repaired.replace(dest)

    if dest != wheel_path:
        wheel_path.unlink(missing_ok=True)
    return dest
