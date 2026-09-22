"""
Integration tests for just-buildit.

Tests:
  1. get_requires_for_build_wheel() → [] (no deps, ever)
  2. build_wheel() with Makefile fixture → valid wheel produced
  3. Built extension imports correctly and returns expected results
  4. build_wheel() with zero-config src/{name}/ fixture → valid wheel produced
  5. Zero-config extension imports correctly and returns expected results
  6. Build command that produces no output → actionable FileNotFoundError
  7. Missing src/{name}/ with no command → actionable FileNotFoundError
"""

import os
import platform
import sys
import sysconfig
import tempfile
import unittest
import zipfile
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixture"
FIXTURE_NOCONFIG = Path(__file__).parent / "fixture_noconfig"
FIXTURE_PURE = Path(__file__).parent / "fixture_pure"
SRC = Path(__file__).parent.parent / "src"

# tempfile.TemporaryDirectory gained ignore_cleanup_errors in 3.10; on older
# Pythons (we support 3.8+) it raises TypeError, so only pass it where
# available. It mainly guards Windows, where a freshly built .pyd stays briefly
# locked at cleanup time.
_TMPDIR_KW = (
    {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}
)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import just_buildit


class TestNoDependencies(unittest.TestCase):
    def test_get_requires_returns_empty_list(self):
        result = just_buildit.get_requires_for_build_wheel()
        self.assertEqual(result, [])
        self.assertIsInstance(result, list)


class TestBuildEditable(unittest.TestCase):
    def test_no_src_dir_raises_runtime_error(self):
        """No editable_path and no src/: build_editable() raises."""
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "foo"\nversion = "0.1.0"\n'
            )
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            orig = os.getcwd()
            os.chdir(tmp)
            try:
                with self.assertRaises(RuntimeError):
                    just_buildit.build_editable(str(wheel_dir))
            finally:
                os.chdir(orig)

    def test_src_dir_auto_detected_for_editable(self):
        """Without editable_path, defaults to src/ if present."""
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "foo"\nversion = "0.1.0"\n'
                "[tool.just-buildit]\nrepair = false\n"
            )
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            orig = os.getcwd()
            os.chdir(tmp)
            try:
                wheel_name = just_buildit.build_editable(str(wheel_dir))
            finally:
                os.chdir(orig)
            self.assertIn("py3-none-any", wheel_name)
            with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
                pth_files = [n for n in zf.namelist() if n.endswith(".pth")]
                pth_content = zf.read(pth_files[0]).decode().strip()
            self.assertEqual(len(pth_files), 1)
            self.assertEqual(pth_content, str(src_dir.resolve()))

    def test_editable_path_produces_pth_wheel(self):
        """With editable_path set, writes a .pth — no build cmd."""
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
            self.assertEqual(
                len(pth_files), 1, f"Expected one .pth file, got: {names}"
            )
            # Wheel should be pure Python (py3-none-any) — no compiled ext
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
            self.assertTrue(
                wheel_path.exists(), f"Wheel not found: {wheel_path}"
            )
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
            self.assertTrue(
                ext_files, f"No extension in wheel. Contents: {names}"
            )

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
        with tempfile.TemporaryDirectory(
            prefix="jb-test-", **_TMPDIR_KW
        ) as tmp:
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
    """Zero-config src/{name}/ path — no Makefile, no explicit command."""

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
        with tempfile.TemporaryDirectory(
            prefix="jb-test-", **_TMPDIR_KW
        ) as tmp:
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


class TestPureBuild(unittest.TestCase):
    """pure = true — copy src/{name}/ verbatim, compile nothing.

    The fixture ships a deliberately uncompilable sample.c as package data;
    a pure build must keep it in the wheel and never hand it to a compiler.
    """

    def _build_pure(self, wheel_dir: Path) -> str:
        orig = os.getcwd()
        os.chdir(FIXTURE_PURE)
        try:
            return just_buildit.build_wheel(str(wheel_dir))
        finally:
            os.chdir(orig)

    def test_produces_pure_tagged_wheel(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            wheel_name = self._build_pure(wheel_dir)
            self.assertTrue(wheel_name.endswith("-py3-none-any.whl"))
            self.assertTrue((wheel_dir / wheel_name).exists())

    def test_wheel_keeps_c_file_as_data(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            wheel_name = self._build_pure(wheel_dir)
            with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
                names = zf.namelist()
            self.assertIn("purepkg/sample.c", names)
            self.assertIn("purepkg/__init__.py", names)
            ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
            self.assertFalse(
                any(n.endswith(ext_suffix) for n in names),
                "pure build must not produce a compiled extension",
            )

    def test_wheel_marked_purelib(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            wheel_name = self._build_pure(wheel_dir)
            with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
                wheel_meta = zf.read("purepkg-0.1.0.dist-info/WHEEL").decode()
            self.assertIn("Root-Is-Purelib: true", wheel_meta)

    def test_importable_after_install(self):
        with tempfile.TemporaryDirectory(
            prefix="jb-test-", **_TMPDIR_KW
        ) as tmp:
            wheel_dir = Path(tmp) / "dist"
            wheel_dir.mkdir()
            install_dir = Path(tmp) / "site"
            install_dir.mkdir()
            wheel_name = self._build_pure(wheel_dir)
            with zipfile.ZipFile(wheel_dir / wheel_name) as zf:
                zf.extractall(install_dir)
            sys.path.insert(0, str(install_dir))
            try:
                sys.modules.pop("purepkg", None)
                import purepkg

                self.assertEqual(purepkg.add(2, 3), 5)
            finally:
                sys.path.remove(str(install_dir))
                sys.modules.pop("purepkg", None)

    def test_pure_with_command_rejected(self):
        from just_buildit import _meta

        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "foo"\nversion = "0.1.0"\n\n'
                '[tool.just-buildit]\npure = true\ncommand = "make"\n'
            )
            with self.assertRaises(ValueError):
                _meta.load(Path(tmp))


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
        """On Windows, JUST_BUILDIT_LIBS carries -L/-lpython for the linker."""
        if platform.system() != "Windows":
            self.skipTest("Windows-only")
        flags = self._build._python_link_flags()
        self.assertTrue(flags)
        self.assertTrue(any(f.startswith("-L") for f in flags))
        self.assertTrue(any(f.startswith("-lpython") for f in flags))
        # JUST_BUILDIT_LDFLAGS must NOT include -l flags (linker order)
        ldflags = self._build._ldflags()
        self.assertFalse(any(f.startswith("-l") for f in ldflags))

    def test_python_link_flags_windows_venv_finds_base_libs(self):
        """Inside a venv -- which every PEP 517 isolated build is -- the
        import library is under sys.base_prefix/libs, not next to the venv's
        python.exe. Simulated, so it runs on every OS.

        Every directory the function searches is pointed into the temp tree,
        including the stdlib's parent. Left real, it is the MSYS2 UCRT64
        interpreter's own lib/, which holds libpython3.X.dll.a -- so on that
        CI leg the MinGW branch won, correctly, and the test measured the
        runner instead of the fix."""
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "Python312"
            (base / "libs").mkdir(parents=True)
            lib = f"python{sys.version_info.major}{sys.version_info.minor}"
            (base / "libs" / f"{lib}.lib").write_bytes(b"")
            venv_exe = Path(d) / "venv" / "Scripts" / "python.exe"
            venv_exe.parent.mkdir(parents=True)
            with mock.patch.object(
                self._build.platform, "system", return_value="Windows"
            ), mock.patch.object(
                self._build.sys, "executable", str(venv_exe)
            ), mock.patch.object(
                self._build.sys, "base_prefix", str(base)
            ), mock.patch.object(
                self._build.sysconfig, "get_config_var", return_value=None
            ), mock.patch.object(
                self._build.sysconfig,
                "get_path",
                return_value=str(base / "Lib"),
            ):
                flags = self._build._python_link_flags()
        self.assertEqual(flags, [f"-L{base / 'libs'}", f"-l{lib}"])

    def test_python_link_flags_non_windows(self):
        """On Linux/macOS symbols resolve at runtime — LIBS is empty."""
        if platform.system() == "Windows":
            self.skipTest("non-Windows only")
        self.assertEqual(self._build._python_link_flags(), [])

    def test_repair_command_darwin(self):
        if platform.system() != "Darwin":
            self.skipTest("Darwin-only")
        cmd = self._build._auto_repair_command()
        self.assertIsNotNone(cmd)
        self.assertIn("delocate", cmd)


class TestRepairArgs(unittest.TestCase):
    """Verify repair-args config parsing and arg injection into run_repair."""

    _meta = sys.modules["just_buildit._meta"]
    _build = sys.modules["just_buildit._build"]

    def _write_pyproject(self, tmp: str, extra: str = "") -> None:
        (Path(tmp) / "pyproject.toml").write_text(
            '[project]\nname = "foo"\nversion = "0.1.0"\n'
            "[tool.just-buildit]\n" + extra
        )

    def test_repair_args_list_parsed(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            self._write_pyproject(
                tmp, 'repair-args = ["--plat", "manylinux_2_28_x86_64"]\n'
            )
            config = self._meta.load(Path(tmp))
        self.assertEqual(
            config.repair_args, ["--plat", "manylinux_2_28_x86_64"]
        )

    def test_repair_args_string_parsed(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            self._write_pyproject(
                tmp, 'repair-args = "--plat manylinux_2_28_x86_64"\n'
            )
            config = self._meta.load(Path(tmp))
        self.assertEqual(
            config.repair_args, ["--plat", "manylinux_2_28_x86_64"]
        )

    def test_repair_args_default_empty(self):
        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "foo"\nversion = "0.1.0"\n'
            )
            config = self._meta.load(Path(tmp))
        self.assertEqual(config.repair_args, [])

    def _fake_repair_run(
        self,
        extra_wheel_name="foo-0.1.0-cp312-cp312-manylinux_2_28_x86_64.whl",
    ):
        """Return (captured, fake_run); mocks the repair subprocess."""
        from unittest.mock import MagicMock

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            w_idx = cmd.index("-w")
            out_dir = Path(cmd[w_idx + 1])
            (out_dir / extra_wheel_name).write_bytes(b"")
            result = MagicMock()
            result.returncode = 0
            return result

        return captured, fake_run

    def test_run_repair_injects_args_before_wheel(self):
        """Extra args appear between the repair command and the wheel path."""
        from unittest.mock import patch

        captured, fake_run = self._fake_repair_run()

        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp)
            wheel_path = wheel_dir / "foo-0.1.0-cp312-cp312-linux_x86_64.whl"
            wheel_path.write_bytes(b"")

            with patch.object(
                self._build.subprocess, "run", side_effect=fake_run
            ), patch.object(
                self._build.shutil,
                "which",
                return_value="/usr/bin/patchelf",
            ):
                self._build.run_repair(
                    wheel_path=wheel_path,
                    wheel_dir=wheel_dir,
                    repair_command="uvx auditwheel repair",
                    repair_args=["--plat", "manylinux_2_28_x86_64"],
                )

        cmd = captured["cmd"]
        self.assertIn("--plat", cmd)
        plat_idx = cmd.index("--plat")
        self.assertEqual(cmd[plat_idx + 1], "manylinux_2_28_x86_64")
        wheel_idx = cmd.index(str(wheel_path))
        self.assertLess(
            plat_idx, wheel_idx, "--plat must precede the wheel path"
        )

    def test_run_repair_no_extra_args(self):
        """Without repair_args: <repair_cmd> <wheel> -w <dir>, nothing else."""
        from unittest.mock import patch

        captured, fake_run = self._fake_repair_run()

        with tempfile.TemporaryDirectory(prefix="jb-test-") as tmp:
            wheel_dir = Path(tmp)
            wheel_path = wheel_dir / "foo-0.1.0-cp312-cp312-linux_x86_64.whl"
            wheel_path.write_bytes(b"")

            with patch.object(
                self._build.subprocess, "run", side_effect=fake_run
            ), patch.object(
                self._build.shutil,
                "which",
                return_value="/usr/bin/patchelf",
            ):
                self._build.run_repair(
                    wheel_path=wheel_path,
                    wheel_dir=wheel_dir,
                    repair_command="uvx auditwheel repair",
                )

        cmd = captured["cmd"]
        # Expected: ["uvx", "auditwheel", "repair", "<wheel>", "-w", "<dir>"]
        self.assertEqual(cmd[:3], ["uvx", "auditwheel", "repair"])
        self.assertEqual(cmd[3], str(wheel_path))


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
