#!/usr/bin/env python3
"""Wait while main's CI for a commit is alive, then say whether it passed.

CANONICAL. Vendored verbatim by every repo with ``HAS_RELEASE`` and gated
by ``make standard-check``. It is the ONE answer to "did main's CI certify
this commit?", asked from two places:

- ``make release-verify-ci``: a release workflow's verify job, before
  anything is built or published. A tag must point at a commit whose
  ``CI_CHECK_NAME`` check concluded ``success`` on main's push run.
- ``scripts/release-watch.sh``, when that verify job failed: is CI for the
  tag still running (wait for it), green (rerun the release), red (rerun
  CI's failed jobs first), or something no rerun can fix (stop, recovery
  unspent)? It used to answer with its own copy of the lookup, and the
  copy read a failed API call as "CI finished" (just-buildit.github.io#226).

The waiting rule
----------------
Every poll reads the newest push run on main of the CI workflow
(``CI_WORKFLOW``) for the SHA through the Actions API, not the check-runs
list: a run queued behind another in its concurrency group has NO jobs and
so no check-run at all, which is how a merely queued CI read as "never
started" and then as a timeout (just-makeit v0.127.1 and v0.128.0,
2026-11-11, each spending the release's one recovery on it).

``alive``
    The run's status is anything but ``completed`` -- queued, pending,
    waiting (an environment's approval), requested, in progress, or a
    status GitHub adds later. Only ``completed`` has a result to read, so
    nothing else is judged. Keep waiting, with no cap of this script's
    own unless ``--max-minutes`` gives one: in a workflow the job's
    ``timeout-minutes`` is the cap, and every waiting line says so.
``no-run``
    No run for the SHA after ``--appear`` seconds. A push run registers
    within seconds of its commit (3-5 s over 100 runs of just-makeit's,
    2026-11-11), so main never ran CI on this commit.
``green`` / ``red``
    The run completed, and ``CI_CHECK_NAME`` in ITS OWN check suite
    concluded ``success`` / anything else.
``no-check``
    The run completed without that check: cancelled before it existed,
    typically superseded by a newer push to main.
``unreadable``
    GitHub gave no answer. A failed read is retried with backoff, then
    waited past -- an unanswered question is never a verdict -- for at
    most ``--unreadable`` seconds in a row; refused outright (HTTP 401,
    403 that is not a rate limit, 404) it is a verdict at once, naming the
    path, since waiting cannot fix a wrong token or workflow name.

A ``red`` or ``no-check`` verdict also names a NEWER main push run of
the CI workflow that has not completed, when there is one
(``newer_url``). Rerunning this commit's CI then is not safe: a workflow
whose main pushes share one concurrency group holds one PENDING run, and
a rerun queued on the older commit can cancel the newer head's.

``--min-attempt N`` treats a completed run whose ``run_attempt`` is below
N as not yet re-run, so a caller that just reran CI does not read the
previous attempt's result back.

Usage::

    REPO=owner/name SHA=<commit> python3 scripts/verify-ci.py \\
        [--max-minutes M] [--min-attempt N] [--out FILE]

``CI_CHECK_NAME`` (default ``CI passed``) and ``CI_WORKFLOW`` (default
``ci.yml``) come from standard.mk. Exits 0 on ``green`` and 1 on every
other verdict, after a ``::error::`` line naming it. ``--out`` appends
``verdict=``, ``run_id=``, ``run_attempt=``, ``run_url=`` and
``newer_url=`` lines to FILE
for a caller to read. ``gh`` needs ``GH_TOKEN`` with ``actions: read`` and
``checks: read``.

Examples
--------
The decision, over a fake API and a clock that moves only when it sleeps:

>>> run = {"id": 7, "status": "completed", "conclusion": "success",
...     "run_attempt": 1, "check_suite_id": 3,
...     "html_url": "https://example.invalid/runs/7"}
>>> def api(path: str) -> Any:
...     if "/check-suites/" in path:
...         return {"total_count": 1, "check_runs": [{"name": "CI passed",
...             "status": "completed", "conclusion": "success"}]}
...     return {"total_count": 1, "workflow_runs": [run]}
>>> verify("o/r", "abc", api=api, say=lambda m: None).verdict
'green'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from typing import Any, Callable, NamedTuple, Optional

#: Seconds between polls.
INTERVAL = 20
#: Seconds a run may take to APPEAR: over a hundred times the measured
#: 3-5 s, and short enough that a commit main never ran fails in minutes.
APPEAR = 10 * 60
#: Seconds of unanswered reads in a row before that is the verdict.
UNREADABLE = 15 * 60
#: Seconds between the attempts of ONE read (5xx, network, rate limit).
#: ``gh api`` retries nothing itself.
BACKOFF = (5, 15, 45)

Api = Callable[[str], Any]


class Unreadable(Exception):
    """A read GitHub did not answer; waited past, never a verdict."""


class Refused(Exception):
    """A read GitHub refused outright; waiting cannot change it."""


class Verdict(NamedTuple):
    """What became of CI for the SHA, and the run that says so."""

    verdict: str
    message: str
    run_id: str = ""
    run_attempt: str = ""
    run_url: str = ""
    newer_url: str = ""


def _permanent(err: str) -> bool:
    """True for an HTTP refusal that no amount of waiting can change."""
    m = re.search(r"HTTP (\d{3})", err)
    if not m:
        return False
    code = int(m.group(1))
    if code == 403:
        return "rate limit" not in err.lower()
    return code in (401, 404, 422)


def gh_api(
    path: str,
    *,
    run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] = print,
) -> Any:
    """GET one REST path through ``gh api``, retrying what may recover.

    Each failed attempt is printed. A refusal (:func:`_permanent`, or gh
    exit 4: no token) raises :class:`Refused` at once; anything else -- a
    5xx, a rate limit, no network, a reply that is not JSON -- is retried
    after each :data:`BACKOFF` pause and then raises :class:`Unreadable`.
    """
    err = ""
    for pause in (*BACKOFF, None):
        r = run(["gh", "api", path], capture_output=True, text=True)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except ValueError as e:
                err = f"not JSON: {e}"
        else:
            err = r.stderr.strip() or f"gh exited {r.returncode}"
            # gh exits 4 when it has no token at all ("set the GH_TOKEN
            # environment variable"): no HTTP code, and no wait fixes it.
            if r.returncode == 4 or _permanent(err):
                raise Refused(f"gh api {path}: {err}")
        if pause is None:
            break
        say(f"  gh api {path}: {err}; retrying in {pause}s")
        sleep(pause)
    raise Unreadable(f"gh api {path}: {err} ({len(BACKOFF) + 1} attempts)")


def newest_run(
    repo: str, sha: str, workflow: str, api: Api
) -> Optional[dict[str, Any]]:
    """The newest push run of ``workflow`` on main for ``sha``, or None.

    Newest first is the API's order; a re-run keeps its run id and bumps
    ``run_attempt``.
    """
    runs: list[dict[str, Any]] = api(
        f"repos/{repo}/actions/workflows/{workflow}/runs"
        f"?head_sha={sha}&branch=main&event=push&per_page=10"
    ).get("workflow_runs", [])
    return runs[0] if runs else None


def certifying_check(
    repo: str, run: dict[str, Any], check: str, api: Api
) -> Optional[dict[str, Any]]:
    """``check`` in ``run``'s own check suite, or None.

    Read from the run's suite rather than every check on the commit, so
    the verdict belongs to the run whose status was waited on.
    """
    name = urllib.parse.quote(check)
    found: list[dict[str, Any]] = api(
        f"repos/{repo}/check-suites/{run['check_suite_id']}/check-runs"
        f"?check_name={name}"
    ).get("check_runs", [])
    return found[0] if found else None


def newer_live_run(
    repo: str, run: dict[str, Any], workflow: str, api: Api
) -> Optional[dict[str, Any]]:
    """A main push run of ``workflow`` newer than ``run``, not completed.

    Newer is a larger run id (ids only grow); a rerun keeps its id, so
    ``run`` itself never counts. The API lists newest first, so the first
    page holds every run that can be newer and still alive.
    """
    runs: list[dict[str, Any]] = api(
        f"repos/{repo}/actions/workflows/{workflow}/runs"
        f"?branch=main&event=push&per_page=20"
    ).get("workflow_runs", [])
    for r in runs:
        if r.get("id", 0) > run["id"] and r.get("status") != "completed":
            return r
    return None


def verify(
    repo: str,
    sha: str,
    *,
    check: str = "CI passed",
    workflow: str = "ci.yml",
    max_minutes: Optional[float] = None,
    min_attempt: int = 1,
    api: Api = gh_api,
    interval: float = INTERVAL,
    appear: float = APPEAR,
    unreadable: float = UNREADABLE,
    say: Callable[[str], None] = print,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Verdict:
    """Wait while CI for ``sha`` is alive; return what became of it.

    Parameters
    ----------
    repo, sha
        ``owner/name`` and the commit.
    check, workflow
        The aggregate check that certifies a tree, and the CI workflow's
        file name.
    max_minutes
        Stop waiting on a live run after this long (verdict ``alive``).
        None waits as long as it is alive: the caller's own timeout is the
        cap.
    min_attempt
        A completed run on an earlier attempt is still waited for.
    api, interval, appear, unreadable, say, now, sleep
        The REST reader and the clock, injected so a test drives every
        branch without GitHub or real time.
    """
    start = now()
    unread_since: Optional[float] = None
    last: Optional[dict[str, Any]] = None
    seen = ""

    def ident(run: Optional[dict[str, Any]]) -> dict[str, str]:
        if run is None:
            return {}
        return {
            "run_id": str(run.get("id", "")),
            "run_attempt": str(run.get("run_attempt", "")),
            "run_url": str(run.get("html_url", "")),
        }

    while True:
        state = ""
        try:
            run = newest_run(repo, sha, workflow, api)
            last = run
            if run is None:
                state = "absent"
            elif run["status"] != "completed":
                state = str(run["status"])
            elif int(run.get("run_attempt") or 1) < min_attempt:
                state = f"attempt {run.get('run_attempt')}, not yet re-run"
            else:
                url = run["html_url"]
                got = certifying_check(repo, run, check, api)
                if got is not None and got.get("conclusion") == "success":
                    return Verdict(
                        "green", f"'{check}' is green on {url}", **ident(run)
                    )
                newer = newer_live_run(repo, run, workflow, api)
                busy = ""
                if newer is not None:
                    busy = (
                        f" A newer main CI run, {newer.get('html_url')}, is "
                        f"{newer.get('status')}: rerunning this one now "
                        f"could cancel it, so let it finish first."
                    )
                extra = {
                    **ident(run),
                    "newer_url": str(newer.get("html_url", ""))
                    if newer
                    else "",
                }
                if got is None:
                    return Verdict(
                        "no-check",
                        f"CI run {url} for {sha} completed "
                        f"'{run.get('conclusion')}' with no '{check}' "
                        f"check: it never reached it (cancelled, or "
                        f"superseded by a newer push to main). Nothing "
                        f"certified this commit.{busy}",
                        **extra,
                    )
                return Verdict(
                    "red",
                    f"'{check}' concluded '{got.get('conclusion')}' on CI "
                    f"run {url} (run concluded '{run.get('conclusion')}')."
                    f"{busy}",
                    **extra,
                )
            unread_since = None
        except Refused as e:
            return Verdict(
                "unreadable",
                f"GitHub refused a read, so CI for {sha} cannot be judged: "
                f"{e}",
                **ident(last),
            )
        except Unreadable as e:
            if unread_since is None:
                unread_since = now()
            say(
                f"No answer from GitHub ({e}); waiting -- an unanswered "
                f"read is never a verdict."
            )
            if now() - unread_since >= unreadable:
                return Verdict(
                    "unreadable",
                    f"GitHub has not answered for {unreadable / 60:.0f} "
                    f"min, so CI for {sha} cannot be judged: {e}",
                    **ident(last),
                )

        elapsed = now() - start
        if state == "absent" and elapsed >= appear:
            return Verdict(
                "no-run",
                f"No {workflow} push run on main for {sha} appeared in "
                f"{appear / 60:.0f} min. A push registers its run within "
                f"seconds, so main never ran CI on this commit: tag one "
                f"it did.",
            )
        if max_minutes is not None and elapsed >= max_minutes * 60:
            what = state or "unanswered"
            return Verdict(
                "unreadable" if not state else "alive",
                f"CI for {sha} is still {what} after {max_minutes:g} min "
                f"(the cap this wait was given).",
                **ident(last),
            )
        if state and state != seen:
            if state == "absent":
                say(f"No {workflow} run for {sha} yet; waiting for it.")
            else:
                cap = (
                    f"the cap is {max_minutes:g} min"
                    if max_minutes is not None
                    else "this job's timeout-minutes is the only cap"
                )
                say(
                    f"CI run {last and last.get('html_url')} is {state} "
                    f"({elapsed / 60:.0f} min so far); waiting while it is "
                    f"alive -- {cap}."
                )
            seen = state
        sleep(interval)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--max-minutes", type=float, default=None)
    ap.add_argument("--min-attempt", type=int, default=1)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    repo, sha = os.environ.get("REPO", ""), os.environ.get("SHA", "")
    if not repo or not sha:
        # An empty head_sha= filters nothing: the newest run of ANY commit
        # would answer for this one.
        print("::error::verify-ci.py needs REPO=owner/name and SHA=<commit>")
        return 2
    v = verify(
        repo,
        sha,
        check=os.environ.get("CI_CHECK_NAME") or "CI passed",
        workflow=os.environ.get("CI_WORKFLOW") or "ci.yml",
        max_minutes=a.max_minutes,
        min_attempt=a.min_attempt,
    )
    if v.verdict == "green":
        print(f"{v.message} -- proceeding.")
    else:
        print(f"::error::[{v.verdict}] {v.message}")
    if a.out:
        with open(a.out, "a", encoding="utf-8") as f:
            for key in (
                "verdict",
                "run_id",
                "run_attempt",
                "run_url",
                "newer_url",
            ):
                f.write(f"{key}={getattr(v, key)}\n")
    return 0 if v.verdict == "green" else 1


if __name__ == "__main__":
    sys.exit(main())
