#!/usr/bin/env python3
"""Land several ready PRs as ONE pull request, so they pay one CI run.

A repo whose ruleset requires branches to be up to date
(``strict_required_status_checks_policy``) makes every merge knock every
other open PR back to BEHIND. Landing N ready PRs one at a time then costs N
full CI runs in series, plus a re-run for each one a sibling knocked back. A
*train* cherry-picks the PRs' commits, unchanged and in order, onto the
current base as one branch, and lands that branch by REBASE merge: each
commit keeps its own message and its own ``Closes #N``, and CI runs once, on
the combined tree. That is the only tree that will exist on the base, so it
is the one worth testing. A merge queue does not buy this: it runs CI once
per queued PR.

What this script does, failing closed at every step:

1. Refuses a PR that is not open, is a draft, targets another base, or has
   an unresolved review thread. A train carries only ready work.
2. Fetches each PR's head from ``refs/pull/<n>/head`` and refuses it if
   that is not the head GitHub reports (the PR moved under you), or if the
   range carries a merge commit (a train is a linear series of picks).
3. Cherry-picks every commit onto a new branch off ``<remote>/<base>``. A
   conflict aborts: two PRs that touch the same lines need a human, and
   resolving them here would land a diff nobody reviewed.
4. Requires each picked commit's ``git patch-id --stable`` and its full
   message to equal its source commit's, so the train lands exactly what
   was reviewed.
5. Runs the gate (``make lint`` unless told otherwise) on the combined tree.
   Two PRs can each be green alone and red together; that is the case the
   train exists to catch before main does.
6. Runs ``scripts/close-keywords.py`` against a synthetic ``pull_request``
   event built from the train's own title and body, when that script is
   vendored, so the train cannot close an issue none of its PRs declared.
7. Without ``--push``, stops there: a dry run. It deletes the train branch
   and puts you back where you were. With ``--push`` it pushes the branch,
   opens the train PR and closes each constituent with a comment linking
   it. Their branches are kept, for the train's merge to retire.

It never merges. ``gh pr merge <train> --rebase --match-head-commit <sha>``,
or ``--auto``, stays the gate: CI decides, server-side.

Environment: ``GH`` names the gh binary (default ``gh``), which is how the
tests substitute a fake.

Usage:  train.py [--base main] [--remote origin] [--branch NAME]
                 [--title TEXT] [--gate CMD] [--push] PR [PR ...]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

#: What a train's PR body says, so a reader knows how to land it.
LAND_HOW = (
    "Land it with a **rebase merge** so each commit keeps its own message "
    "and closing keywords. Do not squash it."
)


class RefusedError(Exception):
    """A step failed closed; the message says which and why."""


def run(*args: str, check: bool = True, **kw) -> subprocess.CompletedProcess:
    """Runs a command, capturing text output."""
    p = subprocess.run(args, capture_output=True, text=True, **kw)
    if check and p.returncode != 0:
        raise RefusedError(
            f"`{' '.join(args)}` exited {p.returncode}: "
            f"{(p.stderr or p.stdout).strip()}"
        )
    return p


def git(*args: str, check: bool = True) -> str:
    return run("git", *args, check=check).stdout.strip()


def gh(*args: str) -> str:
    return run(os.environ.get("GH", "gh"), *args).stdout


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


def check_pr(n: int, base: str, repo: str) -> dict:
    """The PR's metadata, or RefusedError naming what makes it not ready."""
    pr = json.loads(
        gh(
            "pr",
            "view",
            str(n),
            "--json",
            "number,state,isDraft,baseRefName,headRefOid,title,url",
        )
    )
    if pr["state"] != "OPEN":
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
    return pr


def pr_commits(n: int, pr: dict, remote: str, base: str) -> list[str]:
    """The PR's own commits, oldest first, from the head GitHub reports."""
    ref = f"refs/train/pr-{n}"
    git("fetch", "--quiet", "--no-tags", remote, f"+refs/pull/{n}/head:{ref}")
    head = git("rev-parse", ref)
    if head != pr["headRefOid"]:
        raise RefusedError(
            f"#{n}: refs/pull/{n}/head is {head[:9]} but GitHub reports "
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
    return commits


def body_for(
    prs: list[dict],
    picks: list[tuple[int, str, str]],
    base_sha: str,
    base: str,
    gate: str,
) -> str:
    rows = "\n".join(
        f"| `{git('log', '-1', '--format=%s', dst)}` | #{n} |"
        for n, _, dst in picks
    )
    nums = ", ".join(f"#{p['number']}" for p in prs)
    return (
        f"A merge train: {nums} cherry-picked unchanged onto `{base}` "
        f"{base_sha[:9]}, so they land after one CI run. {LAND_HOW}\n\n"
        f"| commit | from |\n|---|---|\n{rows}\n\n"
        "**Verified by `make train`:** each commit's `git patch-id "
        "--stable` and full message equal its source PR's commit, and "
        f"`{gate}` passed on the combined tree.\n\n"
        f"Supersedes {nums}; each PR's own description has its detail. "
        "Their branches are kept until this merges.\n"
    )


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
    if run("git", "status", "--porcelain", "--untracked-files=no").stdout:
        raise RefusedError("the working tree has uncommitted changes")
    repo = json.loads(gh("repo", "view", "--json", "nameWithOwner"))[
        "nameWithOwner"
    ]
    prs = [check_pr(n, args.base, repo) for n in args.prs]
    git("fetch", "--quiet", "--no-tags", args.remote, args.base)
    base_sha = git("rev-parse", f"{args.remote}/{args.base}")
    commits = {
        p["number"]: pr_commits(p["number"], p, args.remote, args.base)
        for p in prs
    }

    branch = args.branch or "train/" + "-".join(map(str, args.prs))
    if git(
        "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False
    ):
        raise RefusedError(f"branch {branch} already exists locally")
    if git("ls-remote", "--heads", args.remote, branch):
        raise RefusedError(f"branch {branch} already exists on {args.remote}")

    start = git(
        "symbolic-ref", "--quiet", "--short", "HEAD", check=False
    ) or git("rev-parse", "HEAD")
    git("switch", "--quiet", "-c", branch, base_sha)
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
                f"`{args.gate}` failed on the combined tree; branch {branch} "
                "is kept so the fix can go into the commit that needs it"
            )

        head = git("rev-parse", "HEAD")
        title = args.title or (
            "train: " + ", ".join(f"#{p['number']}" for p in prs)
        )
        body = body_for(prs, picks, base_sha, args.base, args.gate)
        close_keywords(title, body, head, base_sha, repo, len(picks))

        if not args.push:
            print(
                f"train: dry run OK. To publish: re-run with --push "
                f"(make train PRS='{' '.join(map(str, args.prs))}' "
                "PUSH=1)"
            )
            return 0

        git("push", "--quiet", "-u", args.remote, branch)
        keep = True
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(body)
        url = (
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
        url = url[-1] if url else ""
        for p in prs:
            gh(
                "pr",
                "close",
                str(p["number"]),
                "--comment",
                f"Superseded by the train {url}: this PR's commits, "
                "cherry-picked unchanged onto the current base (patch-id and "
                "message verified). The branch is kept until it merges.",
            )
        print(
            f"train: opened {url}; closed "
            + ", ".join(f"#{p['number']}" for p in prs)
        )
        print(
            f"train: land it with: gh pr merge {url} --rebase "
            f"--match-head-commit {head}"
        )
        return 0
    finally:
        git("switch", "--quiet", start, check=False)
        if not keep:
            git("branch", "--quiet", "-D", branch, check=False)
        for p in prs:
            git(
                "update-ref", "-d", f"refs/train/pr-{p['number']}", check=False
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "prs",
        nargs="+",
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
    args = ap.parse_args(argv)
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
