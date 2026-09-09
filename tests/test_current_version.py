"""`just-buildit --current-version` — the version this tree builds as.

The sibling of `--next-version`, and the one CI usually wants: not "what
should I tag next" but "what did I just build". With `dynamic = ["version"]`
there is no file carrying it, so the only ways to get it were to scrape
`inspect`'s human report or to re-derive it -- and scraping a report formatted
for people is how a pipeline breaks on a cosmetic change.

The two queries answer different questions and correctly disagree about which
projects they serve:

============================  ================  ================
project                       --current-version --next-version
============================  ================  ================
literal `[project] version`   the literal       refuses
derived, on tag `v1.1.3`      ``1.1.3``         ``1.1.4``
derived, 5 commits past       ``1.1.4.dev5``    ``1.1.4``
============================  ================  ================

The current version is a FACT about the tree, so it answers for every project.
The next one is a judgement about a release, so it refuses where there is no
scheme to read it from.
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

from tests.test_gh28_dynamic_version import _repo
from tests.test_next_version import LITERAL


def _cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from just_buildit._cli import main; main()",
            *args,
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
    )


def _current(root: Path) -> str:
    r = _cli(root, "--current-version")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _inspect_version(root: Path) -> str:
    """The version as the human report states it."""
    r = _cli(root, "inspect")
    assert r.returncode == 0, r.stderr
    for line in r.stdout.splitlines():
        if line.strip().startswith("version:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no version line in inspect output:\n{r.stdout}")


class TestItIsTheSameFactAsInspect(unittest.TestCase):
    """Two renderings of one value, gated so they cannot drift.

    This query exists BECAUSE scraping the report is fragile; if the two could
    disagree, it would have replaced a fragile answer with a wrong one.
    """

    def test_it_matches_inspect_for_a_derived_version(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), commits=5)
            self.assertEqual(_current(root), _inspect_version(root))
            self.assertEqual(_current(root), "1.1.4.dev5")

    def test_it_matches_inspect_on_the_tag(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            self.assertEqual(_current(root), _inspect_version(root))
            self.assertEqual(_current(root), "1.1.3")

    def test_it_matches_inspect_for_a_literal_version(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), toml=LITERAL)
            self.assertEqual(_current(root), _inspect_version(root))
            self.assertEqual(_current(root), "1.1.3")


class TestItServesProjectsNextVersionRefuses(unittest.TestCase):
    def test_a_literal_version_project_gets_an_answer(self) -> None:
        """The asymmetry, stated as a test.

        `--next-version` refuses here, because which digit a release bumps is
        a judgement. The version it builds as today is not a judgement, so
        this answers.
        """
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), toml=LITERAL)
            self.assertEqual(_current(root), "1.1.3")
            refused = _cli(root, "--next-version")
            self.assertEqual(refused.returncode, 1)


class TestThePairAgrees(unittest.TestCase):
    def test_current_is_next_plus_the_dev_distance(self) -> None:
        """Through the CLI, not just the functions behind it."""
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), commits=5)
            nxt = _cli(root, "--next-version").stdout.strip()
            self.assertEqual(_current(root), f"{nxt}.dev5")


class TestTheCLIContract(unittest.TestCase):
    def test_it_prints_the_bare_version_and_nothing_else(self) -> None:
        with TemporaryDirectory() as tmp:
            r = _cli(_repo(Path(tmp), commits=5), "--current-version")
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "1.1.4.dev5\n")

    def test_a_failure_is_stderr_and_non_zero(self) -> None:
        """An untagged derived project cannot state a version at all."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "jbdyn"\ndynamic = ["version"]\n\n'
                '[tool.just-buildit]\nversion-from = "vcs"\npure = true\n',
                encoding="utf-8",
            )
            r = _cli(root, "--current-version")
            self.assertEqual(r.returncode, 1)
            self.assertEqual(r.stdout, "")
            self.assertIn("error:", r.stderr)

    def test_help_advertises_it(self) -> None:
        with TemporaryDirectory() as tmp:
            r = _cli(Path(tmp), "help")
            self.assertIn("--current-version", r.stdout)


if __name__ == "__main__":
    unittest.main()
