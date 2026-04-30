"""
Smoke tests for the published PyPI package.

Installs just-buildit from PyPI via uvx and exercises the CLI end-to-end.
Requires: uvx (uv), a C compiler, make.

Run with: python -m unittest tests.test_pypi -v
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import unittest

FIXTURE = Path(__file__).parent / "fixture"


def _uvx(*args, cwd=FIXTURE) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uvx", "just-buildit", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


class TestPyPIHelp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("uvx"):
            raise unittest.SkipTest("uvx not found")

    def test_help_exits_0(self):
        r = _uvx("help")
        self.assertEqual(r.returncode, 0)

    def test_help_lists_commands(self):
        r = _uvx("help")
        self.assertIn("inspect", r.stdout)
        self.assertIn("build", r.stdout)
        self.assertIn("sdist", r.stdout)

    def test_unknown_command_exits_1(self):
        r = _uvx("frobnicate")
        self.assertEqual(r.returncode, 1)


class TestPyPIInspect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("uvx"):
            raise unittest.SkipTest("uvx not found")
        cls._result = _uvx("inspect")

    def test_exits_0(self):
        self.assertEqual(self._result.returncode, 0)

    def test_shows_project_name(self):
        self.assertIn("hello", self._result.stdout)

    def test_shows_version(self):
        self.assertIn("0.1.0", self._result.stdout)

    def test_shows_env_vars(self):
        self.assertIn("JUST_BUILDIT_NAME", self._result.stdout)
        self.assertIn("JUST_BUILDIT_OUTPUT_DIR", self._result.stdout)


class TestPyPIBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("uvx"):
            raise unittest.SkipTest("uvx not found")
        if not shutil.which("make"):
            raise unittest.SkipTest("make not found")
        if not shutil.which("cc") and not shutil.which("gcc") and not shutil.which("clang"):
            raise unittest.SkipTest("no C compiler found")
        cls._tmp = tempfile.mkdtemp(prefix="jb-pypi-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._result = _uvx("build", str(cls._wheel_dir))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_exits_0(self):
        self.assertEqual(self._result.returncode, 0)

    def test_prints_wheel_path(self):
        self.assertIn(".whl", self._result.stdout)

    def test_wheel_file_exists(self):
        wheels = list(self._wheel_dir.glob("*.whl"))
        self.assertEqual(len(wheels), 1)

    def test_wheel_is_valid_zip(self):
        wheel = next(self._wheel_dir.glob("*.whl"))
        self.assertTrue(zipfile.is_zipfile(wheel))


class TestPyPISdist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("uvx"):
            raise unittest.SkipTest("uvx not found")
        cls._tmp = tempfile.mkdtemp(prefix="jb-pypi-sdist-")
        cls._sdist_dir = Path(cls._tmp) / "dist"
        cls._sdist_dir.mkdir()
        cls._result = _uvx("sdist", str(cls._sdist_dir))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_exits_0(self):
        self.assertEqual(self._result.returncode, 0)

    def test_prints_sdist_path(self):
        self.assertIn(".tar.gz", self._result.stdout)

    def test_sdist_file_exists(self):
        sdists = list(self._sdist_dir.glob("*.tar.gz"))
        self.assertEqual(len(sdists), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
