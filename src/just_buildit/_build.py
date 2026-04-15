"""
_build.py — invoke the user's build command and verify the output.

Contract:
  - Set JUST_BUILDIT_* env vars
  - Call the user's command via subprocess
  - Verify the expected output file exists
  - Return the path to the built extension

Environment variables set for the build command:
  JUST_BUILDIT_NAME          extension module name (e.g. "hello")
  JUST_BUILDIT_INCLUDE_DIR   Python C header directory
  JUST_BUILDIT_OUTPUT_DIR    directory where the .so/.pyd must be placed
  JUST_BUILDIT_EXT_SUFFIX    full extension suffix (e.g. .cpython-312-x86_64-linux-gnu.so)
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


def _auto_repair_command() -> str | None:
    """Return the platform-appropriate wheel repair command, or None if not found."""
    system = platform.system()
    if system == "Linux":
        return "uvx auditwheel repair"
    elif system == "Darwin":
        return "uvx --from delocate delocate-wheel"
    elif system == "Windows":
        return "uvx delvewheel repair"
    return None


def _ldflags() -> list[str]:
    """Return platform-appropriate shared-library link flags."""
    if platform.system() == "Darwin":
        return ["-dynamiclib", "-undefined", "dynamic_lookup"]
    if platform.system() == "Windows":
        return ["-shared"]  # MinGW/UCRT64 — -fPIC is meaningless on Windows x64
    return ["-shared", "-fPIC"]


def _python_link_flags() -> list[str]:
    """
    On Windows/MinGW, return flags to explicitly link the Python import library.
    Linux/macOS resolve Python symbols at runtime (dynamic lookup / system linker);
    Windows requires them at link time.

    Two cases:
      MSYS2/MinGW Python  — ships libpython3.X[.dll].a under <root>/lib/
      Native Windows CPython — ships python3X.lib under <install root>/libs/
    """
    if platform.system() != "Windows":
        return []
    major = sys.version_info.major
    minor = sys.version_info.minor

    # Search candidate dirs: sysconfig LIBDIR, <exe_root>/lib, stdlib parent
    install_root = Path(sys.executable).parent
    candidates = dict.fromkeys(filter(None, [
        sysconfig.get_config_var("LIBDIR"),
        str(install_root / "lib"),
        str(Path(sysconfig.get_path("stdlib")).parent),
    ]))

    # MSYS2 / MinGW-style Python: libpython3.X.a or libpython3.X.dll.a
    for d in candidates:
        for stem in (f"libpython{major}.{minor}.a", f"libpython{major}.{minor}.dll.a"):
            if (Path(d) / stem).exists():
                return [f"-L{d}", f"-lpython{major}.{minor}"]

    # Native Windows CPython: python3X.lib in <root>/libs/
    libs_dir = install_root / "libs"
    if (libs_dir / f"python{major}{minor}.lib").exists():
        return [f"-L{libs_dir}", f"-lpython{major}{minor}"]

    # Last resort
    return [f"-L{install_root}", f"-lpython{major}{minor}"]


def _default_build(
    *,
    name: str,
    package: str,
    output_dir: Path,
    project_root: Path,
    include_dir: str,
    ext_suffix: str,
) -> bool:
    """
    Zero-config build: compile all *.c files from src/{package}/ and copy
    everything else (Python sources, data) to output_dir verbatim.
    Returns True if C extensions were compiled, False for pure-Python packages.
    """
    src_dir = project_root / "src" / package
    if not src_dir.is_dir():
        raise FileNotFoundError(
            f"No command set in [tool.just-buildit] and no src/{package}/ directory found.\n\n"
            f"For zero-config builds, put your sources in src/{package}/\n"
            f"Or set a build command:\n\n"
            f"  [tool.just-buildit]\n"
            f'  command = "make"\n'
        )

    c_files = sorted(src_dir.rglob("*.c"))
    if c_files:
        output = output_dir / f"{name}{ext_suffix}"
        cmd = [
            os.environ.get("CC", "cc"),
            *_ldflags(), "-O2",
            f"-I{include_dir}",
            *[str(f) for f in c_files],
            "-o", str(output),
            *_python_link_flags(),
        ]
        print(f"just-buildit: default build: {shlex.join(cmd)}", flush=True)
        result = subprocess.run(cmd, cwd=str(project_root))
        if result.returncode != 0:
            raise RuntimeError(f"Default build failed with exit code {result.returncode}")
    else:
        print(f"just-buildit: no .c files in src/{package}/ — pure Python package", flush=True)

    # Copy all non-source files (Python sources, data, etc.) preserving tree structure.
    # .c and .h stay in the source tree — they have no place in a wheel.
    # Pure Python packages go into a {package}/ subdir so `import {package}` works.
    # C extension packages put files at the root alongside the compiled .so.
    _skip = {".c", ".h"}
    pkg_out = output_dir / package if not c_files else output_dir
    for src_file in src_dir.rglob("*"):
        if src_file.is_file() and src_file.suffix not in _skip:
            dst = pkg_out / src_file.relative_to(src_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src_file.read_bytes())

    return bool(c_files)


def run_build(
    *,
    name: str,
    package: str,
    command: str | None,
    output_dir: Path,
    project_root: Path,
) -> Path:
    """
    Run the build (user command or zero-config default) with JUST_BUILDIT_* env vars set.
    Returns output_dir — the wheel content root, containing all built artifacts.
    """
    include_dir = sysconfig.get_path("include")
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")

    if not include_dir:
        raise RuntimeError("Could not determine Python include directory via sysconfig.")
    if not ext_suffix:
        raise RuntimeError("Could not determine extension suffix via sysconfig.")

    output_dir.mkdir(parents=True, exist_ok=True)

    needs_extension = True

    if command is None:
        needs_extension = _default_build(
            name=name,
            package=package,
            output_dir=output_dir,
            project_root=project_root,
            include_dir=include_dir,
            ext_suffix=ext_suffix,
        )
    else:
        env = os.environ.copy()
        env.update({
            "JUST_BUILDIT_NAME": name,
            "JUST_BUILDIT_PYTHON": sys.executable,
            "JUST_BUILDIT_INCLUDE_DIR": include_dir,
            "JUST_BUILDIT_OUTPUT_DIR": str(output_dir),
            "JUST_BUILDIT_EXT_SUFFIX": ext_suffix,
            "JUST_BUILDIT_LDFLAGS": " ".join(_ldflags()),
            "JUST_BUILDIT_LIBS":    " ".join(_python_link_flags()),
        })

        print(f"just-buildit: running build command: {command}", flush=True)
        print(f"  JUST_BUILDIT_NAME        = {name}", flush=True)
        print(f"  JUST_BUILDIT_PYTHON      = {sys.executable}", flush=True)
        print(f"  JUST_BUILDIT_INCLUDE_DIR = {include_dir}", flush=True)
        print(f"  JUST_BUILDIT_OUTPUT_DIR  = {output_dir}", flush=True)
        print(f"  JUST_BUILDIT_EXT_SUFFIX  = {ext_suffix}", flush=True)
        print(f"  JUST_BUILDIT_LDFLAGS     = {env['JUST_BUILDIT_LDFLAGS']}", flush=True)
        if env["JUST_BUILDIT_LIBS"]:
            print(f"  JUST_BUILDIT_LIBS        = {env['JUST_BUILDIT_LIBS']}", flush=True)

        result = subprocess.run(
            shlex.split(command),
            cwd=str(project_root),
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Build command failed with exit code {result.returncode}:\n  {command}"
            )

    if needs_extension and not list(output_dir.rglob(f"*{ext_suffix}")):
        raise FileNotFoundError(
            f"Build produced no extension (*{ext_suffix}) in {output_dir}\n\n"
            f"Make sure your build command writes extensions to $JUST_BUILDIT_OUTPUT_DIR"
        )

    return output_dir


def run_repair(
    *,
    wheel_path: Path,
    wheel_dir: Path,
    repair_command: str | None | bool,
) -> Path:
    """
    Run the wheel repair command. Returns path to the (possibly repaired) wheel.

    repair_command:
      None  → auto-detect by platform
      False → skip repair
      str   → use as-is
    """
    if repair_command is False:
        return wheel_path

    if repair_command is None:
        repair_command = _auto_repair_command()
        if repair_command is None:
            print(
                "just-buildit: no repair command detected for this platform, skipping repair.",
                flush=True,
            )
            return wheel_path

    # On Linux, auditwheel requires patchelf — check early for a clear error.
    if platform.system() == "Linux" and "auditwheel" in repair_command:
        if not shutil.which("patchelf"):
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
    with tempfile.TemporaryDirectory(dir=wheel_dir, prefix="_repair_") as repair_tmp:
        cmd = shlex.split(repair_command) + [str(wheel_path), "-w", repair_tmp]
        print(f"just-buildit: repairing wheel: {shlex.join(cmd)}", flush=True)

        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(
                f"Wheel repair failed with exit code {result.returncode}:\n  {shlex.join(cmd)}"
            )

        repaired_wheels = sorted(Path(repair_tmp).glob("*.whl"), key=lambda p: p.stat().st_mtime)
        if not repaired_wheels:
            raise FileNotFoundError(f"Repair command ran but no wheel found in {repair_tmp}")

        repaired = repaired_wheels[-1]
        dest = wheel_dir / repaired.name
        repaired.replace(dest)

    if dest != wheel_path:
        wheel_path.unlink(missing_ok=True)
    return dest
