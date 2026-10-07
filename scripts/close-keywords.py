#!/usr/bin/env python3
"""Refuse a closing keyword before an issue the pull request does not close.

VENDORED VERBATIM from https://just-buildit.github.io/scripts/close-keywords.py
and checked by ``standard-check`` like ``standard.mk`` itself. Never edit it
in place; change canonical and re-vendor. ``make close-keywords-check`` runs
it, and ``make lint`` runs that.

Why
---
GitHub closes an issue when a closing keyword followed by a reference to it
reaches the default branch -- in the PR description, or in any commit
message, which a squash with ``COMMIT_MESSAGES`` copies into the merge
commit. The parser is lexical. It does not read the words around the
phrase, so a negation is invisible to it, and it reads across a line break,
even a blank one. Measured, each of these CLOSED the issue it names:

* "filed, not fixed" + gh-1960 (just-makeit#1960, open again 18 hours
  later), and "Filed rather than fixed" + gh-1516 (just-makeit);
* "this does NOT close" + #942, and "Closes" + #723 + "is NOT claimed"
  (doppler);
* "Closes" + #1310 + "'s blocker" (just-makeit, reopened the same day);
* a subject ending "#1658 closes", a blank line, and a body starting
  #1838 (doppler); "the fix", a line break, then #1004 (doppler).

Agents write most of this text, often listing carve-outs as "not fixed" or
"left open, fixes later", and a rule in each repo's notes did not hold. So
this is a gate, run on every pull request.

The rule
--------
A *closing reference* is one of GitHub's keywords -- ``close``,
``closes``, ``closed``, ``fix``, ``fixes``, ``fixed``, ``resolve``,
``resolves``, ``resolved``, in any case, a colon allowed after it --
followed, across any whitespace, by an issue reference: ``#N``, ``GH-N``
(any case), ``owner/repo#N`` or an issue URL. Each one in the PR's commit
messages, title or body must name an issue the PR *declares* it closes:

* a group in parentheses that ends the PR title: ``fix: x (gh-12)``;
* or a *declaration line*, in the PR body or a commit message: a line
  that begins with a closing reference (a list bullet allowed), perhaps a
  run of them (``Closes #1, closes #2``), followed by the end of the line
  or by punctuation -- ``Closes #12.``, ``Closes #12, which ...``.
  ``Closes #723 is NOT claimed`` is no declaration: a word follows it.

Anything else is refused, naming the commit (or the title or body), the
line and the phrase. Write "filed gh-N" or "left open: gh-N" instead, or
declare the issue if the PR does close it.

Where its input comes from
--------------------------
In a ``pull_request`` run the PR's title, body, head and base are read from
the event GitHub Actions hands every step (``GITHUB_EVENT_PATH``), so an
adopter's CI passes nothing: the job that runs ``make lint`` already has
them. The commits are ``head`` minus ``base`` and minus the first parent of
the checked-out test merge, which is the base GitHub merged against when
``base.sha`` in the event is older. A shallow checkout is deepened first --
a range read from a shallow clone silently stops at its boundary, which
would pass a commit it never saw.

Any other CI event is told it is not the gate: on a push the issue is
already closed. Run outside CI, the PR's title and body do not exist yet,
so the commits ahead of ``--base`` are read and anything undeclared IN
THEM is printed as a note, never as a failure: a gate that is red locally
and green in CI on the same commits would be two answers.

Examples
--------
>>> title = "fix: x (gh-7)"
>>> undeclared([("commit a", "Filed, not fixed: gh-9.")], title, "o/r")
[('commit a, line 1', 'fixed: gh-9')]
>>> undeclared([("commit a", "This fixes gh-7 at last.")], title, "o/r")
[]
>>> undeclared([("PR body", "Closes #723 is NOT claimed.")], "", "o/r")
[('PR body, line 1', 'Closes #723')]
>>> wrapped = [("PR body", "Closes #12."), ("commit b", "the fix\\n#12")]
>>> undeclared(wrapped, "", "o/r")
[]
>>> body = ("PR body", "Closes O/R#5.")
>>> undeclared([body, ("commit c", "so fixes #5, fixes o/x#5")], "", "o/r")
[('commit c, line 1', 'fixes o/x#5')]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

#: GitHub's closing keywords, every tense. Matched without case.
KEYWORD = r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b"

#: An issue reference in each spelling GitHub links: an issue URL,
#: ``owner/repo#N``, ``#N`` and ``GH-N``. Matched without case. Never part
#: of a longer word, and ``&#N`` is an HTML entity, not a reference.
REFERENCE = (
    r"(?:https?://github\.com/[\w.-]+/[\w.-]+/issues/\d+"
    r"|\b[\w.-]+/[\w.-]+#\d+"
    r"|(?<![\w&])#\d+"
    r"|\bgh-\d+)"
    r"(?!\w)"
)

#: A closing reference as GitHub reads one: the keyword, an optional
#: colon, and ANY whitespace -- a line break included -- before the issue.
CLOSING = re.compile(
    rf"(?P<kw>{KEYWORD})\s*:?\s*(?P<ref>{REFERENCE})", re.IGNORECASE
)

_ITEM = rf"{KEYWORD}[ \t]*:?[ \t]*{REFERENCE}"
_MORE = (
    rf"[ \t]*(?:[,;&.]|\band\b)?[ \t]*(?:{KEYWORD}[ \t]*:?[ \t]*)?{REFERENCE}"
)

#: A declaration line: a closing reference (or a run of them) at the start
#: of a line, then the line's end or punctuation, never another word.
DECLARATION = re.compile(
    rf"^[ \t]*(?:[-*+][ \t]+)?(?P<run>{_ITEM}(?:{_MORE})*)"
    r"(?=[ \t]*(?:$|[.,;:!?)\]]|--|\u2013|\u2014))",
    re.IGNORECASE | re.MULTILINE,
)

#: The parenthesised groups that end a title: ``(gh-12)``, ``(gh-1, gh-2)``.
_TRAILING_GROUPS = re.compile(r"(?:\s*\([^()]*\))+\s*$")

_QUALIFIED = re.compile(r"([\w.-]+/[\w.-]+)(?:/issues/|#)(\d+)$")

Issue = tuple[str, int]


def issue(ref: str, repo: str) -> Issue:
    """``(owner/repo, number)`` for a reference, lower-cased.

    A bare ``#N`` or ``GH-N`` is ``repo``'s, so ``#5`` and ``O/R#5`` are
    one issue in repository ``o/r``.

    >>> issue("GH-12", "O/R"), issue("o/r#12", "x/y")
    (('o/r', 12), ('o/r', 12))
    >>> issue("https://github.com/A/b.c/issues/3", "o/r")
    ('a/b.c', 3)
    """
    m = _QUALIFIED.search(ref.lower())
    if m:
        return m.group(1), int(m.group(2))
    return repo.lower(), int(re.sub(r"\D", "", ref))


def title_declares(title: str, repo: str) -> set[Issue]:
    """The issues named in the parenthesised groups ending ``title``.

    >>> sorted(title_declares("fix: x (gh-3, gh-4) (#9)", "o/r"))
    [('o/r', 3), ('o/r', 4), ('o/r', 9)]
    >>> title_declares("fix(gh-3): not at the end", "o/r")
    set()
    """
    m = _TRAILING_GROUPS.search(title)
    if not m:
        return set()
    found = re.finditer(REFERENCE, m.group(), re.IGNORECASE)
    return {issue(r.group(), repo) for r in found}


def declarations(text: str, repo: str) -> set[Issue]:
    """The issues ``text`` declares on declaration lines.

    Only a reference a keyword closes is declared: ``Closes #1 and #2``
    closes #1 alone, as it does on GitHub.

    >>> sorted(declarations("- Closes #1 and #2, fixes gh-3.", "o/r"))
    [('o/r', 1), ('o/r', 3)]
    >>> declarations("Closes #4 partially", "o/r")
    set()
    """
    found: set[Issue] = set()
    for d in DECLARATION.finditer(text):
        for c in CLOSING.finditer(d.group("run")):
            found.add(issue(c.group("ref"), repo))
    return found


def undeclared(
    sources: list[tuple[str, str]], title: str, repo: str
) -> list[tuple[str, str]]:
    """Every closing reference in ``sources`` naming an undeclared issue.

    ``sources`` are ``(where, text)`` pairs -- the commit messages, the PR
    title and its body. Each finding is ``(where + line, phrase)``, the
    phrase with its whitespace collapsed.
    """
    texts = [(where, _lines(text)) for where, text in sources]
    declared = title_declares(title, repo)
    for _, text in texts:
        declared |= declarations(text, repo)
    findings = []
    for where, text in texts:
        for c in CLOSING.finditer(text):
            if issue(c.group("ref"), repo) in declared:
                continue
            line = text.count("\n", 0, c.start()) + 1
            phrase = " ".join(c.group().split())
            findings.append((f"{where}, line {line}", phrase))
    return findings


def _lines(text: str) -> str:
    # A body typed into GitHub's editor has CRLF endings, and `$` in a
    # MULTILINE pattern matches only before a bare LF.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )


def _has_commit(rev: str) -> bool:
    return _git("cat-file", "-e", f"{rev}^{{commit}}").returncode == 0


def _shallow() -> bool:
    out = _git("rev-parse", "--is-shallow-repository").stdout
    return out.strip() == "true"


def _commits(head: str, exclude: list[str]) -> list[tuple[str, str]] | None:
    """``(sha, message)`` for each commit in ``head`` but not ``exclude``."""
    r = _git("log", "-z", "--format=%H%n%B", head, *(f"^{x}" for x in exclude))
    if r.returncode != 0:
        return None
    found = []
    for record in r.stdout.split("\0"):
        sha, _, message = record.strip("\n").partition("\n")
        if sha:
            found.append((sha, message))
    return found


def _sources(commits: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(f"commit {sha[:8]}", message) for sha, message in commits]


def _get(obj: object, *path: str) -> object:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _deepen(head: str, base: str) -> str | None:
    """Make ``base..head`` readable in full; why not, or None."""
    shallow = _shallow()
    if shallow or not (_has_commit(head) and _has_commit(base)):
        args = ["fetch", "--quiet", "--no-tags"]
        if shallow:
            args.append("--unshallow")
        r = _git(*args, "origin", head, base)
        if r.returncode != 0:
            return f"cannot fetch them from origin: {r.stderr.strip()}"
    if not (_has_commit(head) and _has_commit(base)):
        return "they are not in this clone, and fetching did not bring them"
    if _shallow():
        return "this clone is still shallow, so the range would be cut short"
    return None


_HOW = """\
GitHub closes an issue for any closing keyword (close, fix or resolve, any
tense or case, a colon allowed) followed by a reference to it, in a commit
message or the PR text -- whatever the words around it say, and across a
line break. "Filed, not fixed: gh-1960" closed just-makeit#1960.

  Not closing it?  Reword so no keyword touches the reference:
                   "filed gh-N", "left open: gh-N", "gh-N stays open".
  Closing it?      Declare it: "(gh-N)" ending the PR title, or a line in
                   the PR body or a commit message that begins "Closes #N"
                   followed by the line's end or punctuation.

A commit message is reworded with `git rebase -i` and a force-push. The
title and body are read from the event that started this run: after editing
them, push again (an empty commit will do), because a re-run reads the old
text."""


def check_pull_request(path: str) -> int:
    """The gate: a pull request's commits, title and body."""
    try:
        with open(path, encoding="utf-8") as f:
            event: object = json.load(f)
    except (OSError, ValueError) as e:
        where = path or "GITHUB_EVENT_PATH (unset)"
        print(f"close-keywords-check: FAIL -- cannot read {where}: {e}")
        return 1
    title = _get(event, "pull_request", "title")
    body = _get(event, "pull_request", "body")
    head = _get(event, "pull_request", "head", "sha")
    base = _get(event, "pull_request", "base", "sha")
    repo = _get(event, "repository", "full_name")
    expected = _get(event, "pull_request", "commits")
    if not (
        isinstance(title, str)
        and isinstance(head, str)
        and isinstance(base, str)
        and isinstance(repo, str)
        and head
        and base
    ):
        print(
            "close-keywords-check: FAIL -- the pull_request event lacks a "
            "title, head, base or repository; nothing to check is not a pass"
        )
        return 1
    why = _deepen(head, base)
    if why:
        print(
            f"close-keywords-check: FAIL -- cannot read {base[:8]}.."
            f"{head[:8]}: {why}"
        )
        return 1
    # The test merge GitHub checked out has the base it merged against as
    # its first parent; when the event's base.sha is older, excluding that
    # too keeps commits the branch merged in from main out of the range.
    exclude = [base]
    parents = _git("rev-parse", "HEAD^1", "HEAD^2").stdout.split()
    if len(parents) == 2 and parents[1] == head:
        exclude.append(parents[0])
    commits = _commits(head, exclude)
    if commits is None or (not commits and expected):
        print(
            f"close-keywords-check: FAIL -- read no commits in {base[:8]}.."
            f"{head[:8]}, but the PR has {expected}"
        )
        return 1
    sources = [
        *_sources(commits),
        ("PR title", title),
        ("PR body", body if isinstance(body, str) else ""),
    ]
    findings = undeclared(sources, title, repo)
    if findings:
        print(
            "close-keywords-check: FAIL -- this PR would close issue(s) it "
            "does not declare:\n"
        )
        for where, phrase in findings:
            print(f'  {where}: "{phrase}"')
        print(f"\n{_HOW}")
        return 1
    n = sum(len(CLOSING.findall(_lines(text))) for _, text in sources)
    carry = f"{n}, each one declared" if n else "none"
    print(
        f"close-keywords-check: {len(commits)} commit(s), the PR title and "
        f"its body; closing references: {carry}"
    )
    return 0


def _origin_repo() -> str:
    url = _git("remote", "get-url", "origin").stdout.strip()
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else ""


def advise(base: str) -> int:
    """Outside CI: notes on the branch's commits, never a failure."""
    lead = "close-keywords-check: not a pull request run"
    if not _has_commit(base):
        print(
            f"{lead}, and {base} is not in this clone -- nothing to read. "
            "The pull_request run in CI is the gate."
        )
        return 0
    commits = _commits("HEAD", [base]) or []
    findings = undeclared(_sources(commits), "", _origin_repo())
    if not findings:
        print(
            f"{lead}; {len(commits)} commit(s) ahead of {base} carry no "
            "undeclared closing reference (CI also reads the PR title and "
            "body)"
        )
        return 0
    print(
        f"{lead}. These closing references in the {len(commits)} commit(s) "
        f"ahead of {base} are not declared by any of them; CI refuses each "
        "unless the PR title or body declares it:\n"
    )
    for where, phrase in findings:
        print(f'  note: {where}: "{phrase}"')
    print(f"\n{_HOW}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--base",
        default="origin/main",
        help="outside CI: what the branch's commits are measured against",
    )
    args = ap.parse_args(argv)
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event in ("pull_request", "pull_request_target"):
        return check_pull_request(os.environ.get("GITHUB_EVENT_PATH", ""))
    if event:
        print(
            f"close-keywords-check: a {event} run, inert -- a closing keyword "
            "acts when it merges, so the pull_request run is the gate"
        )
        return 0
    return advise(str(args.base))


if __name__ == "__main__":
    sys.exit(main())
