"""
Integration tests for just-build.

Tests:
  1. get_requires_for_build_wheel() → [] (no deps, ever)
  2. build_wheel() with Makefile fixture → valid wheel produced
  3. Built extension imports correctly and returns expected results
  4. build_wheel() with zero-config src/{name}/ fixture → valid wheel produced
  5. Zero-config extension imports correctly and returns expected results
  6. Build command that produces no output → actionable FileNotFoundError
  7. Missing src/{name}/ with no command → actionable FileNotFoundError
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixture"
FIXTURE_NOCONFIG = Path(__file__).parent / "fixture_noconfig"
JUST_BUILD = Path(__file__).parent.parent / "src" / "just_buildit"


def _load_just_buildit():
    """Import just_buildit from source without installation."""
    for sub in ("_meta", "_build", "_wheel"):
        sub_spec = importlib.util.spec_from_file_location(
            f"just_buildit.{sub}", JUST_BUILD / f"{sub}.py"
        )
        sub_mod = importlib.util.module_from_spec(sub_spec)
        sys.modules[f"just_buildit.{sub}"] = sub_mod
        sub_spec.loader.exec_module(sub_mod)

    spec = importlib.util.spec_from_file_location(
        "just_buildit",
        JUST_BUILD / "__init__.py",
        submodule_search_locations=[str(JUST_BUILD)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["just_buildit"] = mod
    spec.loader.exec_module(mod)
    return mod


just_buildit = _load_just_buildit()


class TestNoDependencies(unittest.TestCase):
    def test_get_requires_returns_empty_list(self):
        result = just_buildit.get_requires_for_build_wheel()
        self.assertEqual(result, [])
        self.assertIsInstance(result, list)


class TestBuildEditable(unittest.TestCase):

    def test_no_editable_path_falls_back_to_build_wheel(self):
        """Without editable_path, build_editable() produces a full compiled wheel."""
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            orig = os.getcwd()
            os.chdir(FIXTURE)
            try:
                wheel_name = just_buildit.build_editable(str(wheel_dir))
            finally:
                os.chdir(orig)
            wheel_path = wheel_dir / wheel_name
            self.assertTrue(wheel_path.exists())
            self.assertTrue(zipfile.is_zipfile(wheel_path))
            with zipfile.ZipFile(wheel_path) as zf:
                names = zf.namelist()
            self.assertTrue(any(n.endswith((".so", ".pyd")) for n in names))

    def test_editable_path_produces_pth_wheel(self):
        """With editable_path set, build_editable() writes a .pth file — no build command."""
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "foo"\nversion = "0.1.0"\n'
                '[tool.just-buildit]\neditable_path = "src"\nrepair = false\n'
            )
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            orig = os.getcwd()
            os.chdir(tmp)
            try:
                wheel_name = just_buildit.build_editable(str(wheel_dir))
            finally:
                os.chdir(orig)
            wheel_path = wheel_dir / wheel_name
            self.assertTrue(wheel_path.exists())
            self.assertTrue(zipfile.is_zipfile(wheel_path))
            with zipfile.ZipFile(wheel_path) as zf:
                names = zf.namelist()
            pth_files = [n for n in names if n.endswith(".pth")]
            self.assertEqual(len(pth_files), 1, f"Expected one .pth file, got: {names}")
            # Wheel should be pure Python (py3-none-any) — no compiled extension
            self.assertIn("py3-none-any", wheel_name)
            # .pth content must point at the resolved src/ directory
            with zipfile.ZipFile(wheel_path) as zf:
                pth_content = zf.read(pth_files[0]).decode().strip()
            self.assertEqual(pth_content, str(src_dir.resolve()))


class TestBuildWheel(unittest.TestCase):

    def _build_fixture(self, wheel_dir: Path) -> str:
        orig = os.getcwd()
        os.chdir(FIXTURE)
        try:
            return just_buildit.build_wheel(str(wheel_dir))
        finally:
            os.chdir(orig)

    def test_produces_whl_file(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            wheel_name = self._build_fixture(wheel_dir)
            wheel_path = wheel_dir / wheel_name
            self.assertTrue(wheel_path.exists(), f"Wheel not found: {wheel_path}")
            self.assertEqual(wheel_path.suffix, ".whl")

    def test_wheel_is_valid_zip(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            wheel_name = self._build_fixture(wheel_dir)
            self.assertTrue(zipfile.is_zipfile(wheel_dir / wheel_name))

    def test_wheel_contains_extension(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            wheel_name = self._build_fixture(wheel_dir)
            with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
                names = zf.namelist()
            ext_files = [n for n in names if n.endswith((".so", ".pyd"))]
            self.assertTrue(ext_files, f"No extension in wheel. Contents: {names}")

    def test_wheel_contains_dist_info(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            wheel_name = self._build_fixture(wheel_dir)
            with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
                names = zf.namelist()
            self.assertTrue(any("METADATA" in n for n in names))
            self.assertTrue(any("WHEEL" in n for n in names))
            self.assertTrue(any("RECORD" in n for n in names))

    def test_extension_is_importable_and_correct(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-", ignore_cleanup_errors=True) as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            install_dir = Path(tmp) / "site"
            install_dir.mkdir()
            wheel_name = self._build_fixture(wheel_dir)

            # Wheels are zip archives — unpack directly, no pip needed.
            with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
                zf.extractall(install_dir)

            sys.path.insert(0, str(install_dir))
            try:
                if "hello" in sys.modules:
                    del sys.modules["hello"]
                import hello
                self.assertEqual(hello.add(2, 3), 5)
                self.assertEqual(hello.add(-1, 1), 0)
                self.assertEqual(hello.add(100, 200), 300)
            finally:
                sys.path.remove(str(install_dir))
                if "hello" in sys.modules:
                    del sys.modules["hello"]


class TestDefaultBuild(unittest.TestCase):
    """Zero-config src/{name}/ path — no Makefile, no [tool.just-buildit] command."""

    def _build_noconfig(self, wheel_dir: Path) -> str:
        orig = os.getcwd()
        os.chdir(FIXTURE_NOCONFIG)
        try:
            return just_buildit.build_wheel(str(wheel_dir))
        finally:
            os.chdir(orig)

    def test_produces_whl_file(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            wheel_name = self._build_noconfig(wheel_dir)
            self.assertTrue((wheel_dir / wheel_name).exists())

    def test_extension_is_importable_and_correct(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-", ignore_cleanup_errors=True) as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            install_dir = Path(tmp) / "site"
            install_dir.mkdir()
            wheel_name = self._build_noconfig(wheel_dir)

            with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
                zf.extractall(install_dir)

            sys.path.insert(0, str(install_dir))
            try:
                if "hello" in sys.modules:
                    del sys.modules["hello"]
                import hello
                self.assertEqual(hello.add(2, 3), 5)
            finally:
                sys.path.remove(str(install_dir))
                if "hello" in sys.modules:
                    del sys.modules["hello"]


class TestBuildEnv(unittest.TestCase):
    """Verify platform-specific build environment helpers."""

    _build = sys.modules["just_buildit._build"]

    def test_ldflags_nonempty(self):
        flags = self._build._ldflags()
        self.assertTrue(flags, "_ldflags() must return at least one flag")

    def test_ldflags_platform(self):
        flags = self._build._ldflags()
        system = platform.system()
        if system == "Darwin":
            self.assertIn("-dynamiclib", flags)
            self.assertIn("-undefined", flags)
            self.assertIn("dynamic_lookup", flags)
            self.assertNotIn("-shared", flags)
            self.assertNotIn("-fPIC", flags)
        elif system == "Windows":
            self.assertIn("-shared", flags)
            self.assertNotIn("-fPIC", flags)
            self.assertNotIn("-dynamiclib", flags)
        else:
            self.assertIn("-shared", flags)
            self.assertIn("-fPIC", flags)
            self.assertNotIn("-dynamiclib", flags)

    def test_python_link_flags_windows(self):
        """On Windows, JUST_BUILDIT_LIBS carries -L and -lpython for the linker."""
        if platform.system() != "Windows":
            self.skipTest("Windows-only")
        flags = self._build._python_link_flags()
        self.assertTrue(flags)
        self.assertTrue(any(f.startswith("-L") for f in flags))
        self.assertTrue(any(f.startswith("-lpython") for f in flags))
        # JUST_BUILDIT_LDFLAGS must NOT include -l flags (linker order)
        ldflags = self._build._ldflags()
        self.assertFalse(any(f.startswith("-l") for f in ldflags))

    def test_python_link_flags_non_windows(self):
        """On Linux/macOS Python symbols resolve at runtime — JUST_BUILDIT_LIBS is empty."""
        if platform.system() == "Windows":
            self.skipTest("non-Windows only")
        self.assertEqual(self._build._python_link_flags(), [])

    def test_repair_command_darwin(self):
        if platform.system() != "Darwin":
            self.skipTest("Darwin-only")
        cmd = self._build._auto_repair_command()
        self.assertIsNotNone(cmd)
        self.assertIn("delocate", cmd)


class TestErrorHandling(unittest.TestCase):

    def test_no_command_no_src_raises_file_not_found(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "foo"\nversion = "0.1.0"\n'
            )
            orig = os.getcwd()
            os.chdir(tmp)
            try:
                with self.assertRaises(FileNotFoundError) as ctx:
                    just_buildit.build_wheel(tmp)
                self.assertIn("src/foo/", str(ctx.exception))
            finally:
                os.chdir(orig)

    def test_build_command_with_no_output_raises_file_not_found(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "foo"\nversion = "0.1.0"\n'
                '[tool.just-buildit]\ncommand = "true"\nrepair = false\n'
            )
            orig = os.getcwd()
            os.chdir(tmp)
            try:
                with self.assertRaises(FileNotFoundError) as ctx:
                    just_buildit.build_wheel(tmp)
                self.assertIn("$JUST_BUILDIT_OUTPUT_DIR", str(ctx.exception))
            finally:
                os.chdir(orig)


if __name__ == "__main__":
    unittest.main(verbosity=2)
