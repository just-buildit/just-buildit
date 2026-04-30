"""
CLI tests for just-buildit — exercises inspect, build, sdist, help, and error
handling via subprocess, without requiring the package to be installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixture"
SRC = Path(__file__).parent.parent / "src"


def _cli(*args, cwd=FIXTURE) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "from just_buildit._cli import main; main()", *args],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
    )


import unittest


class TestCLIHelp(unittest.TestCase):
    def test_no_args_prints_usage(self):
        r = _cli()
        self.assertEqual(r.returncode, 0)
        self.assertIn("Usage:", r.stdout)

    def test_help_command(self):
        r = _cli("help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("inspect", r.stdout)
        self.assertIn("build", r.stdout)
        self.assertIn("sdist", r.stdout)

    def test_unknown_command_exits_1(self):
        r = _cli("frobnicate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown command", r.stderr)


class TestCLIInspect(unittest.TestCase):
    def test_exits_0(self):
        r = _cli("inspect")
        self.assertEqual(r.returncode, 0)

    def test_shows_name_and_version(self):
        r = _cli("inspect")
        self.assertIn("hello", r.stdout)
        self.assertIn("0.1.0", r.stdout)

    def test_shows_command(self):
        r = _cli("inspect")
        self.assertIn("make", r.stdout)

    def test_shows_env_vars(self):
        r = _cli("inspect")
        self.assertIn("JUST_BUILDIT_NAME", r.stdout)
        self.assertIn("JUST_BUILDIT_OUTPUT_DIR", r.stdout)

    def test_shows_predicted_wheel_name(self):
        r = _cli("inspect")
        self.assertIn("hello-0.1.0", r.stdout)
        self.assertIn(".whl", r.stdout)


class TestCLIBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("make"):
            raise unittest.SkipTest("make not found")
        if not shutil.which("cc") and not shutil.which("gcc") and not shutil.which("clang"):
            raise unittest.SkipTest("no C compiler found")
        cls._tmp = tempfile.mkdtemp(prefix="jb-cli-build-")
        cls._wheel_dir = Path(cls._tmp) / "dist"
        cls._wheel_dir.mkdir()
        cls._result = _cli("build", str(cls._wheel_dir))

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


class TestCLISdist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="jb-cli-sdist-")
        cls._sdist_dir = Path(cls._tmp) / "dist"
        cls._sdist_dir.mkdir()
        cls._result = _cli("sdist", str(cls._sdist_dir))

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
