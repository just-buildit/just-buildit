#!/usr/bin/env python3
"""Classify a diff for CI: did the docs change, and did anything else?

A workflow's ``changes`` job runs this (as ``make ci-docs``) and gates on
the two answers it prints:

``docs``
    ``true`` when any changed path matches ``--re`` (``CI_DOCS_RE``, the
    repo's one declaration of what the docs are). A docs build job runs
    when this is true, even on a diff the matrix may otherwise skip.
``code``
    ``false`` only when EVERY changed path matches ``--re`` and no file
    outside a docs directory (``--dirs``, ``CI_DOCS_DIRS``) was deleted,
    or is a symlink or submodule on either side of the change.
    The jobs docs cannot break are gated on it, and the repo's aggregator
    grants them a skip only on an explicit ``code=false``.

Why deletions are special: a docs file can be READ by something that is not
docs -- ``pyproject.toml`` names ``README.md`` as the package readme -- and
editing it cannot break that reader, but removing it can. A deletion inside
a docs directory (a retired page) is still docs-only; its readers are the
docs build, the doc gates and the live-tree tests, all of which still run.
A symlink or a submodule is the same risk by another route: what it reaches
lives somewhere else, so retargeting one can break that reader too, and
outside a docs directory it counts like a deletion (git's own letter for a
file turned into one is ``T``, and ``_diff`` reports every such record so).

Fail-safe in every direction, like ``ci-changes``: an unreadable base, an
empty diff, or a git error answers ``docs=true`` and ``code=true``, so the
worst it can do wrong is run something that was not needed.

Examples
--------
>>> import re
>>> rx = re.compile(r"^(docs/|README\\.md$)")
>>> classify([("M", "docs/a.md"), ("A", "docs/b.md")], rx)
(True, False)
>>> classify([("M", "docs/a.md"), ("M", "native/src/x.c")], rx)
(True, True)
>>> classify([("D", "README.md")], rx)
(True, True)
>>> classify([("D", "docs/old.md")], rx)
(True, False)
>>> classify([("T", "README.md")], rx)
(True, True)
>>> classify([("T", "docs/index.md")], rx)
(True, False)
>>> classify([], rx)
(True, True)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

#: Directories whose files may be deleted in a docs-only diff, by default:
#: nothing that is not docs reads a file that lives in one.
DOCS_DIRS = ("docs/", "changelog.d/")


def classify(
    changes: list[tuple[str, str]],
    docs_re: re.Pattern[str],
    dirs: tuple[str, ...] = DOCS_DIRS,
    exclude_re: re.Pattern[str] | None = None,
) -> tuple[bool, bool]:
    """``(docs, code)`` for a list of ``(git status letter, path)`` pairs.

    A path is docs when it matches ``docs_re`` and not ``exclude_re`` (the
    include-minus-exclude shape, so no pattern needs a lookahead). An empty
    list is fail-safe: both true.
    """
    if not changes:
        return True, True

    def is_docs(p: str) -> bool:
        if exclude_re is not None and exclude_re.search(p):
            return False
        return bool(docs_re.search(p))

    docs = any(is_docs(p) for _, p in changes)
    code = any(
        not is_docs(p)
        or (status in ("D", "T") and not p.startswith(dirs))
        for status, p in changes
    )
    return docs, code


#: The modes either side of a plain file's change can have: a regular file,
#: or none (000000, an add or a delete). Anything else -- a symlink
#: (120000), a submodule (160000) -- reaches contents that live somewhere
#: else, so ``_diff`` reports it as ``T`` and ``classify`` reads it like a
#: deletion outside a docs directory.
FILE_MODES = ("000000", "100644", "100755")


def _diff(base: str) -> list[tuple[str, str]] | None:
    """``git diff --raw`` of HEAD against ``base``; None on error.

    Renames are split into a delete of the old path and an add of the new,
    so a page moved out of ``docs/`` counts as both. Submodules are never
    ignored: ``ignore = all`` in .gitmodules otherwise hides a moved
    pointer from the diff altogether (just-buildit.github.io#117). A record
    with a symlink or submodule on either side is reported as ``T``,
    whatever git's own letter.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "diff",
                "--raw",
                "-z",
                "--no-renames",
                "--ignore-submodules=none",
                base,
                "HEAD",
            ],
            check=True,
            capture_output=True,
            text=True,
            # -z leaves a path unquoted: bytes that are not UTF-8 must
            # still match (or not) rather than crash the job.
            errors="surrogateescape",
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    # -z: ``:<mode> <mode> <sha> <sha> <status>`` NUL ``<path>`` NUL, so a
    # path is read whole, whatever it holds.
    fields = out.split("\0")
    pairs = []
    for meta, path in zip(fields[0::2], fields[1::2]):
        was, now, _, _, status = meta.lstrip(":").split()
        if was not in FILE_MODES or now not in FILE_MODES:
            status = "T"
        pairs.append((status[:1], path))
    return pairs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--re", dest="docs_re", required=True)
    ap.add_argument(
        "--exclude",
        default="",
        help="paths matching this are never docs (CI_DOCS_EXCLUDE_RE)",
    )
    ap.add_argument(
        "--dirs",
        default=" ".join(DOCS_DIRS),
        help="space-separated directory prefixes a deletion may come from",
    )
    args = ap.parse_args(argv)
    changes = _diff(args.base)
    why = "a docs-only diff"
    if changes is None:
        docs, code, why = True, True, f"cannot diff against {args.base}"
    else:
        dirs = tuple(args.dirs.split())
        excl = re.compile(args.exclude) if args.exclude else None
        docs, code = classify(changes, re.compile(args.docs_re), dirs, excl)
        if not changes:
            why = "an empty diff"
        elif code:
            why = "code changed"
    lines = [f"docs={str(docs).lower()}", f"code={str(code).lower()}"]
    print("\n".join(lines))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(f"ci-docs: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
