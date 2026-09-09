"""`just-buildit --next-version` — the tag a release job should push.

A project with ``dynamic = ["version"]`` has deleted the version from every
tracked file, which is the whole point of gh-28. The consequence lands in CI:
there is no ``[project] version`` to grep and no file for a
``VERSION_PROBES``-style check to probe, so a release job that needs the
number has only two bad options -- re-implement `git describe` parsing in
shell, or reintroduce the carrier the dynamic version just removed.

`--next-version` is the third. It invents no policy: a build five commits past
``v1.1.3`` is *already* called ``1.1.4.dev5``, and ``.devN`` means "on the way
to", so that build already names 1.1.4 as the next release. The query reports
the same number without the ``.devN``.

That equality is the property worth gating, and `TestItAgreesWithTheBuild`
does: the two answers come from one `_describe` of one tag precisely so they
cannot drift into disagreeing about which tag is nearest or whether it is
usable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from just_buildit import _meta, _version

# Reused, not re-declared: a second git fixture in this repo would be a second
# definition of "a tagged checkout", free to drift from the one the build's
# own tests run against.
from tests.test_gh28_dynamic_version import DYNAMIC, _git, _repo

LITERAL = """\
[project]
name = "jbdyn"
version = "1.1.3"

[tool.just-buildit]
pure = true
"""


def _next(root: Path) -> str:
    return _version.next_version(root, _meta.version_source(root))


class TestTheAnswer(unittest.TestCase):
    def test_on_the_tag_names_the_release_after_it(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(_next(_repo(Path(tmp))), "1.1.4")

    def test_past_the_tag_gives_the_same_answer(self) -> None:
        """Landing a commit does not change which release is being worked
        toward -- only how far along it is."""
        with TemporaryDirectory() as tmp:
            self.assertEqual(_next(_repo(Path(tmp), commits=5)), "1.1.4")

    def test_a_pre_release_tag_bumps_the_pre_release(self) -> None:
        """Not the release. `1.1.3rc1` -> `1.1.3rc2`, because `1.1.4` would
        skip every remaining candidate for 1.1.3."""
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            _git(root, "tag", "-d", "v1.1.3")
            _git(root, "tag", "v1.1.3-rc1")
            self.assertEqual(_next(root), "1.1.3rc2")

    def test_the_tags_spelling_is_an_input_not_the_output(self) -> None:
        """`v1.1.3ALPHA2` is `1.1.3a2`, so the next one is canonical too --
        this string becomes a tag and then a wheel filename."""
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            _git(root, "tag", "-d", "v1.1.3")
            _git(root, "tag", "v1.1.3ALPHA2")
            self.assertEqual(_next(root), "1.1.3a3")


class TestItAgreesWithTheBuild(unittest.TestCase):
    """The invariant that makes this a report rather than a second opinion."""

    def test_the_build_version_is_the_next_version_plus_dev_distance(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), commits=5)
            self.assertEqual(
                _version.resolve(root, "vcs"), f"{_next(root)}.dev5"
            )

    def test_it_holds_for_a_pre_release_tag_too(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            _git(root, "tag", "-d", "v1.1.3")
            _git(root, "tag", "v1.1.3-rc1")
            (root / "f").write_text("x", encoding="utf-8")
            _git(root, "add", "-A")
            _git(root, "commit", "-qm", "past rc1")
            self.assertEqual(
                _version.resolve(root, "vcs"), f"{_next(root)}.dev1"
            )


class TestItRefusesRatherThanGuesses(unittest.TestCase):
    def test_a_literal_version_has_no_next_version(self) -> None:
        """Which digit a release bumps is the runbook's one human step."""
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), toml=LITERAL)
            with self.assertRaises(ValueError) as ctx:
                _next(root)
            self.assertIn("does not derive its version", str(ctx.exception))
            self.assertIn("1.1.3", str(ctx.exception))

    def test_dynamic_without_a_source_names_the_key_to_add(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(
                Path(tmp),
                toml=DYNAMIC.replace('version-from = "vcs"\n', ""),
            )
            with self.assertRaises(_version.VersionError) as ctx:
                _next(root)
            self.assertIn("version-from", str(ctx.exception))

    def test_an_untagged_repository_says_to_tag_one(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            (root / "pyproject.toml").write_text(DYNAMIC, encoding="utf-8")
            _git(root, "init", "-q", ".")
            _git(root, "add", "-A")
            _git(root, "commit", "-qm", "init")
            with self.assertRaises(_version.VersionError) as ctx:
                _next(root)
            self.assertIn("git tag", str(ctx.exception))

    def test_a_dev_carrying_tag_is_refused_here_too(self) -> None:
        """And with the SAME message the build gives, not merely a similar
        one.

        `v1.1.2.dev1` cannot be the base of a derived version -- appending a
        distance would give two `.dev` segments, which is not a valid PEP 440
        version. That guard lives in `_describe`, which both readings share,
        and this asserts the sharing rather than the refusal: two guards that
        merely agree today are free to stop agreeing, and the failure mode is
        a tag the build rejects and the release query happily bumps.
        """
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            _git(root, "tag", "-d", "v1.1.3")
            _git(root, "tag", "v1.1.2.dev1")

            with self.assertRaises(_version.VersionError) as from_build:
                _version.resolve(root, "vcs")
            with self.assertRaises(_version.VersionError) as from_query:
                _next(root)

            self.assertIn("v1.1.2.dev1", str(from_query.exception))
            self.assertEqual(
                str(from_build.exception), str(from_query.exception)
            )

    def test_pkg_info_is_deliberately_not_consulted(self) -> None:
        """The asymmetry with `resolve`, gated so it stays deliberate.

        `resolve` checks PKG-INFO FIRST, so an unpacked sdist reports its own
        identity. "What comes next" is a question about a repository's
        history, and an sdist has neither tags nor a future -- answering from
        a stale PKG-INFO would be a guess wearing an answer's clothes.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(DYNAMIC, encoding="utf-8")
            (root / "PKG-INFO").write_text(
                "Metadata-Version: 2.1\nName: jbdyn\nVersion: 9.9.9\n",
                encoding="utf-8",
            )
            # resolve() answers from PKG-INFO; next_version must not.
            self.assertEqual(_version.resolve(root, "vcs"), "9.9.9")
            with self.assertRaises(_version.VersionError) as ctx:
                _next(root)
            self.assertNotIn("9.9.9", str(ctx.exception))


class TestTheCLI(unittest.TestCase):
    """A release job does VERSION=$(just-buildit --next-version)."""

    @staticmethod
    def _cli(root: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "from just_buildit._cli import main; main()",
                "--next-version",
            ],
            cwd=root,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            capture_output=True,
            text=True,
        )

    def test_it_prints_the_bare_version_and_nothing_else(self) -> None:
        with TemporaryDirectory() as tmp:
            r = self._cli(_repo(Path(tmp), commits=5))
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), "1.1.4")
            self.assertEqual(r.stdout, "1.1.4\n")

    def test_a_failure_is_stderr_and_non_zero(self) -> None:
        """So a broken query can never be captured and pushed as a tag."""
        with TemporaryDirectory() as tmp:
            r = self._cli(_repo(Path(tmp), toml=LITERAL))
            self.assertEqual(r.returncode, 1)
            self.assertEqual(r.stdout, "")
            self.assertIn("error:", r.stderr)

    def test_help_advertises_it(self) -> None:
        with TemporaryDirectory() as tmp:
            r = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from just_buildit._cli import main; main()",
                    "help",
                ],
                cwd=tmp,
                env={**os.environ, "PYTHONPATH": str(SRC)},
                capture_output=True,
                text=True,
            )
            self.assertIn("--next-version", r.stdout)


if __name__ == "__main__":
    unittest.main()
