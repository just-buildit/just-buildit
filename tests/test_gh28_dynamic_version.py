"""gh-28: `dynamic = ["version"]`, so the version need not be a literal.

`dynamic` was not consulted anywhere in `_meta`, so `[project] version` had to
be a hand-edited literal. The cost is not cosmetic: a package index refuses a
duplicate filename, so a re-used version is a rejected upload — every PR must
bump it, and any two open PRs conflict on every file that carries a copy.

The version now comes from `[tool.just-buildit] version-from = "vcs"`: a
sibling `PKG-INFO` if there is one, else `git describe`.

Why PKG-INFO is checked first
-----------------------------
Its presence *is* the statement "this tree is an unpacked sdist". Checking git
first would let an sdist unpacked inside some unrelated checkout take that
checkout's tags, and would make a wheel built from an sdist disagree with the
sdist it came from. `test_round_trip_*` is the test that fails if the order is
swapped — it unpacks a real sdist somewhere with no `.git` at all.

The refusals are PEP 621's, not house style
-------------------------------------------
- `name` in `dynamic`: "A build back-end MUST raise an error if the metadata
  specifies `name` in `dynamic`."
- a key given statically *and* in `dynamic`: "Build back-ends MUST raise an
  error". The exception the spec grants for list- and table-valued keys a
  back-end may append to does not reach `version`.
- in `dynamic` but underivable: "Build back-ends MUST raise an error if the
  metadata specifies a key in `dynamic` but the build back-end was unable to
  determine the data." Hence no `0.0.0` placeholder — that would upload one.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from just_buildit import _meta, _sdist, _version

DYNAMIC = """\
[project]
name = "jbdyn"
dynamic = ["version"]

[tool.just-buildit]
version-from = "vcs"
pure = true
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(root),
        },
    )


def _repo(root: Path, toml: str = DYNAMIC, commits: int = 0) -> Path:
    """A real git checkout, tagged v1.1.3, *commits* commits past the tag."""
    (root / "pyproject.toml").write_text(toml, encoding="utf-8")
    pkg = root / "src" / "jbdyn"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    _git(root, "init", "-q", ".")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    _git(root, "tag", "v1.1.3")
    for i in range(commits):
        (pkg / "__init__.py").write_text("x" * (i + 1), encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", f"c{i}")
    return root


class TestDerivedFromGit(unittest.TestCase):
    def test_exactly_on_the_tag_is_the_tag(self) -> None:
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp))
            self.assertEqual(_meta.load(root).version, "1.1.3")

    def test_distance_past_the_tag_is_a_dev_release(self) -> None:
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), commits=5)
            self.assertEqual(_meta.load(root).version, "1.1.3.dev5")

    def test_a_hyphenated_tag_keeps_its_hyphens(self) -> None:
        """`git describe --long` appends `-<distance>-g<sha>`, so splitting on
        the first hyphen would turn `v1.1.3-rc1` into `1.1.3`."""
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp))
            _git(root, "tag", "-d", "v1.1.3")
            _git(root, "tag", "v1.1.3-rc1")
            self.assertEqual(_meta.load(root).version, "1.1.3-rc1")

    def test_a_non_version_tag_is_not_mistaken_for_one(self) -> None:
        """The tag glob is anchored on a digit after the `v`."""
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp))
            _git(root, "tag", "-d", "v1.1.3")
            _git(root, "tag", "vendor-freeze")
            with self.assertRaises(_version.VersionError):
                _meta.load(root)


class TestSdistIdentity(unittest.TestCase):
    """PKG-INFO first: an sdist carries its own version, wherever it sits."""

    def test_pkg_info_is_used_when_present(self) -> None:
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), commits=5)  # git would say 1.1.3.dev5
            (root / "PKG-INFO").write_text(
                "Metadata-Version: 2.1\nName: jbdyn\nVersion: 9.9.9\n",
                encoding="utf-8",
            )
            self.assertEqual(_meta.load(root).version, "9.9.9")

    def test_version_inside_the_description_is_not_the_header(self) -> None:
        """`Version:` also appears indented in a packed long description."""
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), commits=5)
            (root / "PKG-INFO").write_text(
                "Metadata-Version: 2.1\nName: jbdyn\nVersion: 9.9.9\n"
                "\n    Version: 0.0.1 is what the old docs said\n",
                encoding="utf-8",
            )
            self.assertEqual(_meta.load(root).version, "9.9.9")

    def test_round_trip_sdist_to_wheel_without_a_repository(self) -> None:
        """The whole point of the PKG-INFO leg.

        Build a real sdist from a checkout, unpack it somewhere with no `.git`,
        and load it again. Without PKG-INFO there is nothing left to derive
        from and this raises.
        """
        with TemporaryDirectory(prefix="jb28-") as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            root = _repo(repo, commits=5)
            out = Path(tmp) / "dist"
            out.mkdir()
            sdist = _sdist.build_sdist(root, out, _meta.load(root))

            unpacked = Path(tmp) / "unpacked"
            unpacked.mkdir()
            # `filter=` landed in 3.11.4/3.12; this repo still supports 3.9.
            safe = (
                {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            )
            with tarfile.open(sdist) as tf:
                tf.extractall(unpacked, **safe)
            tree = next(p for p in unpacked.iterdir() if p.is_dir())

            self.assertFalse((tree / ".git").exists())
            self.assertEqual(_meta.load(tree).version, "1.1.3.dev5")


class TestRefusals(unittest.TestCase):
    def test_static_and_dynamic_together_is_refused(self) -> None:
        toml = DYNAMIC.replace(
            'dynamic = ["version"]', 'version = "1.0.0"\ndynamic = ["version"]'
        )
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), toml=toml)
            with self.assertRaises(ValueError) as ctx:
                _meta.load(root)
            self.assertIn(
                "both statically and in 'dynamic'", str(ctx.exception)
            )

    def test_name_in_dynamic_is_refused(self) -> None:
        toml = DYNAMIC.replace(
            'dynamic = ["version"]', 'dynamic = ["version", "name"]'
        )
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), toml=toml)
            with self.assertRaises(ValueError) as ctx:
                _meta.load(root)
            self.assertIn("'name'", str(ctx.exception))

    def test_dynamic_version_without_a_source_is_refused(self) -> None:
        toml = DYNAMIC.replace('version-from = "vcs"\n', "")
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), toml=toml)
            with self.assertRaises(_version.VersionError) as ctx:
                _meta.load(root)
            self.assertIn("version-from", str(ctx.exception))

    def test_an_unknown_source_is_refused(self) -> None:
        toml = DYNAMIC.replace(
            'version-from = "vcs"', 'version-from = "guess"'
        )
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), toml=toml)
            with self.assertRaises(_version.VersionError) as ctx:
                _meta.load(root)
            self.assertIn("guess", str(ctx.exception))

    def test_underivable_is_an_error_not_a_placeholder(self) -> None:
        """No repository, no PKG-INFO. PEP 621 says MUST raise; a `0.0.0`
        fallback would publish a wrong version instead of failing the build."""
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(DYNAMIC, encoding="utf-8")
            with self.assertRaises(_version.VersionError) as ctx:
                _meta.load(root)
            message = str(ctx.exception)
            self.assertNotIn("0.0.0", message)
            self.assertIn("git tag", message)  # names a way out

    def test_dynamic_must_be_a_list(self) -> None:
        toml = DYNAMIC.replace('dynamic = ["version"]', 'dynamic = "version"')
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), toml=toml)
            with self.assertRaises(ValueError) as ctx:
                _meta.load(root)
            self.assertIn("must be a list", str(ctx.exception))


class TestBackwardCompatibility(unittest.TestCase):
    """Every existing project states a literal and no `dynamic` at all."""

    def test_a_literal_version_still_wins(self) -> None:
        toml = (
            '[project]\nname = "jbdyn"\nversion = "2.5.0"\n\n'
            "[tool.just-buildit]\npure = true\n"
        )
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = _repo(Path(tmp), toml=toml, commits=5)
            self.assertEqual(_meta.load(root).version, "2.5.0")

    def test_a_literal_version_ignores_a_sibling_pkg_info(self) -> None:
        """A literal is authoritative; nothing else is consulted."""
        toml = (
            '[project]\nname = "jbdyn"\nversion = "2.5.0"\n\n'
            "[tool.just-buildit]\npure = true\n"
        )
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(toml, encoding="utf-8")
            (root / "PKG-INFO").write_text(
                "Version: 9.9.9\n", encoding="utf-8"
            )
            self.assertEqual(_meta.load(root).version, "2.5.0")

    def test_no_version_at_all_still_reports_the_requirement(self) -> None:
        toml = '[project]\nname = "jbdyn"\n'
        with TemporaryDirectory(prefix="jb28-") as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(toml, encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                _meta.load(root)
            self.assertIn("version is required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
