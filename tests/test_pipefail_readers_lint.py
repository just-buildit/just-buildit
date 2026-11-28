"""No pipeline under pipefail ends in a reader that stops early.

``producer | grep -q`` (or ``head``, ``sed 1q``, an awk ``exit``) exits
before the producer has finished writing; the producer takes SIGPIPE (rc
141), and under ``pipefail`` -- GitHub's ``shell: bash`` -- the step fails
though the reader got its answer, by timing alone. Under ``!`` the answer
flips. The rules are canonical's vendored ``scripts/pipefail-readers.py``;
``make lint-pipefail-readers`` runs it over every tracked shell script that
sets pipefail and every workflow, and ``.pre-commit-config.yaml``
dispatches to it, so ``make lint`` holds the tree to it.

This repo's own shell had no such pipe when the gate arrived; these tests
hold the wiring, so the first one added is caught: the target passes on the
tree, reads the workflows it guards and leaves the vendored ones to
canonical, and the hook reaches it.
"""

import re
import shlex
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _make(*args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        ["make", "-s", "--no-print-directory", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        timeout=300,
    )


class PipefailReaders(unittest.TestCase):
    def test_the_tree_has_no_pipe_into_an_early_reader(self) -> None:
        p = _make("lint-pipefail-readers")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"pipefail-readers: \d+ file\(s\)")

    def test_the_scan_reads_the_workflows_and_skips_vendored(self) -> None:
        p = _make("-n", "lint-pipefail-readers")
        self.assertEqual(p.returncode, 0, p.stderr)
        # The `git ls-files` the recipe runs, its pathspecs read off the
        # command make would run and handed to git as a list -- no shell.
        m = re.search(r"\$\(git ls-files ([^)]*)\)", p.stdout)
        self.assertIsNotNone(m, p.stdout)
        assert m is not None
        files = subprocess.run(
            ["git", "ls-files", *shlex.split(m.group(1))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        for f in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            self.assertIn(f, files)
        # Vendored files are canonical's to hold.
        self.assertNotIn(".github/workflows/changes.yml", files)
        self.assertNotIn("scripts/release-watch.sh", files)

    def test_pre_commit_dispatches_to_it(self) -> None:
        cfg = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        self.assertRegex(
            cfg, r"(?m)^\s+entry: make -s lint-pipefail-readers\s*$"
        )


if __name__ == "__main__":
    unittest.main()
