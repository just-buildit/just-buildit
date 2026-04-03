"""
Integration tests for examples/ — each example is built and smoke-tested.

Tests skip gracefully when required tools (cmake, meson) are not installed.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

EXAMPLES = Path(__file__).parent.parent / "examples"
SRC = Path(__file__).parent.parent / "src"

# Put just_build on the path so it can be imported without installation.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import just_build  # noqa: E402


def _build_example(example_dir: Path, wheel_dir: Path) -> str:
    orig = os.getcwd()
    os.chdir(example_dir)
    try:
        return just_build.build_wheel(str(wheel_dir))
    finally:
        os.chdir(orig)


def _unpack_and_import(wheel_dir: Path, wheel_name: str, module_name: str):
    """Unpack wheel into a temp site dir and return the imported module."""
    install_dir = wheel_dir / "site"
    install_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
        zf.extractall(install_dir)
    sys.path.insert(0, str(install_dir))
    try:
        if module_name in sys.modules:
            del sys.modules[module_name]
        import importlib
        mod = importlib.import_module(module_name)
        return mod
    finally:
        sys.path.remove(str(install_dir))


class TestMakeExample(unittest.TestCase):
    """Zero-config: examples/make/ — no Makefile, no command."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc") and not shutil.which("gcc") and not shutil.which("clang"):
            raise unittest.SkipTest("no C compiler found")
        cls._tmp = tempfile.mkdtemp(prefix="jb-make-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._wheel_name = _build_example(EXAMPLES / "make", cls._wheel_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_produces_whl_file(self):
        self.assertTrue((self._wheel_dir / self._wheel_name).exists())

    def test_wheel_is_valid_zip(self):
        self.assertTrue(zipfile.is_zipfile(self._wheel_dir / self._wheel_name))

    def test_wheel_contains_extension(self):
        with zipfile.ZipFile(self._wheel_dir / self._wheel_name) as zf:
            names = zf.namelist()
        self.assertTrue(any(n.endswith((".so", ".pyd")) for n in names))

    def test_extension_add(self):
        mod = _unpack_and_import(self._wheel_dir, self._wheel_name, "add")
        self.assertEqual(mod.add(2, 3), 5)
        self.assertEqual(mod.add(-1, 1), 0)


class TestCMakeExample(unittest.TestCase):
    """examples/cmake/ — CMake + Makefile build."""

    @classmethod
    def setUpClass(cls):
        missing = [t for t in ("cmake", "make") if not shutil.which(t)]
        if missing:
            raise unittest.SkipTest(f"required tools not found: {', '.join(missing)}")
        cls._tmp = tempfile.mkdtemp(prefix="jb-cmake-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._wheel_name = _build_example(EXAMPLES / "cmake", cls._wheel_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_produces_whl_file(self):
        self.assertTrue((self._wheel_dir / self._wheel_name).exists())

    def test_wheel_is_valid_zip(self):
        self.assertTrue(zipfile.is_zipfile(self._wheel_dir / self._wheel_name))

    def test_wheel_contains_extension(self):
        with zipfile.ZipFile(self._wheel_dir / self._wheel_name) as zf:
            names = zf.namelist()
        self.assertTrue(any(n.endswith((".so", ".pyd")) for n in names))

    def test_extension_add(self):
        mod = _unpack_and_import(self._wheel_dir, self._wheel_name, "add")
        self.assertEqual(mod.add(2, 3), 5)
        self.assertEqual(mod.add(-1, 1), 0)


class TestMesonExample(unittest.TestCase):
    """examples/meson/ — Meson build."""

    @classmethod
    def setUpClass(cls):
        missing = [t for t in ("meson", "make") if not shutil.which(t)]
        if missing:
            raise unittest.SkipTest(f"required tools not found: {', '.join(missing)}")
        cls._tmp = tempfile.mkdtemp(prefix="jb-meson-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._wheel_name = _build_example(EXAMPLES / "meson", cls._wheel_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_produces_whl_file(self):
        self.assertTrue((self._wheel_dir / self._wheel_name).exists())

    def test_wheel_is_valid_zip(self):
        self.assertTrue(zipfile.is_zipfile(self._wheel_dir / self._wheel_name))

    def test_wheel_contains_extension(self):
        with zipfile.ZipFile(self._wheel_dir / self._wheel_name) as zf:
            names = zf.namelist()
        self.assertTrue(any(n.endswith((".so", ".pyd")) for n in names))

    def test_extension_add(self):
        mod = _unpack_and_import(self._wheel_dir, self._wheel_name, "add")
        self.assertEqual(mod.add(2, 3), 5)
        self.assertEqual(mod.add(-1, 1), 0)


class TestMixedExample(unittest.TestCase):
    """examples/mixed/ — pure Python + C extension."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("make"):
            raise unittest.SkipTest("make not found")
        if not shutil.which("cc") and not shutil.which("gcc") and not shutil.which("clang"):
            raise unittest.SkipTest("no C compiler found")
        cls._tmp = tempfile.mkdtemp(prefix="jb-mixed-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._wheel_name = _build_example(EXAMPLES / "mixed", cls._wheel_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_produces_whl_file(self):
        self.assertTrue((self._wheel_dir / self._wheel_name).exists())

    def test_wheel_is_valid_zip(self):
        self.assertTrue(zipfile.is_zipfile(self._wheel_dir / self._wheel_name))

    def test_wheel_contains_extension_and_python(self):
        with zipfile.ZipFile(self._wheel_dir / self._wheel_name) as zf:
            names = zf.namelist()
        self.assertTrue(any(n.endswith((".so", ".pyd")) for n in names))
        self.assertTrue(any(n.endswith("__init__.py") for n in names))

    def test_package_add_and_multiply(self):
        mod = _unpack_and_import(self._wheel_dir, self._wheel_name, "calc")
        result = mod.add_and_multiply(3, 4)
        self.assertEqual(result, (7, 12))
        result = mod.add_and_multiply(0, 5)
        self.assertEqual(result, (5, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
