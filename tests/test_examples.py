"""
Integration tests for examples/ — each example is built and smoke-tested.

Tests skip gracefully when required tools (cmake, meson) are not installed.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import ClassVar

EXAMPLES = Path(__file__).parent.parent / "examples"
SRC = Path(__file__).parent.parent / "src"

# Put just_buildit on the path so it can be imported without installation.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import just_buildit


def _build_example(example_dir: Path, wheel_dir: Path) -> str:
    orig = os.getcwd()
    os.chdir(example_dir)
    try:
        return just_buildit.build_wheel(str(wheel_dir))
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
        if (
            not shutil.which("cc")
            and not shutil.which("gcc")
            and not shutil.which("clang")
        ):
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
            raise unittest.SkipTest(
                f"required tools not found: {', '.join(missing)}"
            )
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
            raise unittest.SkipTest(
                f"required tools not found: {', '.join(missing)}"
            )
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
        if (
            not shutil.which("cc")
            and not shutil.which("gcc")
            and not shutil.which("clang")
        ):
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


class TestBazelExample(unittest.TestCase):
    """examples/bazel/ — Bazel genrule build."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("bazel"):
            raise unittest.SkipTest("bazel not found")
        cls._tmp = tempfile.mkdtemp(prefix="jb-bazel-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._wheel_name = _build_example(EXAMPLES / "bazel", cls._wheel_dir)

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

    def test_greet(self):
        mod = _unpack_and_import(self._wheel_dir, self._wheel_name, "greeter")
        self.assertEqual(mod.greet("world"), "Hello, world!")
        self.assertEqual(mod.greet("Python"), "Hello, Python!")


class TestNestedExample(unittest.TestCase):
    """examples/nested/ — recursive package tree, extensions in subdirs."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("make"):
            raise unittest.SkipTest("make not found")
        if (
            not shutil.which("cc")
            and not shutil.which("gcc")
            and not shutil.which("clang")
        ):
            raise unittest.SkipTest("no C compiler found")
        cls._tmp = tempfile.mkdtemp(prefix="jb-nested-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._wheel_name = _build_example(EXAMPLES / "nested", cls._wheel_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_produces_whl_file(self):
        self.assertTrue((self._wheel_dir / self._wheel_name).exists())

    def test_wheel_is_valid_zip(self):
        self.assertTrue(zipfile.is_zipfile(self._wheel_dir / self._wheel_name))

    def test_wheel_contains_nested_extensions(self):
        with zipfile.ZipFile(self._wheel_dir / self._wheel_name) as zf:
            names = zf.namelist()
        exts = [n for n in names if n.endswith((".so", ".pyd"))]
        self.assertEqual(len(exts), 2)
        self.assertTrue(any("filters" in n for n in exts))
        self.assertTrue(any("codec" in n for n in exts))

    def test_wheel_contains_python_sources(self):
        with zipfile.ZipFile(self._wheel_dir / self._wheel_name) as zf:
            names = zf.namelist()
        self.assertTrue(any(n == "imagelib/__init__.py" for n in names))
        self.assertTrue(
            any(n == "imagelib/filters/__init__.py" for n in names)
        )
        self.assertTrue(any(n == "imagelib/codec/__init__.py" for n in names))

    def test_blur_and_encode(self):
        mod = _unpack_and_import(self._wheel_dir, self._wheel_name, "imagelib")
        self.assertEqual(mod.blur(100), 50)
        self.assertEqual(mod.blur(7), 3)
        self.assertEqual(mod.encode(10), 30)
        self.assertEqual(mod.encode(0), 0)


class TestJustMakeitExample(unittest.TestCase):
    """just-makeit scaffolding: scaffold, verify layout, build, import."""

    # Files that must exist after `just-makeit new my_dsp --object gain ...`,
    # in the layout of the jm that ci.yml pins. jm 0.90.0 (gh-1583) moved
    # every header under native/inc/<pkg>/ and named the .pc template after
    # the package (my_dsp, not my-dsp); bump this list with the pin.
    _EXPECTED_FILES: ClassVar[list[str]] = [
        "just-makeit.toml",
        "CMakeLists.txt",
        "Makefile",
        "pyproject.toml",
        "README.md",
        "cmake/my_dsp.pc.in",
        "native/inc/my_dsp/clib_common.h",
        "native/inc/my_dsp/pyex_common.h",
        "native/inc/my_dsp/my_dsp.h",
        "native/inc/my_dsp/gain/gain_core.h",
        "native/src/my_dsp_lib.c",
        "native/src/gain/gain_core.c",
        "native/src/gain/gain_ext.c",
        "native/src/gain/CMakeLists.txt",
        "native/tests/test_gain_core.c",
        "native/benchmarks/bench_gain_core.c",
        "src/my_dsp/__init__.py",
        "src/my_dsp/gain.pyi",
    ]

    @classmethod
    def setUpClass(cls):
        if not shutil.which("just-makeit"):
            raise unittest.SkipTest("just-makeit not installed")
        missing = [t for t in ("cmake", "make") if not shutil.which(t)]
        if missing:
            raise unittest.SkipTest(
                f"required tools not found: {', '.join(missing)}"
            )
        if (
            not shutil.which("cc")
            and not shutil.which("gcc")
            and not shutil.which("clang")
        ):
            raise unittest.SkipTest("no C compiler found")

        cls._tmp = tempfile.mkdtemp(prefix="jb-makeit-")
        cls._proj = Path(cls._tmp) / "my_dsp"
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()

        subprocess.run(
            [
                "just-makeit",
                "new",
                "my_dsp",
                "--object",
                "gain",
                "--state",
                "gain:double:1.0",
            ],
            cwd=cls._tmp,
            check=True,
        )
        cls._wheel_name = _build_example(cls._proj, cls._wheel_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_layout_key_files(self):
        missing = [
            f for f in self._EXPECTED_FILES if not (self._proj / f).exists()
        ]
        self.assertEqual(missing, [], f"Missing generated files: {missing}")

    def test_produces_whl_file(self):
        self.assertTrue((self._wheel_dir / self._wheel_name).exists())

    def test_wheel_is_valid_zip(self):
        self.assertTrue(zipfile.is_zipfile(self._wheel_dir / self._wheel_name))

    def test_wheel_contains_extension(self):
        with zipfile.ZipFile(self._wheel_dir / self._wheel_name) as zf:
            names = zf.namelist()
        self.assertTrue(any(n.endswith((".so", ".pyd")) for n in names))

    def test_import_gain(self):
        mod = _unpack_and_import(self._wheel_dir, self._wheel_name, "my_dsp")
        self.assertTrue(hasattr(mod, "Gain"), "my_dsp.Gain not found")
        obj = mod.Gain(gain=1.0)
        self.assertTrue(hasattr(obj, "step"))
        self.assertTrue(hasattr(obj, "steps"))
        self.assertTrue(hasattr(obj, "reset"))


class TestClangClExample(unittest.TestCase):
    """examples/clang-cl/ — explicit Makefile build, clang-cl on Windows."""

    @classmethod
    def setUpClass(cls):
        if platform.system() != "Windows":
            raise unittest.SkipTest("clang-cl example only runs on Windows")
        missing = [t for t in ("make", "clang-cl") if not shutil.which(t)]
        if missing:
            raise unittest.SkipTest(
                f"required tools not found: {', '.join(missing)}"
            )
        cls._tmp = tempfile.mkdtemp(prefix="jb-clang-cl-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._wheel_name = _build_example(EXAMPLES / "clang-cl", cls._wheel_dir)

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
        self.assertTrue(any(n.endswith(".pyd") for n in names))

    def test_wheel_has_no_link_byproducts(self):
        """/LD writes add*.lib and add*.exp beside the .pyd; they are for
        linking against the extension, which nothing does, and must not
        ship."""
        with zipfile.ZipFile(self._wheel_dir / self._wheel_name) as zf:
            names = zf.namelist()
        junk = [n for n in names if n.endswith((".lib", ".exp", ".obj"))]
        self.assertEqual(junk, [])

    def test_extension_add(self):
        mod = _unpack_and_import(self._wheel_dir, self._wheel_name, "add")
        self.assertEqual(mod.add(2, 3), 5)
        self.assertEqual(mod.add(-1, 1), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
