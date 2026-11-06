#!/usr/bin/env python3
"""Land several ready PRs as ONE pull request, so they pay one CI run.

A repo whose ruleset requires branches to be up to date
(``strict_required_status_checks_policy``) makes every merge knock every
other open PR back to BEHIND. Landing N ready PRs one at a time then costs N
full CI runs in series, plus a re-run for each one a sibling knocked back. A
*train* cherry-picks the PRs' commits, unchanged and in order, onto the
current base as one branch, and lands that branch by REBASE merge: each
commit keeps its own message, and CI runs once, on the combined tree. That
is the only tree that will exist on the base, so it is the one worth
testing. A merge queue does not buy this: it runs CI once per queued PR.

What this script does, failing closed at every step:

1. Refuses a PR that is not open, is a draft, targets another base, or has
   an unresolved review thread. A train carries only ready work.
   Reads each PR's linked closing issues from GitHub
   (``closingIssuesReferences``), and refuses when they cannot be read.
2. Fetches each PR's head from ``refs/pull/<n>/head`` and refuses it if
   that is not the head GitHub reports (the PR moved under you), or if the
   range carries a merge commit (a train is a linear series of picks).
   Refuses a commit whose author or committer email is a placeholder:
   its domain (after the ``@``) has no dot, as in ``t <t@t>``. A pick
   copies identity faithfully, so the train would land it on the base
   (doppler fdde12e7c). Bot identities such as
   ``41898282+github-actions[bot]@users.noreply.github.com`` and
   ``noreply@just-buildit.invalid`` have a dotted domain and pass.
3. Cherry-picks every commit onto a new branch off ``<remote>/<base>``. A
   conflict aborts: two PRs that touch the same lines need a human, and
   resolving them here would land a diff nobody reviewed.
4. Requires each picked commit's ``git patch-id --stable`` and its full
   message to equal its source commit's, so the train lands exactly what
   was reviewed.
5. Runs the gate (``make lint`` unless told otherwise) on the combined tree.
   Two PRs can each be green alone and red together; that is the case the
   train exists to catch before main does.
6. Declares each of those issues on its own ``Closes`` line in the train
   PR's body, naming the PR it came from. A constituent is closed
   unmerged, and a PR closed unmerged closes nothing, so an issue linked
   only by its description (the usual place for ``Closes #N``) would
   otherwise stay open when the train lands (just-bashit#160).
7. Runs ``scripts/close-keywords.py`` against a synthetic ``pull_request``
   event built from the train's own title and body, when that script is
   vendored, so the train cannot close an issue none of its PRs declared.
8. Without ``--push``, stops there: a dry run. It deletes the train branch
   and puts you back where you were. With ``--push`` it pushes the branch,
   opens the train PR and closes each constituent with a comment linking
   it. Their branches are kept, for the train's merge to retire.
9. Cancels each closed constituent's in-progress and queued workflow
   runs of the head the train took (``cancel_runs``). Closing a PR does
   not cancel its CI, and that CI can gate nothing once the train's run
   on the combined tree replaces it; left running, it holds runners the
   train and every release are queued for (just-buildit.github.io#200).
   A run of the train's own head is never cancelled, nor any on its
   branch for a constituent.

Once the train PR exists nothing is REFUSED, because something was
published. Each constituent gets its comment (``gh pr comment``), then is
closed (``gh pr close``): two calls, so a retry never repeats a comment
that landed. A run that cannot be listed or cancelled (step 9) is a
``train: warning`` naming it, never a failure. Each is tried
``RETRY_TRIES`` times, waiting ``TRAIN_RETRY_DELAY`` seconds (default 2),
doubling, between tries: a
GitHub API failure there is usually transient. A constituent merged in
the meantime counts as done. If one still fails, the run
prints ``train: PUBLISHED`` with the train's URL, the constituents closed
and those still open, and the exact ``gh pr close`` that finishes each,
and exits ``EXIT_PUBLISHED_PARTIAL`` (3). Do not re-run it: a re-run
refuses before it changes anything, on the first closed constituent, or
on the train branch, which it reports as the open train (printing the
same finish commands); one given another ``--branch`` could open a second
train for the same PRs.

Exit status: 0 published (or a clean dry run); 1 REFUSED, nothing
published; 2 a usage error; 3 published, but a constituent is still open.

It never merges. ``gh pr merge <train> --rebase --match-head-commit <sha>``,
or ``--auto``, stays the gate: CI decides, server-side.

The train PR's table records, for each picked commit, the source commit it
was picked from (``source``); a constituent's last row is the head it had
when the train closed it.

Re-cut (``--recut T``), for a train that went red. Its constituents are
closed, and GitHub refuses ``gh pr reopen`` on a PR whose branch was
force-pushed while it was closed, which is exactly what a fix-up does.
A re-cut:

1. Reads the constituents, and the head each had, from train ``T``'s
   table. Refuses a merged train, one on another base, or one whose body
   lists no constituents. ``PR`` arguments are not taken with it.
2. Compares each constituent's branch on the remote with that head. A
   head that moved is REFUSED, printed as ``old -> new`` with the commit
   subjects, unless the PR is named in ``--moved`` ("its new head was
   reviewed"). A PR named in ``--moved`` whose head did not move is
   refused too: a stale list is a mistake. A head with no record (a train
   cut before ``source`` existed) is read from GitHub, which holds a
   closed PR's head where the train left it.
3. Composes from those heads exactly as above, every refusal intact
   except that a constituent may be closed, since the train closed it.
4. With ``--push``, and only once the gate has passed on the combined
   tree: closes ``T``; reopens each closed constituent. If GitHub refuses
   to reopen an accepted moved PR, pushes its branch back to the closed
   head (``--force-with-lease`` pinned to the new head), reopens it, and
   restores the new head (lease pinned to the closed head). Then reads
   ``state,headRefOid`` back and requires OPEN at the head the train
   composed. Closing ``T`` cancels the active runs of ``T``'s head, as
   step 9 does a constituent's, before the new head is pushed. It then
   publishes as above, reusing ``T``'s branch name with a lease pinned to
   ``T``'s head. Without ``--push`` it changes nothing
   on GitHub. If the restoring push fails, it stops with the command that
   restores the branch, and the same re-cut as a dry run: once its
   ``#n moved:`` line ends at the reviewed head, adding ``--push``
   recovers (the constituents it reopened read as open, the rest are
   reopened). MOVED names a PR, not a sha, so that check is the reader's.

Environment: ``GH`` names the gh binary (default ``gh``), which is how the
tests substitute a fake. ``TRAIN_RETRY_DELAY`` is the first wait, in
seconds, between tries of a step after publishing; the tests set it to 0.

Usage:  train.py [--base main] [--remote origin] [--branch NAME]
                 [--title TEXT] [--gate CMD] [--push] PR [PR ...]
        train.py [options] --recut T [--moved PR ...]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import re
import shlex
import tempfile
import time
from typing import Any

#: What a train's PR body says, so a reader knows how to land it.
LAND_HOW = (
    "Land it with a **rebase merge** so each commit keeps its own message. "
    "Do not squash it. Its PRs are closed unmerged, which closes none of "
    "the issues they link, so the issues they would have closed are "
    "declared below."
)

#: The closing references GitHub resolved for one PR: the keywords in its
#: description and commits, and any issue linked by hand in its sidebar.
CLOSING_QUERY = (
    "query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r)"
    "{pullRequest(number:$n){closingIssuesReferences(first:100)"
    "{totalCount nodes{number repository{nameWithOwner}}}}}}"
)


#: A row of the train's table: ``| `subject` | #N | `source sha` |``. The
#: source column is absent from trains cut before it existed.
ROW = re.compile(r"\| #(\d+) \|(?: `([0-9a-f]{40})` \|)?\s*$")

#: How long a re-cut waits for GitHub to report a reopened PR's new head.
VERIFY_TRIES = 10
VERIFY_DELAY = 3.0

#: How often a step after the train PR exists is tried, and the first wait
#: between tries in seconds (``TRAIN_RETRY_DELAY`` overrides it), doubling.
RETRY_TRIES = 3
RETRY_DELAY = 2.0

#: The exit status when the train PR is open but a constituent is not
#: closed. 1 is REFUSED (nothing published); argparse's usage error is 2.
EXIT_PUBLISHED_PARTIAL = 3

#: What ``gh pr close`` prints, failing, for a PR that is already merged.
MERGED = "because it was already merged"


class RefusedError(Exception):
    """A step failed closed; the message says which and why."""


def run(
    *args: str, check: bool = True, **kw: Any
) -> subprocess.CompletedProcess[str]:
    """Runs a command, capturing text output."""
    p = subprocess.run(args, capture_output=True, text=True, **kw)
    if check and p.returncode != 0:
        raise RefusedError(
            f"`{' '.join(args)}` exited {p.returncode}: "
            f"{(p.stderr or p.stdout).strip()}"
        )
    return p


def git(*args: str, check: bool = True) -> str:
    return str(run("git", *args, check=check).stdout).strip()


def gh(*args: str) -> str:
    return str(run(os.environ.get("GH", "gh"), *args).stdout)


def message(sha: str) -> bytes:
    """A commit's full message, byte for byte (everything after the header).

    ``--format=%B`` would add a trailing newline; the raw object does not.
    """
    raw = subprocess.run(
        ["git", "cat-file", "commit", sha], capture_output=True, check=True
    ).stdout
    return raw.split(b"\n\n", 1)[1] if b"\n\n" in raw else b""


def patch_id(sha: str) -> str:
    """``git patch-id --stable`` of one commit: its diff, ignoring position."""
    show = subprocess.run(
        ["git", "show", sha], capture_output=True, check=True
    ).stdout
    out = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=show,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return out.split()[0] if out.strip() else ""


def same_commit(src: str, dst: str) -> str | None:
    """None when ``dst`` carries exactly ``src``'s diff and message, else why
    not."""
    if patch_id(src) != patch_id(dst):
        return "its diff differs"
    if message(src) != message(dst):
        return "its message differs"
    return None


def placeholder_identity(sha: str) -> str | None:
    """Why commit ``sha`` carries a placeholder identity, or None.

    A placeholder is an email with no ``@`` at all (``t.t``), or whose
    domain (the part after the last ``@``) contains no dot -- ``t@t``,
    ``me@localhost``. A single-label domain is refused by design: no real
    mailbox and no bot noreply address uses one, so this needs no list of
    known owners. It is a shape check, not validation: ``t@t.`` passes.
    The author is checked first, then the committer.
    """
    fmt = "--format=%an%x00%ae%x00%cn%x00%ce"
    fields = git("show", "-s", fmt, sha).split("\0")
    for role, name, email in (
        ("authored", fields[0], fields[1]),
        ("committed", fields[2], fields[3]),
    ):
        if "@" not in email or "." not in email.rpartition("@")[2]:
            return f"is {role} by `{name} <{email}>`"
    return None


def check_pr(
    n: int, base: str, repo: str, closed_ok: bool = False
) -> dict[str, Any]:
    """The PR's metadata, or RefusedError naming what makes it not ready.

    ``closed_ok`` is a re-cut's: its constituents were closed by the train.
    """
    pr: dict[str, Any] = json.loads(
        gh(
            "pr",
            "view",
            str(n),
            "--json",
            "number,state,isDraft,baseRefName,headRefOid,title,url,"
            "headRefName,isCrossRepository",
        )
    )
    if pr["state"] != "OPEN" and not (closed_ok and pr["state"] == "CLOSED"):
        raise RefusedError(f"#{n} is {pr['state'].lower()}, not open")
    if pr["isDraft"]:
        raise RefusedError(f"#{n} is a draft")
    if pr["baseRefName"] != base:
        raise RefusedError(f"#{n} targets {pr['baseRefName']}, not {base}")
    owner, name = repo.split("/", 1)
    q = (
        "query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r)"
        "{pullRequest(number:$n){reviewThreads(first:100)"
        "{nodes{isResolved}}}}}"
    )
    threads = json.loads(
        gh(
            "api",
            "graphql",
            "-f",
            f"query={q}",
            "-f",
            f"o={owner}",
            "-f",
            f"r={name}",
            "-F",
            f"n={n}",
        )
    )["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    open_threads = sum(1 for t in threads if not t["isResolved"])
    if open_threads:
        raise RefusedError(
            f"#{n} has {open_threads} unresolved review thread(s)"
        )
    pr["closes"] = closing_issues(n, repo)
    return pr


def closing_issues(n: int, repo: str) -> list[str]:
    """The issues PR ``n`` would close on merge, as references.

    Read from GitHub's own parse (``closingIssuesReferences``), not from a
    regex over the description, so the train closes exactly what each PR
    would have. An issue in ``repo`` is ``#N``; one elsewhere keeps its
    ``owner/repo#N``. Any answer that is not a complete list is refused:
    a train opened on a partial one would silently leave issues open.
    """
    owner, name = repo.split("/", 1)
    out = gh(
        "api",
        "graphql",
        "-f",
        f"query={CLOSING_QUERY}",
        "-f",
        f"o={owner}",
        "-f",
        f"r={name}",
        "-F",
        f"n={n}",
    )
    try:
        reply = json.loads(out)
        refs = reply["data"]["repository"]["pullRequest"][
            "closingIssuesReferences"
        ]
        nodes = refs["nodes"]
        if reply.get("errors") or refs["totalCount"] != len(nodes):
            raise ValueError(reply.get("errors") or "a partial list")
        found = []
        for i in nodes:
            where = str(i["repository"]["nameWithOwner"])
            num = int(i["number"])
            same = where.lower() == repo.lower()
            found.append(f"#{num}" if same else f"{where}#{num}")
    except (ValueError, KeyError, TypeError) as e:
        raise RefusedError(
            f"#{n}: cannot read the issues it closes ({e!r}); a train "
            "opened without them would leave them open"
        ) from e
    return found


def closes_block(prs: list[dict[str, Any]]) -> str:
    """One ``Closes`` line per issue the PRs close, each naming its PRs.

    A line is ``- Closes #N, from #P.``: the reference ends at the comma,
    which is what both GitHub and ``close-keywords-check`` read as a
    declaration of #N, and ``from #P`` carries no keyword, so it closes
    nothing. An issue two PRs close is declared once.

    >>> a = {"number": 2, "closes": ["#7", "x/y#3"]}
    >>> b = {"number": 5, "closes": ["#7"]}
    >>> closes_block([a, b]).splitlines()
    ['- Closes #7, from #2 and #5.', '- Closes x/y#3, from #2.']
    >>> closes_block([{"number": 2, "closes": []}])
    ''
    """
    owners: dict[str, list[str]] = {}
    for p in prs:
        for ref in p["closes"]:
            owners.setdefault(ref, []).append(f"#{p['number']}")
    return "".join(
        f"- Closes {ref}, from {' and '.join(src)}.\n"
        for ref, src in owners.items()
    )


def pr_commits(
    n: int, pr: dict[str, Any], remote: str, base: str
) -> list[str]:
    """The PR's own commits, oldest first, from the head GitHub reports."""
    ref = f"refs/train/pr-{n}"
    src = pr.get("fetch", f"refs/pull/{n}/head")
    git("fetch", "--quiet", "--no-tags", remote, f"+{src}:{ref}")
    head = git("rev-parse", ref)
    if head != pr["headRefOid"]:
        raise RefusedError(
            f"#{n}: {src} is {head[:9]} but GitHub reports "
            f"{pr['headRefOid'][:9]}; the PR moved, re-run"
        )
    rng = f"{remote}/{base}..{ref}"
    if git("rev-list", "--merges", rng):
        raise RefusedError(
            f"#{n} carries a merge commit; rebase it onto {base} first"
        )
    commits = git("rev-list", "--reverse", rng).split()
    if not commits:
        raise RefusedError(f"#{n} has no commits ahead of {remote}/{base}")
    for sha in commits:
        who = placeholder_identity(sha)
        if who:
            raise RefusedError(
                f"#{n}'s commit {sha[:9]} {who}, a placeholder identity "
                "(no dot in its email domain); fix the authorship on the "
                "PR before it rides, e.g. `git commit --amend "
                "--reset-author` or `git rebase --exec 'git commit "
                f"--amend --no-edit --reset-author' {remote}/{base}`, "
                "and push"
            )
    return commits


def body_for(
    prs: list[dict[str, Any]],
    picks: list[tuple[int, str, str]],
    base_sha: str,
    base: str,
    gate: str,
    recut: int = 0,
) -> str:
    rows = "\n".join(
        f"| `{git('log', '-1', '--format=%s', dst)}` | #{n} | `{src}` |"
        for n, src, dst in picks
    )
    again = f"It re-cuts the train #{recut}. " if recut else ""
    nums = ", ".join(f"#{p['number']}" for p in prs)
    closes = closes_block(prs) or "None of its PRs links an issue.\n"
    return (
        f"A merge train: {nums} cherry-picked unchanged onto `{base}` "
        f"{base_sha[:9]}, so they land after one CI run. {again}"
        f"{LAND_HOW}\n\n"
        f"| commit | from | source |\n|---|---|---|\n{rows}\n\n"
        "**Issues its PRs close**, read from GitHub's "
        "`closingIssuesReferences` for each:\n\n"
        f"{closes}\n"
        "**Verified by `make train`:** each commit's `git patch-id "
        "--stable` and full message equal its source PR's commit, and "
        f"`{gate}` passed on the combined tree.\n\n"
        f"Supersedes {nums}; each PR's own description has its detail. "
        "Their branches are kept until this merges.\n"
    )


def read_train(t: int, base: str) -> dict[str, Any]:
    """Train ``t``'s PR, with its constituents and recorded heads (see
    ``constituents``)."""
    tr: dict[str, Any] = json.loads(
        gh(
            "pr",
            "view",
            str(t),
            "--json",
            "number,state,baseRefName,headRefName,headRefOid,body",
        )
    )
    if tr["state"] == "MERGED":
        raise RefusedError(f"the train #{t} is merged; nothing to re-cut")
    if tr["baseRefName"] != base:
        raise RefusedError(
            f"the train #{t} targets {tr['baseRefName']}, not {base}"
        )
    tr["heads"] = constituents(tr["body"])
    if not tr["heads"]:
        raise RefusedError(
            f"#{t} is not a train: its body has no `| #N |` rows"
        )
    return tr


def constituents(body: str) -> dict[int, str | None]:
    """The ``from`` and ``source`` columns of a train body's table.

    Read from the table ``body_for`` writes, one row per picked commit:
    the constituents are the ``from`` column in order of first appearance,
    and each one's head is the ``source`` of its last row (None for a
    train cut before that column existed).

    >>> body = ("| commit | from | source |\\n|---|---|---|\\n"
    ...         "| `a` | #3 | `" + "1" * 40 + "` |\\n"
    ...         "| `b` | #3 | `" + "2" * 40 + "` |\\n"
    ...         "| `c` | #5 |\\n")
    >>> heads = constituents(body)
    >>> list(heads), heads[3][:4], heads[5]
    ([3, 5], '2222', None)
    """
    heads: dict[int, str | None] = {}
    for line in body.splitlines():
        m = ROW.search(line)
        if m:
            heads[int(m.group(1))] = m.group(2)
    return heads


def subject(sha: str) -> str:
    return git("log", "-1", "--format=%s", sha, check=False) or "?"


def plan_reopen(
    pr: dict[str, Any], recorded: str | None, remote: str
) -> str | None:
    """Points a closed constituent at its branch's current head.

    Sets ``closed_head`` (what the train left, which GitHub reopens
    against), and makes ``headRefOid`` and ``fetch`` the branch tip, so
    the train composes from it. Returns a line describing the move, or
    None when the head did not move. Refuses a fork's branch (no push
    rights to restore it) and a missing branch, and a recorded head that
    disagrees with the one GitHub holds.
    """
    n, br = pr["number"], pr.get("headRefName") or ""
    frozen = pr["headRefOid"]
    if recorded and recorded != frozen:
        raise RefusedError(
            f"#{n}: the train recorded head {recorded[:9]} but GitHub "
            f"holds {frozen[:9]} for the closed PR"
        )
    if pr.get("isCrossRepository"):
        raise RefusedError(f"#{n}'s branch is in a fork; reopen it by hand")
    closed = f"refs/train/closed-{n}"
    pull = f"+refs/pull/{n}/head:{closed}"
    git("fetch", "--quiet", "--no-tags", remote, pull)
    if git("rev-parse", closed) != frozen:
        raise RefusedError(f"#{n}: refs/pull/{n}/head is not {frozen[:9]}")
    line = git("ls-remote", "--heads", remote, f"refs/heads/{br}")
    if not br or not line:
        raise RefusedError(f"#{n}: its branch {br or '?'} is gone")
    tip = line.split()[0]
    pr.update(closed_head=frozen, headRefOid=tip, fetch=f"refs/heads/{br}")
    if tip == frozen:
        return None
    new = f"+refs/heads/{br}:{closed}-new"
    git("fetch", "--quiet", "--no-tags", remote, new)
    return moved_line(n, frozen, tip)


def moved_line(n: int, old: str, new: str) -> str:
    return (
        f"#{n} moved: {old[:9]} ({subject(old)}) -> "
        f"{new[:9]} ({subject(new)})"
    )


def moved(
    pr: dict[str, Any], old: dict[str, Any], remote: str
) -> str | None:
    """Why constituent ``pr`` of train ``old`` counts as moved, or None.

    A closed one is planned for reopening (``plan_reopen``). An open one
    was reopened already, by a re-cut that stopped part way or by hand,
    and its head is compared with the train's record all the same. With
    no record (a train cut before ``source``) an open one's head cannot be
    told from a moved one, so it counts as moved: only MOVED accepts it.
    """
    n, was = pr["number"], old["heads"][pr["number"]]
    if pr["state"] == "CLOSED":
        return plan_reopen(pr, was, remote)
    now = pr["headRefOid"]
    if was == now:
        return None
    ref = f"refs/train/closed-{n}-new"
    git("fetch", "--quiet", "--no-tags", remote, f"+refs/pull/{n}/head:{ref}")
    if was is None:
        return (
            f"#{n} is open and the train #{old['number']} recorded no head "
            f"for it; it is at {now[:9]} ({subject(now)})"
        )
    return moved_line(n, was, now)


def push_lease(
    remote: str, br: str, expect: str, sha: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Sets ``br`` to ``sha`` only if it is still exactly ``expect``."""
    return run(
        "git",
        "push",
        "--quiet",
        f"--force-with-lease=refs/heads/{br}:{expect}",
        remote,
        f"{sha}:refs/heads/{br}",
        check=check,
    )


def again(args: argparse.Namespace) -> str:
    """The ``make train`` arguments that repeat this run, without PUSH.

    >>> import argparse
    >>> again(argparse.Namespace(recut=9, moved={3, 1}, prs=[1, 3]))
    "RECUT=9 MOVED='1,3'"
    >>> again(argparse.Namespace(recut=0, moved=set(), prs=[4, 2]))
    "PRS='4 2'"
    """
    if args.recut:
        return f"RECUT={args.recut}" + (
            f" MOVED='{','.join(map(str, sorted(args.moved)))}'"
            if args.moved
            else ""
        )
    return f"PRS='{' '.join(map(str, args.prs))}'"


def reopen(pr: dict[str, Any], remote: str, rerun: str) -> None:
    """Reopens a closed constituent at the head the train composed.

    GitHub refuses to reopen a PR whose branch was force-pushed while it
    was closed. Only then, and only for a head that moved, is the branch
    pushed back to the closed head, the PR reopened, and the new head
    restored; each push's lease pins the exact sha it replaces.

    If that restoring push fails, the refusal prints the exact command
    that restores the branch, then ``rerun``: this run's ``make train``
    command WITHOUT ``PUSH=1``. Its dry run prints ``#n moved: old ->
    new``, and only once that ``new`` is the reviewed head is the push
    safe: MOVED names a PR, not a sha, so a re-cut pushed blind would take
    whatever the branch holds. When the lease was rejected (``stale
    info``), someone pushed after the reopen, and the refusal says the
    branch may hold a head nobody reviewed.
    """
    n, br = pr["number"], pr["headRefName"]
    old, new = pr["closed_head"], pr["headRefOid"]
    gh_bin = os.environ.get("GH", "gh")
    first = run(gh_bin, "pr", "reopen", str(n), check=False)
    if first.returncode != 0:
        if old == new:
            raise RefusedError(
                f"#{n}: gh pr reopen exited {first.returncode}: "
                f"{(first.stderr or first.stdout).strip()}"
            )
        print(
            f"train: #{n} refused to reopen; restoring {old[:9]} around it"
        )
        push_lease(remote, br, new, old)
        try:
            gh("pr", "reopen", str(n))
        finally:
            # Runs whether or not the reopen worked: the reviewed head goes
            # back either way. If it cannot, say exactly how to put it back.
            back = push_lease(remote, br, old, new, check=False)
            if back.returncode != 0:
                why = (back.stderr or back.stdout).strip()
                # A rejected lease means the branch is not at the closed
                # head: someone pushed after the reopen.
                raced = (
                    f"Someone pushed to {br} after the reopen, so it may "
                    "hold a head nobody reviewed; the restore below "
                    "refuses until you decide which head is right.\n"
                    if "stale info" in why
                    else ""
                )
                raise RefusedError(
                    f"#{n}: branch {br} may be left at {old[:9]}, not the "
                    f"reviewed head {new[:9]} (kept locally at "
                    f"refs/train/closed-{n}-new): {why}\n{raced}"
                    f"Restore with: git push --force-with-lease="
                    f"refs/heads/{br}:{old} {remote} {new}:refs/heads/{br}"
                    f"\nThen dry-run the same re-cut, with any TRAIN_* "
                    f"overrides you gave: {rerun}\n"
                    f"Add PUSH=1 only once its `#{n} moved:` line ends at "
                    f"the reviewed head {new[:9]}."
                )
    for i in range(VERIFY_TRIES):
        got = json.loads(
            gh("pr", "view", str(n), "--json", "state,headRefOid")
        )
        if got["state"] == "OPEN" and got["headRefOid"] == new:
            return
        if i + 1 < VERIFY_TRIES:
            time.sleep(VERIFY_DELAY)
    raise RefusedError(
        f"#{n}: reopened, but GitHub reports {got['state'].lower()} at "
        f"{got['headRefOid'][:9]}, not open at {new[:9]}"
    )


def gh_retried(*args: str, stop: str = "") -> str | None:
    """Runs ``gh *args`` up to ``RETRY_TRIES`` times; None once it succeeds.

    For a step that runs after the train PR exists, where a transient
    GitHub failure (a 502, a GraphQL timeout) must not end the run. Waits
    ``TRAIN_RETRY_DELAY`` seconds (default ``RETRY_DELAY``), doubling,
    between tries. Returns the last failure's text when every try failed,
    or at once when a failure's output contains ``stop``: a failure that
    another try cannot change.
    """
    delay = float(os.environ.get("TRAIN_RETRY_DELAY", RETRY_DELAY))
    why = ""
    for i in range(RETRY_TRIES):
        p = run(os.environ.get("GH", "gh"), *args, check=False)
        if p.returncode == 0:
            return None
        why = f"exited {p.returncode}: {(p.stderr or p.stdout).strip()}"
        if stop and stop in why:
            return why
        if i + 1 < RETRY_TRIES:
            time.sleep(delay * 2**i)
    return why


#: The workflow-run states ``cancel_runs`` cancels: those holding or
#: waiting for a runner. ``gh run list --status`` takes one at a time.
ACTIVE_RUNS = ("in_progress", "queued")


def cancel_runs(
    who: str, branch: str, sha: str, head: str, avoid: str = ""
) -> None:
    """Cancels the in-progress and queued workflow runs of ``sha`` on
    ``branch``.

    ``who`` (``#12``) is the PR just closed, whose head is ``sha`` on
    ``branch``. Closing a PR does not cancel its CI, and once the train's
    run on the combined tree replaces it, that CI gates nothing while it
    holds runners the train and any release wait for
    (just-buildit.github.io#200).

    Only a run whose ``headSha`` is ``sha`` is cancelled: a fork's PR
    branch may share its name with a branch of the base repo (``main``),
    whose runs are not this PR's. Nothing is cancelled when ``sha`` is
    the train's own ``head``, nor when ``branch`` is ``avoid`` (a
    constituent passes the train's branch). The old train a re-cut
    closes shares the new train's branch, so it passes no ``avoid``: it
    is told apart by sha, and closed before the new head is pushed.

    Called only once the train is published or about to be, so nothing
    here fails the run: a list or a cancel that fails is a
    ``train: warning`` naming the run, which is left as it was.
    """
    if not branch or sha == head or branch == avoid:
        return
    runs: list[dict[str, Any]] = []
    for status in ACTIVE_RUNS:
        try:
            runs += json.loads(
                gh(
                    "run",
                    "list",
                    "--branch",
                    branch,
                    "--status",
                    status,
                    "--limit",
                    "100",
                    "--json",
                    "databaseId,headSha,name,url",
                )
            )
        except (RefusedError, ValueError) as e:
            print(
                f"train: warning: cannot list {who}'s {status} runs on "
                f"{branch}, so none is cancelled: {e}"
            )
    for r in runs:
        if r.get("headSha") != sha:
            continue
        rid = str(r["databaseId"])
        name = f"run {rid} ({r.get('name', '?')}, {r.get('url', '?')})"
        why = gh_retried("run", "cancel", rid)
        if why is None:
            print(f"train: cancelled {who}'s {name}")
        else:
            print(f"train: warning: cannot cancel {who}'s {name}: {why}")


def superseded(url: str) -> str:
    """The comment each constituent gets, linking the train ``url``."""
    return (
        f"Superseded by the train {url}: the commits here, cherry-picked "
        "unchanged onto the current base (patch-id and message verified). "
        "The branch is kept until it merges."
    )


def finish(n: int, url: str, commented: bool) -> str:
    """The command that finishes closing constituent ``n`` of train ``url``.

    The one spelling every message prints. ``commented`` says the
    ``superseded`` comment already landed, so only the close is left;
    otherwise the close carries the comment.

    >>> finish(2, "U", True).split(" ", 1)[1]
    'pr close 2'
    >>> finish(2, "U", False).split(" ", 1)[1][:22]
    "pr close 2 --comment '"
    """
    cmd = [os.environ.get("GH", "gh"), "pr", "close", str(n)]
    if not commented:
        cmd += ["--comment", superseded(url)]
    return shlex.join(cmd)


def after_publish(
    url: str,
    head: str,
    args: argparse.Namespace,
    prs: list[dict[str, Any]],
    branch: str,
) -> int:
    """Closes each constituent in ``prs`` once the train PR ``url`` is
    open, on ``branch`` at ``head``.

    Each gets the ``superseded`` comment, then is closed, each step through
    ``gh_retried``; once closed, its active runs are cancelled
    (``cancel_runs``). They are two calls because ``gh pr close --comment``
    posts the comment before it closes, so retrying it would repeat a
    comment that landed. A constituent whose comment never lands is not
    closed, so the one ``finish`` command does both. A constituent merged
    in the meantime (gh says so: ``MERGED``) counts as done.

    When all are done, prints the train and how to land it and returns 0.
    When one is still open, the train is PUBLISHED all the same, so this
    never says REFUSED: it names the constituents closed and those still
    open, prints the ``finish`` command for each open one, and returns
    ``EXIT_PUBLISHED_PARTIAL``. It says not to re-run: a re-run refuses
    before it changes anything (on the first closed constituent, or on the
    train branch, which it names as the open train), but one given another
    ``TRAIN_BRANCH`` could open a second train for the same PRs.
    """
    done: list[int] = []
    merged: list[int] = []
    left: list[tuple[int, bool, str]] = []
    for p in prs:
        n = p["number"]
        why = gh_retried("pr", "comment", str(n), "--body", superseded(url))
        if why is not None:
            left.append((n, False, why))
            continue
        why = gh_retried("pr", "close", str(n), stop=MERGED)
        if why is None:
            done.append(n)
            cancel_runs(
                f"#{n}",
                p.get("headRefName") or "",
                p["headRefOid"],
                head,
                avoid=branch,
            )
        elif MERGED in why:
            merged.append(n)
        else:
            left.append((n, True, why))
    land = (
        f"train: land it with: gh pr merge {url} --rebase "
        f"--match-head-commit {head}"
    )
    if not left:
        print(f"train: opened {url}; closed {nums(done) or 'none'}")
        if merged:
            print(f"train: already merged, so not closed: {nums(merged)}")
        print(land)
        return 0
    print(
        f"train: PUBLISHED -- opened {url}, but {nums(n for n, _, _ in left)} "
        f"did not close after {RETRY_TRIES} tries"
    )
    print(f"train: closed: {nums(done) or 'none'}")
    if merged:
        print(f"train: already merged, so not closed: {nums(merged)}")
    for n, _, why in left:
        print(f"train: still open: #{n} -- {why}")
    print("train: finish with:")
    for n, commented, _ in left:
        print("  " + finish(n, url, commented))
    print(
        f"train: do not re-run make train {again(args)} PUSH=1: the train "
        "is already open. A re-run refuses, and one given another "
        "TRAIN_BRANCH could open a second train. Run the commands above."
    )
    print(land)
    return EXIT_PUBLISHED_PARTIAL


def nums(ns: Any) -> str:
    """``#1, #2`` for PR numbers ``ns``.

    >>> nums([1, 2])
    '#1, #2'
    """
    return ", ".join(f"#{n}" for n in ns)


def close_keywords(
    title: str, body: str, head: str, base_sha: str, repo: str, n: int
) -> None:
    """The vendored closing-keyword gate, on the PR this push will open."""
    script = pathlib.Path("scripts/close-keywords.py")
    if not script.is_file():
        return
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(
            {
                "pull_request": {
                    "title": title,
                    "body": body,
                    "commits": n,
                    "head": {"sha": head},
                    "base": {"sha": base_sha},
                },
                "repository": {"full_name": repo},
            },
            f,
        )
    env = dict(
        os.environ, GITHUB_EVENT_NAME="pull_request", GITHUB_EVENT_PATH=f.name
    )
    p = subprocess.run(
        [sys.executable, str(script), "--base", base_sha],
        capture_output=True,
        text=True,
        env=env,
    )
    os.unlink(f.name)
    print(p.stdout.rstrip())
    if p.returncode != 0:
        raise RefusedError("close-keywords-check refused the train")


def compose(args: argparse.Namespace) -> int:
    """``compose_train``, then drops the refs it fetched under
    ``refs/train/``. A failed run keeps each ``closed-<n>-new``: it holds a
    reviewed head a failed restore may have left nowhere else."""
    ok = False
    try:
        rc = compose_train(args)
        ok = True
        return rc
    finally:
        for n in args.prs:
            for r in ("pr-{}", "closed-{}") + (() if not ok else (
                "closed-{}-new",
            )):
                ref = "refs/train/" + r.format(n)
                git("update-ref", "-d", ref, check=False)


def compose_train(args: argparse.Namespace) -> int:
    if run("git", "status", "--porcelain", "--untracked-files=no").stdout:
        raise RefusedError("the working tree has uncommitted changes")
    repo = json.loads(gh("repo", "view", "--json", "nameWithOwner"))[
        "nameWithOwner"
    ]
    old: dict[str, Any] | None = None
    if args.recut:
        old = read_train(args.recut, args.base)
        args.prs = list(old["heads"])
    prs = [
        check_pr(n, args.base, repo, closed_ok=bool(old)) for n in args.prs
    ]
    if old is not None:
        moves = {}
        for p in prs:
            why = moved(p, old, args.remote)
            if why:
                moves[p["number"]] = why
        for line in moves.values():
            print(f"train: {line}")
        unnamed = sorted(set(moves) - args.moved)
        if unnamed:
            raise RefusedError(
                "moved since the train: "
                + ", ".join(f"#{n}" for n in unnamed)
                + "; name each one in MOVED once its new head is reviewed"
            )
        stale = sorted(args.moved - set(moves))
        if stale:
            raise RefusedError(
                "named in MOVED but not moved: "
                + ", ".join(f"#{n}" for n in stale)
            )
    git("fetch", "--quiet", "--no-tags", args.remote, args.base)
    base_sha = git("rev-parse", f"{args.remote}/{args.base}")
    commits = {
        p["number"]: pr_commits(p["number"], p, args.remote, args.base)
        for p in prs
    }

    branch = args.branch or "train/" + "-".join(map(str, args.prs))
    # A re-cut may reuse the old train's branch, but only where it still
    # holds exactly the old train's head: nothing else is lost.
    reuse = old["headRefOid"] if old and branch == old["headRefName"] else ""
    local = git(
        "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False
    )
    on_remote = git("ls-remote", "--heads", args.remote, branch).split()[:1]
    if (local and local != reuse) or (on_remote and on_remote[0] != reuse):
        # A run that published and could not close every constituent left
        # the branch as an open train: that one is to be finished, never
        # deleted, since deleting its branch closes the train.
        trains = [
            t
            for t in json.loads(
                gh(
                    "pr",
                    "list",
                    "--head",
                    branch,
                    "--state",
                    "open",
                    "--json",
                    "number,url,isCrossRepository,baseRefName",
                )
            )
            # ``--head`` matches the bare branch name, so a fork's PR of
            # that name is not this train; nor is the train being re-cut.
            if not t["isCrossRepository"]
            and t["baseRefName"] == args.base
            and t["number"] != (old["number"] if old else None)
        ]
        if trains:
            url = trains[0]["url"]
            todo = [p["number"] for p in prs if p["state"] == "OPEN"]
            raise RefusedError(
                f"branch {branch} is already the open train {url}; do not "
                "re-run. "
                + (
                    "Finish closing its constituents with:\n"
                    + "\n".join("  " + finish(n, url, False) for n in todo)
                    if todo
                    else "Its constituents are closed."
                )
            )
    if local and local != reuse:
        raise RefusedError(f"branch {branch} already exists locally")
    if on_remote and on_remote[0] != reuse:
        # Most often a run that pushed the branch and stopped before
        # `gh pr create`: the push is not recognisable (the picks get new
        # committer dates), so name the recovery instead of guessing.
        raise RefusedError(
            f"branch {branch} already exists on {args.remote} at "
            f"{on_remote[0][:9]}; if it is a train push that never got its "
            f"PR, delete it with: git push --force-with-lease=refs/heads/"
            f"{branch}:{on_remote[0]} {args.remote} :refs/heads/{branch} "
            "-- or pass TRAIN_BRANCH=<another name>"
        )

    start = git(
        "symbolic-ref", "--quiet", "--short", "HEAD", check=False
    ) or git("rev-parse", "HEAD")
    # A dry run composes on a scratch branch of its own, so it never resets
    # or deletes a branch that was there before it. A push replaces a local
    # copy of the train branch only where it holds the old train's head.
    work = branch if args.push else f"dry-run/{branch}"
    reset = bool(local) if args.push else True
    git("switch", "--quiet", "-C" if reset else "-c", work, base_sha)
    keep = False
    try:
        picks: list[tuple[int, str, str]] = []
        for p in prs:
            n = p["number"]
            for src in commits[n]:
                r = run("git", "cherry-pick", src, check=False)
                if r.returncode != 0:
                    run("git", "cherry-pick", "--abort", check=False)
                    raise RefusedError(
                        f"#{n}'s commit {src[:9]} does not apply on "
                        f"{args.base}"
                        + (" and the PRs before it" if picks else "")
                        + f"; rebase #{n} or leave it out of the train"
                    )
                dst = git("rev-parse", "HEAD")
                why = same_commit(src, dst)
                if why:
                    raise RefusedError(f"#{n}'s commit {src[:9]}: {why}")
                picks.append((n, src, dst))
        print(
            f"train: {len(picks)} commit(s) from {len(prs)} PR(s) on "
            f"{branch}, each identical to its source"
        )

        print(f"train: running `{args.gate}` on the combined tree")
        if subprocess.run(args.gate, shell=True).returncode != 0:
            keep = True
            raise RefusedError(
                f"`{args.gate}` failed on the combined tree; branch {work} "
                "is kept so the fix can go into the commit that needs it"
            )

        head = git("rev-parse", "HEAD")
        title = args.title or (
            "train: " + ", ".join(f"#{p['number']}" for p in prs)
        )
        body = body_for(
            prs, picks, base_sha, args.base, args.gate, args.recut
        )
        close_keywords(title, body, head, base_sha, repo, len(picks))

        if not args.push:
            if old is not None:
                closed = [p for p in prs if p["state"] == "CLOSED"]
                print(
                    f"train: a re-cut would close #{args.recut} and reopen "
                    + (", ".join(f"#{p['number']}" for p in closed) or "none")
                )
            print(
                "train: dry run OK. To publish: re-run with --push "
                f"(make train {again(args)} PUSH=1)"
            )
            return 0

        if old is not None:
            if old["state"] == "OPEN":
                gh(
                    "pr",
                    "close",
                    str(args.recut),
                    "--comment",
                    "Re-cut by `make train RECUT=` onto the current base; "
                    "the new train links back here.",
                )
                # Before the push: the old train's runs are on the branch
                # the new one may reuse, told apart only by their sha.
                cancel_runs(
                    f"#{args.recut}",
                    old["headRefName"],
                    old["headRefOid"],
                    head,
                )
            for p in prs:
                if p["state"] == "CLOSED":
                    reopen(p, args.remote, f"make train {again(args)}")
        if on_remote:
            git(
                "push",
                "--quiet",
                "-u",
                f"--force-with-lease=refs/heads/{branch}:{reuse}",
                args.remote,
                branch,
            )
        else:
            git("push", "--quiet", "-u", args.remote, branch)
        keep = True
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(body)
        lines = (
            gh(
                "pr",
                "create",
                "--base",
                args.base,
                "--head",
                branch,
                "--title",
                title,
                "--body-file",
                f.name,
            )
            .strip()
            .splitlines()
        )
        os.unlink(f.name)
        url = lines[-1] if lines else ""
        # Published: from here on nothing may say REFUSED (gh-192 in
        # just-buildit.github.io). ``after_publish`` retries each close and,
        # if one still fails, says what is open and how to finish it.
        return after_publish(url, head, args, prs, branch)
    finally:
        git("switch", "--quiet", start, check=False)
        if not keep:
            git("branch", "--quiet", "-D", work, check=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "prs",
        nargs="*",
        type=int,
        metavar="PR",
        help="PR numbers, in the order their commits land",
    )
    ap.add_argument("--base", default="main")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--gate", default="make lint")
    ap.add_argument("--push", action="store_true")
    ap.add_argument(
        "--recut",
        type=int,
        default=0,
        metavar="T",
        help="re-cut the train PR T from its constituents",
    )
    ap.add_argument(
        "--moved",
        default="",
        metavar="'PR[,PR...]'",
        help="with --recut: constituents whose moved head was reviewed, "
        "comma or space separated, as ONE argument",
    )
    args = ap.parse_args(argv)
    try:
        args.moved = {int(x) for x in re.split(r"[,\s]+", args.moved) if x}
    except ValueError:
        print(f"train: REFUSED -- --moved {args.moved!r} is not PR numbers")
        return 1
    if bool(args.prs) == bool(args.recut):
        print("train: REFUSED -- give PRs or --recut T, not both or neither")
        return 1
    if args.moved and not args.recut:
        print("train: REFUSED -- --moved only means something with --recut")
        return 1
    if len(set(args.prs)) != len(args.prs):
        print("train: REFUSED -- a PR is listed twice")
        return 1
    try:
        return compose(args)
    except RefusedError as e:
        print(f"train: REFUSED -- {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
