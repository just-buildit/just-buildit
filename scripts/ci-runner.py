#!/usr/bin/env python3
"""Route a CI leg to a free self-hosted runner, and keep fork PRs off one.

VENDORED VERBATIM from https://just-buildit.github.io/scripts/ci-runner.py
and checked by ``standard-check`` like ``standard.mk`` itself. Never edit it
in place; change canonical and re-vendor. Two make targets run it:
``make ci-runner`` (``pick``) and ``make self-hosted-check`` (``check``),
which ``make lint`` runs. Why it exists: just-buildit.github.io#203.

Why
---
On the free plan, GitHub-hosted capacity turns CI red with no failing test:
a macOS leg cancelled at its time limit, or never assigned at all. An org
runner on a machine of our own takes that load, but GitHub fixes a job's
labels when it is queued and never reroutes it, so the choice of runner has
to be made BEFORE the job is queued, by a planner job, from what is free at
that moment. And the repositories are public: a fork's pull request that
reaches a self-hosted runner runs a stranger's code on a home machine.

``pick``: the runner each leg gets
-----------------------------------
A filter over a planner's ``$GITHUB_OUTPUT`` lines. Every ``name=value``
line whose value is a JSON object must be a matrix in ``include`` form, and
each of its legs gains a ``runs_on``: the leg's hosted label (the first of
``--key``'s keys the leg has, ``runs_on`` then ``os`` by default) or, for
as many legs as there are idle matching runners, that pool's self-hosted
labels. Every other ``name=value`` line passes through unchanged; any
other line (a ``name<<DELIM`` block) is refused, and so is a leg whose
label is not a GitHub-hosted image (:data:`HOSTED`). A job then reads
``runs-on: ${{ matrix.runs_on }}``. A leg goes to a pool only when ALL of
these hold:

1. the run is not fork-driven: not a fork's pull request (every event whose
   payload is a pull request; a head repository that is gone counts as a
   fork), not a ``workflow_run`` whose triggering run came from another
   repository, and not a comment on a pull request;
2. the repository opted in: the pool's variable (``JB_SELF_HOSTED_MACOS``)
   is ``true``. The workflow passes it in from ``vars.``, so it is a
   repository or organization VARIABLE, not a secret;
3. a runner of the pool is online, idle, and in a runner group this
   repository may use (public repositories need "Allow public
   repositories"; a group restricted to selected workflows must list this
   one, ``GITHUB_WORKFLOW_REF``). That is read from the org's runner API
   with ``JB_RUNNER_READ_TOKEN``, a fine-grained token with the org
   permission "Self-hosted runners: read". ``GITHUB_TOKEN`` cannot read it:
   its permissions are repository-scoped, and the endpoint is
   organization-only;
4. this repository's jobs already queued for the pool (read with
   ``GITHUB_TOKEN``, ``actions: read``) leave an idle runner over: each
   will take the next one, so they are counted against the idle ones.

A runner group restricted to selected workflows counts only for the
workflow named by ``--workflow`` (``CI_RUNNER_WORKFLOW``), and only when
that is the run's own workflow: GitHub grants such a group to jobs defined
directly in a listed workflow, and in a reusable workflow
``GITHUB_WORKFLOW_REF`` names the CALLER, so a callee's jobs never match.
Entries are matched exactly, in full (``@refs/heads/main``) or ``@main``
form; GitHub documents no wildcards there.

:data:`HOSTED` trusts runner LABELS: a self-hosted runner registered with
a hosted-looking label (``macos-latest``) would satisfy a "hosted" leg.
Only org admins register runners, and the org's Mac host registers only
``self-hosted, macOS, ARM64``; that registration is the control, not this
script.

Anything else -- no token, an API error, a busy or offline runner, a group
this repository cannot use -- keeps the hosted label. It fails toward a
hosted leg, never toward one queued for a runner that will not take it. One
self-hosted runner serves one job, so a pool gets at most as many legs as
it has idle runners, in the order the lines and legs arrive: list the leg
that most needs it first. It decides at plan time: another repository's
jobs, or a run planned in the same moment, can still take the runner
first, and then the leg waits for it.

``check``: no fork PR reaches a self-hosted runner
---------------------------------------------------
Each workflow job whose ``runs-on`` can resolve to a self-hosted runner --
any label that is not a GitHub-hosted image (a runner must carry all of a
job's labels, so ``[macOS, ARM64]`` can only be ours), a runner ``group``,
or a value it cannot resolve -- must be gated so that a fork never selects
it, on a pull request event, ``workflow_run`` or ``issue_comment``.
Accepted:

* ``runs-on: ${{ matrix.runs_on }}`` over a matrix read with ``fromJSON``
  from a job output of a step in which ``make ci-runner`` is the one
  command writing ``$GITHUB_OUTPUT`` (a heredoc, quote or comment is not a
  command). ``pick`` never gives a fork-driven run a self-hosted label;
* a job ``if:`` that is FALSE for a fork's pull request on every pull
  request event the workflow can run on, whatever else is unknown, for
  example ``github.event.pull_request.head.repo.full_name ==
  github.repository``, or ``github.event_name != 'pull_request' && ... ||``
  that comparison. It is evaluated, not matched: GitHub's loose equality and
  three-valued unknowns, so ``head.repo.fork == false`` -- TRUE when the
  fork was deleted, because null equals false -- is refused;
* a workflow that no pull request event can start (``workflow_call`` can:
  its event is the caller's).

A literal, a static matrix and ``fromJSON`` of literals are resolved to
their labels. Any other source -- an input, a variable, another planner's
output -- is refused unless the job is gated, because it can say anything.
Workflow files are read with a YAML subset parser (stdlib only, like every
canonical script); a file it cannot read is refused, never passed.

The gate guards against a maintainer's mistake. It is not what stops a
malicious fork: a ``pull_request`` run uses the workflow files of the
fork's own merge commit, so a fork can edit them. That is the job of the
runner group's repository access and the fork-PR approval policy.

Examples
--------
>>> legs = [{"os": "macos-latest"}, {"os": "macos-latest"},
...         {"os": "ubuntu-latest"}]
>>> [x["runs_on"] for x in allocate(legs, ("os",), {POOLS[0]: 1})]
[['self-hosted', 'macOS', 'ARM64'], 'macos-latest', 'ubuntu-latest']
>>> truth(parse_expr("github.event.pull_request.head.repo.full_name"
...                  " == github.repository"), scenario("pull_request", True))
False
>>> truth(parse_expr("!github.event.pull_request.head.repo.fork"),
...       scenario("pull_request", deleted=True))
True
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import sys
import urllib.request
from typing import Any, Callable, Iterable, NamedTuple


class Pool(NamedTuple):
    """Self-hosted runners that can stand in for some hosted labels."""

    #: What the log calls it.
    name: str
    #: The hosted labels this pool replaces.
    hosted: "re.Pattern[str]"
    #: The labels a job asks for to reach it.
    labels: "tuple[str, ...]"
    #: The variable that opts a repository in (``true``).
    opt_in: str


#: The org's self-hosted pools. macOS: a Mac running each job in a
#: throwaway Tart VM (just-bashit's ``jb-runner-host``). ``macos-13`` and
#: the ``-intel`` / ``-large`` images are x64, so they stay hosted.
POOLS = (
    Pool(
        "macOS ARM64",
        re.compile(r"^macos-(latest|1[4-9]|[2-9][0-9])(-xlarge)?$"),
        ("self-hosted", "macOS", "ARM64"),
        "JB_SELF_HOSTED_MACOS",
    ),
)

#: The secret holding a token that can read the org's runners.
TOKEN_ENV = "JB_RUNNER_READ_TOKEN"

#: The events whose payload is a pull request, whose code a run may build.
PR_EVENTS = (
    "pull_request",
    "pull_request_target",
    "pull_request_review",
    "pull_request_review_comment",
)

#: The events that run this repository's workflow with code or a request
#: a fork can supply: a pull request's, a ``workflow_run`` a fork's pull
#: request triggered, and a comment on a pull request.
FORK_EVENTS = PR_EVENTS + ("workflow_run", "issue_comment")

#: GitHub-hosted image labels, from "GitHub-hosted runners" (standard and
#: larger runners). A runner is matched by ALL of a job's labels, and no
#: hosted image carries any other label, so a job asking for anything else
#: -- ``macOS``, ``ARM64``, a name of our own -- can only ever run on a
#: self-hosted runner, whether or not it says ``self-hosted``.
HOSTED = re.compile(
    r"^(ubuntu-(latest|slim|\d{2}\.\d{2})(-arm)?"
    r"|windows-(latest|\d{4}|11-arm)(-vs\d{4})?"
    r"|macos-(latest|\d{2})(-(large|xlarge|intel))?)$",
    re.I,
)

#: Job statuses that will still take a runner.
WAITING = ("queued", "waiting", "requested", "pending")


def hosted(label: Any) -> bool:
    """Whether *label* names a GitHub-hosted image.

    >>> [hosted(x) for x in ("macos-latest", "ubuntu-24.04-arm", "macOS")]
    [True, True, False]
    """
    return isinstance(label, str) and bool(HOSTED.match(label.strip()))


# ---------------------------------------------------------------- pick


def trusted(env: "dict[str, str]") -> "tuple[bool, str]":
    """Whether this run may use a self-hosted runner, and why not.

    No for a fork's pull request -- any :data:`PR_EVENTS` event whose
    head repository is not this one, or is gone -- for a ``workflow_run``
    whose triggering run's head repository is not this one, and for a
    comment on a pull request. Outside Actions, or with an event file it
    cannot read, it says no.
    """
    event, repo = (
        env.get("GITHUB_EVENT_NAME", ""),
        env.get("GITHUB_REPOSITORY", ""),
    )
    if not event or not repo:
        return False, "not a GitHub Actions run"
    if event not in FORK_EVENTS:
        return True, ""
    try:
        with open(env.get("GITHUB_EVENT_PATH", ""), encoding="utf-8") as f:
            payload = json.load(f)
        if event == "issue_comment":
            if payload["issue"].get("pull_request"):
                return False, "a comment on a pull request"
            return True, ""
        if event == "workflow_run":
            head = payload["workflow_run"]["head_repository"]
        else:
            head = payload["pull_request"]["head"]["repo"]
        full = head["full_name"] if head else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return False, f"cannot read the {event} event ({e})"
    if not full or full.lower() != repo.lower():
        return False, f"a {event} from {full or 'a deleted fork'}"
    return True, ""


Fetch = Callable[[str], Any]


def http_fetch(api: str, token: str) -> Fetch:
    """A GET of the GitHub API, JSON-decoded; raises on any failure."""

    def get(path: str) -> Any:
        req = urllib.request.Request(
            api.rstrip("/") + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)

    return get


def _paged(fetch: Fetch, path: str, key: str) -> "list[dict]":
    out: "list[dict]" = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        got = fetch(f"{path}{sep}per_page=100&page={page}")[key]
        out += got
        if len(got) < 100:
            return out
        page += 1


def _workflow_refs(ref: str) -> "list[str]":
    """*ref* (``GITHUB_WORKFLOW_REF``) as a runner group may list it: as
    given, and with a branch or tag ref shortened (``@main``)."""
    ref = ref.lower()
    path, _, at = ref.partition("@")
    out = [ref]
    for pre in ("refs/heads/", "refs/tags/"):
        if at.startswith(pre):
            out.append(f"{path}@{at[len(pre) :]}")
    return out


def idle(
    fetch: Fetch, org: str, repo: str, private: bool, workflow_ref: str = ""
) -> "dict[Pool, int]":
    """Idle runners of each pool in a group *repo* may use.

    A group restricted to selected workflows is usable only when it lists
    *workflow_ref* exactly, in full or ``@branch`` form; an empty
    *workflow_ref* (no ``--workflow``, or a reusable workflow's run) matches
    no such group. On a pull request the ref is ``refs/pull/N/merge``, so a
    group pinned to ``main`` is not counted there. Raises on any API
    failure.
    """
    usable = set()
    for g in _paged(
        fetch, f"/orgs/{org}/actions/runner-groups", "runner_groups"
    ):
        if g.get("restricted_to_workflows"):
            mine = _workflow_refs(workflow_ref) if workflow_ref else []
            allowed = [
                str(w).lower() for w in g.get("selected_workflows") or []
            ]
            if not set(mine) & set(allowed):
                continue
        if not private and not g.get("allows_public_repositories"):
            continue
        vis = g.get("visibility")
        if vis == "private" and not private:
            continue
        if vis == "selected":
            repos = _paged(
                fetch,
                f"/orgs/{org}/actions/runner-groups/{g['id']}/repositories",
                "repositories",
            )
            if repo.lower() not in {r["full_name"].lower() for r in repos}:
                continue
        elif vis not in ("all", "private"):
            continue
        usable.add(g["id"])
    counts = {p: 0 for p in POOLS}
    for r in _paged(fetch, f"/orgs/{org}/actions/runners", "runners"):
        if r.get("runner_group_id") not in usable:
            continue
        if r.get("status") != "online" or r.get("busy") is not False:
            continue
        have = {str(x.get("name", "")).lower() for x in r.get("labels", [])}
        for p in POOLS:
            if {x.lower() for x in p.labels} <= have:
                counts[p] += 1
    return counts


def queued(fetch: Fetch, repo: str) -> "dict[Pool, int]":
    """This repository's jobs already waiting for each pool's runners.

    Each will take the next idle runner of its pool, so the picker counts
    them against the idle ones. A job already running is not counted: its
    runner is busy, and :func:`idle` has left it out. Read with the run's
    ``GITHUB_TOKEN`` (``actions: read``); raises on any API failure.
    """
    runs: "dict[Any, dict]" = {}
    for status in ("queued", "in_progress"):
        for r in _paged(
            fetch,
            f"/repos/{repo}/actions/runs?status={status}",
            "workflow_runs",
        ):
            runs[r["id"]] = r
    counts = {p: 0 for p in POOLS}
    for rid in runs:
        for j in _paged(
            fetch, f"/repos/{repo}/actions/runs/{rid}/jobs", "jobs"
        ):
            if j.get("status") not in WAITING:
                continue
            have = {str(x).lower() for x in j.get("labels") or []}
            for p in POOLS:
                if {x.lower() for x in p.labels} <= have:
                    counts[p] += 1
    return counts


def pool_of(label: str) -> "Pool | None":
    for p in POOLS:
        if p.hosted.match(label):
            return p
    return None


def allocate(
    legs: "list[dict]", keys: "Iterable[str]", free: "dict[Pool, int]"
) -> "list[dict]":
    """Each leg with a ``runs_on``; spends *free* in leg order.

    A leg's hosted label is the value of the first of *keys* it has, and
    must be a GitHub-hosted image (:data:`HOSTED`): anything else -- not
    only ``self-hosted`` but ``macOS`` -- can only be met by a self-hosted
    runner, and would carry one past the fork check.
    """
    keys = tuple(keys)
    out = []
    for leg in legs:
        if not isinstance(leg, dict):
            raise ValueError(f"a matrix leg is not an object: {leg!r}")
        label = next((leg[k] for k in keys if k in leg), None)
        if not isinstance(label, str) or not label:
            raise ValueError(f"a leg names no hosted label in {keys}: {leg}")
        if not hosted(label):
            raise ValueError(f"a leg's label is not a hosted image: {label}")
        p = pool_of(label)
        runs_on: "str | list[str]" = label
        if p is not None and free.get(p, 0) > 0:
            free[p] -= 1
            runs_on = list(p.labels)
        out.append({**leg, "runs_on": runs_on})
    return out


def own_workflow_ref(env: "dict[str, str]", workflow: str) -> str:
    """``GITHUB_WORKFLOW_REF`` if it names *workflow* in this repository,
    else ``""``: a reusable workflow's run carries its caller's ref."""
    ref = env.get("GITHUB_WORKFLOW_REF", "")
    want = f"{env.get('GITHUB_REPOSITORY', '')}/{workflow}".lower()
    if not workflow or ref.partition("@")[0].lower() != want:
        return ""
    return ref


def pick(
    lines: "list[str]",
    keys: "tuple[str, ...]",
    env: "dict[str, str]",
    fetch: "Fetch | None" = None,
    workflow: str = "",
) -> "tuple[list[str], list[str]]":
    """The planner lines with every matrix leg given a ``runs_on``.

    Returns the output lines and the log. Raises ``ValueError`` on input
    that is not a planner's output: no lines, or a JSON object that is not
    an ``include`` matrix.
    """
    if not lines:
        raise ValueError("no planner output on stdin")
    parsed: "list[tuple[str, Any]]" = []
    wanted = set()
    for line in lines:
        name, sep, value = line.partition("=")
        # One `name=value` per line. A `name<<DELIM` block would pass a
        # multi-line value through untouched, matrix and all.
        if not sep or not re.fullmatch(r"[A-Za-z_][\w-]*", name):
            raise ValueError(f"not a name=value output line: {line[:60]}")
        m = None
        try:
            m = json.loads(value) if value.strip() else None
        except ValueError:
            m = None  # plain text: passes through, as GitHub reads it
        if m is not None:
            # Any JSON value -- an array, a string, a number -- could be
            # read with fromJSON somewhere; only a matrix is decided here.
            if (
                not isinstance(m, dict)
                or set(m) != {"include"}
                or not isinstance(m["include"], list)
            ):
                raise ValueError(
                    f"{name}: JSON that is not a matrix in include form "
                    f"({value[:60]})"
                )
            for leg in m["include"]:
                for k in keys:
                    if isinstance(leg, dict) and k in leg:
                        p = pool_of(str(leg[k]))
                        if p is not None:
                            wanted.add(p)
                        break
        parsed.append((line, m))

    log: "list[str]" = []
    free = {p: 0 for p in POOLS}
    ok, why = trusted(env)
    asking = [p for p in POOLS if p in wanted]
    for p in list(asking):
        if not ok:
            log.append(f"{p.name}: hosted -- {why}")
        elif env.get(p.opt_in, "").strip().lower() != "true":
            log.append(f"{p.name}: hosted -- {p.opt_in} is not 'true'")
        elif not env.get(TOKEN_ENV):
            log.append(f"{p.name}: hosted -- no {TOKEN_ENV}")
        elif not env.get("GITHUB_TOKEN"):
            log.append(f"{p.name}: hosted -- no GITHUB_TOKEN for the queue")
        else:
            continue
        asking.remove(p)
    if asking:
        repo = env["GITHUB_REPOSITORY"]
        api = env.get("GITHUB_API_URL", "https://api.github.com")
        org_fetch = fetch or http_fetch(api, env[TOKEN_ENV])
        repo_fetch = fetch or http_fetch(api, env["GITHUB_TOKEN"])
        try:
            counts = idle(
                org_fetch,
                repo.split("/")[0],
                repo,
                _private(env),
                own_workflow_ref(env, workflow),
            )
            waiting = queued(repo_fetch, repo)
        except Exception as e:  # noqa: BLE001 -- any failure means hosted
            for p in asking:
                log.append(f"{p.name}: hosted -- runner API: {e}")
            asking = []
        else:
            for p in asking:
                free[p] = max(0, counts[p] - waiting[p])
                if waiting[p]:
                    log.append(
                        f"{p.name}: {waiting[p]} job(s) already queued for "
                        f"{counts[p]} idle runner(s)"
                    )

    out = []
    total = {p: [0, 0] for p in asking}
    for line, m in parsed:
        if not isinstance(m, dict):
            out.append(line)
            continue
        name = line.partition("=")[0]
        legs = allocate(m["include"], keys, free)
        for was, leg in zip(m["include"], legs):
            p = pool_of(str(next(was[k] for k in keys if k in was)))
            if p in total:
                total[p][1] += 1
                total[p][0] += isinstance(leg["runs_on"], list)
        out.append(f"{name}=" + json.dumps({"include": legs}))
    for p, (n, of) in total.items():
        log.append(f"{p.name}: {n} of {of} leg(s) self-hosted")
    return out, log


def _private(env: "dict[str, str]") -> bool:
    """Whether the repository is private, from the event; False if unknown.

    Unknown counts as public, which needs the stricter group setting.
    """
    try:
        with open(env.get("GITHUB_EVENT_PATH", ""), encoding="utf-8") as f:
            return json.load(f)["repository"]["private"] is True
    except (OSError, ValueError, KeyError, TypeError):
        return False


# ------------------------------------------------- a YAML subset reader


class YamlError(ValueError):
    pass


_KEY = re.compile(
    r"""^(?P<key>"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'"""
    r"""|[^\s'"{\[#&*!|>%@`-][^:#]*?|-[^\s:#][^:#]*?)\s*:(?=\s|$)"""
)


def _strip_comment(s: str) -> str:
    """*s* without a trailing ``# comment``, respecting quoted scalars."""
    quote = ""
    prev = " "
    for i, c in enumerate(s):
        if quote:
            if c == quote:
                quote = ""
        elif c in "'\"" and prev in " \t[{,:":
            quote = c
        elif c == "#" and prev in " \t":
            return s[:i].rstrip()
        prev = c
    return s.rstrip()


def _unquote(s: str) -> str:
    if s.startswith("'"):
        if not s.endswith("'") or len(s) < 2:
            raise YamlError(f"unterminated quote: {s}")
        return s[1:-1].replace("''", "'")
    if s.startswith('"'):
        if not s.endswith('"') or len(s) < 2:
            raise YamlError(f"unterminated quote: {s}")
        try:
            return json.loads(s.replace("\\/", "/"))
        except ValueError as e:
            raise YamlError(f"bad double-quoted scalar {s}: {e}") from e
    return s


def _scalar(s: str) -> "str | None":
    s = s.strip()
    if s[:1] in ("&", "*", "!"):
        raise YamlError(f"anchors, aliases and tags are not read: {s}")
    if s in ("", "~", "null"):
        return None
    return _unquote(s)


class _Flow:
    """A flow collection: ``[a, b]``, ``{k: v}``, nested."""

    def __init__(self, s: str) -> None:
        self.s, self.i = s, 0

    def ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t\n":
            self.i += 1

    def node(self) -> Any:
        self.ws()
        c = self.s[self.i : self.i + 1]
        if c == "[":
            self.i += 1
            out = []
            while True:
                self.ws()
                if self.s[self.i : self.i + 1] == "]":
                    self.i += 1
                    return out
                out.append(self.node())
                self.ws()
                if self.s[self.i : self.i + 1] == ",":
                    self.i += 1
        if c == "{":
            self.i += 1
            d: "dict[str, Any]" = {}
            while True:
                self.ws()
                if self.s[self.i : self.i + 1] == "}":
                    self.i += 1
                    return d
                k = self.node()
                self.ws()
                v = None
                if self.s[self.i : self.i + 1] == ":":
                    self.i += 1
                    v = self.node()
                d[str(k)] = v
                self.ws()
                if self.s[self.i : self.i + 1] == ",":
                    self.i += 1
        if c in ("'", '"'):
            j = self.i + 1
            while j < len(self.s):
                if self.s[j] == c:
                    if c == "'" and self.s[j + 1 : j + 2] == "'":
                        j += 2
                        continue
                    break
                if c == '"' and self.s[j] == "\\":
                    j += 1
                j += 1
            tok, self.i = self.s[self.i : j + 1], j + 1
            return _unquote(tok)
        if not c:
            raise YamlError(f"unterminated flow collection: {self.s}")
        j = self.i
        depth = 0
        while j < len(self.s):
            ch = self.s[j]
            if self.s.startswith("${{", j):
                depth += 1
                j += 3
                continue
            if depth and self.s.startswith("}}", j):
                depth -= 1
                j += 2
                continue
            if not depth and (
                ch in ",]}"
                or (ch == ":" and self.s[j + 1 : j + 2] in (" ", ""))
            ):
                break
            j += 1
        tok, self.i = self.s[self.i : j], j
        return _scalar(tok)


def _flow(s: str) -> Any:
    f = _Flow(s)
    v = f.node()
    f.ws()
    if f.i != len(f.s):
        raise YamlError(f"trailing text after a flow collection: {s}")
    return v


class Yaml:
    """The YAML a workflow file is written in: block and flow collections,
    plain, quoted and block scalars. Every scalar stays a string."""

    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")

    @staticmethod
    def indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def skip(self, i: int) -> int:
        while i < len(self.lines):
            t = self.lines[i].strip()
            if t and not t.startswith("#") and t != "---":
                break
            i += 1
        return i

    def doc(self) -> Any:
        node, i = self.block(0, 0)
        i = self.skip(i)
        if i < len(self.lines):
            raise YamlError(f"line {i + 1}: unexpected {self.lines[i]!r}")
        return node

    def block(self, i: int, min_ind: int) -> "tuple[Any, int]":
        i = self.skip(i)
        if i >= len(self.lines):
            return None, i
        line = self.lines[i]
        ind = self.indent(line)
        if ind < min_ind:
            return None, i
        text = line[ind:]
        if text == "-" or text.startswith("- "):
            return self.seq(i, ind)
        if _KEY.match(text):
            return self.mapping(i, ind)
        return self.inline(_strip_comment(text), i, ind - 1)

    def seq(self, i: int, ind: int) -> "tuple[list, int]":
        out = []
        while True:
            i = self.skip(i)
            if i >= len(self.lines):
                return out, i
            line = self.lines[i]
            if self.indent(line) != ind:
                return out, i
            text = line[ind:]
            if not (text == "-" or text.startswith("- ")):
                return out, i
            rest = text[1:].lstrip(" ")
            if not _strip_comment(rest):
                item, i = self.block(i + 1, ind + 1)
            elif rest[0] in "|>":
                item, i = self.block_scalar(_strip_comment(rest), i, ind)
            else:
                col = ind + len(text) - len(rest)
                self.lines[i] = " " * col + rest
                item, i = self.block(i, col)
            out.append(item)

    def mapping(self, i: int, ind: int) -> "tuple[dict, int]":
        out: "dict[str, Any]" = {}
        while True:
            i = self.skip(i)
            if i >= len(self.lines):
                return out, i
            line = self.lines[i]
            if self.indent(line) != ind:
                if self.indent(line) > ind:
                    raise YamlError(f"line {i + 1}: bad indent {line!r}")
                return out, i
            text = line[ind:]
            m = _KEY.match(text)
            if not m:
                return out, i
            key = _unquote(m.group("key").strip())
            if key in out:
                raise YamlError(f"line {i + 1}: duplicate key {key!r}")
            rest = _strip_comment(text[m.end() :].lstrip(" "))
            if not rest:
                j = self.skip(i + 1)
                nxt = self.lines[j] if j < len(self.lines) else ""
                n_ind = self.indent(nxt)
                if j < len(self.lines) and n_ind > ind:
                    out[key], i = self.block(j, ind + 1)
                elif (
                    j < len(self.lines)
                    and n_ind == ind
                    and (nxt[ind:] == "-" or nxt[ind:].startswith("- "))
                ):
                    out[key], i = self.seq(j, ind)
                else:
                    out[key], i = None, i + 1
            elif rest[0] in "|>":
                out[key], i = self.block_scalar(rest, i, ind)
            else:
                out[key], i = self.inline(rest, i, ind)

    def block_scalar(self, head: str, i: int, ind: int) -> "tuple[str, int]":
        m = re.match(r"^([|>])([+-]?)([1-9]?)([+-]?)$", head)
        if not m:
            raise YamlError(f"line {i + 1}: bad block scalar {head!r}")
        style, chomp = m.group(1), m.group(2) or m.group(4)
        body: "list[str]" = []
        j = i + 1
        content = int(m.group(3)) + ind if m.group(3) else -1
        while j < len(self.lines):
            ln = self.lines[j]
            if ln.strip():
                if self.indent(ln) <= ind:
                    break
                if content < 0:
                    content = self.indent(ln)
                if self.indent(ln) < content:
                    break
                body.append(ln[content:])
            else:
                body.append("")
            j += 1
        while body and not body[-1] and chomp != "+":
            body.pop()
        if style == "|":
            text = "\n".join(body)
        else:
            # Folding: a line break between two normal lines becomes a
            # space; one next to a more-indented line, or a blank, stays.
            text, prev = "", "blank"
            for b in body:
                if not b:
                    text += "\n"
                    prev = "blank"
                elif b.startswith(" ") or prev == "more":
                    text += ("" if prev == "blank" else "\n") + b
                    prev = "more" if b.startswith(" ") else "text"
                else:
                    text += ("" if prev == "blank" else " ") + b
                    prev = "text"
        if chomp != "-" and body:
            text += "\n"
        return text, j

    def inline(self, rest: str, i: int, ind: int) -> "tuple[Any, int]":
        j = i + 1
        if rest[0] in "[{" or rest[0] in "'\"":
            text = rest
            while True:
                try:
                    if rest[0] in "[{":
                        return _flow(text), j
                    return _unquote(text), j
                except YamlError:
                    if j >= len(self.lines) or (
                        self.lines[j].strip()
                        and self.indent(self.lines[j]) <= ind
                    ):
                        raise
                    text += " " + _strip_comment(self.lines[j].strip())
                    j += 1
        parts = [rest]
        while j < len(self.lines):
            ln = self.lines[j]
            if not ln.strip():
                j += 1
                continue
            if self.indent(ln) <= ind or ln.strip().startswith("#"):
                break
            parts.append(_strip_comment(ln.strip()))
            j += 1
        return _scalar(" ".join(parts)), j


def load_yaml(text: str) -> Any:
    """Parse *text*; raises :class:`YamlError` on what it cannot read."""
    return Yaml(text).doc()


# ------------------------------------------------- GitHub expressions


class Unknown:
    """A value the gate cannot know."""

    def __repr__(self) -> str:
        return "UNKNOWN"


UNKNOWN = Unknown()

_TOKEN = re.compile(
    r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>-?(?:0x[0-9a-fA-F]+|\d+\.?\d*"
    r"(?:[eE][+-]?\d+)?))|(?P<id>[A-Za-z_][A-Za-z0-9_-]*)"
    r"|(?P<op>==|!=|<=|>=|&&|\|\||[<>!().,\[\]*]))"
)


def _tokens(s: str) -> "list[tuple[str, str]]":
    out, i = [], 0
    while i < len(s):
        if not s[i:].strip():
            break
        m = _TOKEN.match(s, i)
        if not m:
            raise ValueError(f"cannot read expression at {s[i:]!r}")
        kind = m.lastgroup or ""
        out.append((kind, m.group(kind)))
        i = m.end()
    return out


def parse_expr(s: str) -> tuple:
    """A GitHub expression (no ``${{ }}``) as a small AST of tuples."""
    toks = _tokens(s)
    pos = [0]

    def peek() -> str:
        return toks[pos[0]][1] if pos[0] < len(toks) else ""

    def take(want: "str | None" = None) -> "tuple[str, str]":
        if pos[0] >= len(toks) or (want and toks[pos[0]][1] != want):
            raise ValueError(f"expected {want or 'more'} in {s!r}")
        pos[0] += 1
        return toks[pos[0] - 1]

    def primary() -> tuple:
        kind, v = take()
        if v == "(":
            e = orr()
            take(")")
            node = e
        elif v == "!":
            return ("not", primary())
        elif kind == "str":
            node = ("lit", v[1:-1].replace("''", "'"))
        elif kind == "num":
            node = ("lit", float(int(v, 16)) if "x" in v else float(v))
        elif kind == "id" and v in ("true", "false"):
            node = ("lit", v == "true")
        elif kind == "id" and v == "null":
            node = ("lit", None)
        elif kind == "id" and peek() == "(":
            take("(")
            args = []
            while peek() != ")":
                args.append(orr())
                if peek() == ",":
                    take(",")
            take(")")
            node = ("call", v.lower(), args)
        elif kind == "id":
            node = ("ctx", (v,))
        else:
            raise ValueError(f"unexpected {v!r} in {s!r}")
        while peek() in (".", "["):
            if take()[1] == ".":
                k, name = take()
                if node[0] == "ctx" and k == "id":
                    node = ("ctx", node[1] + (name,))
                else:
                    node = ("index", node, ("lit", name))
            else:
                idx = orr()
                take("]")
                if node[0] == "ctx" and idx[0] == "lit":
                    node = ("ctx", node[1] + (str(idx[1]),))
                else:
                    node = ("index", node, idx)
        return node

    def cmp_rel() -> tuple:
        e = primary()
        while peek() in ("<", "<=", ">", ">="):
            e = ("cmp", take()[1], e, primary())
        return e

    def cmp_eq() -> tuple:
        e = cmp_rel()
        while peek() in ("==", "!="):
            e = ("cmp", take()[1], e, cmp_rel())
        return e

    def andd() -> tuple:
        e = cmp_eq()
        while peek() == "&&":
            take()
            e = ("and", e, cmp_eq())
        return e

    def orr() -> tuple:
        e = andd()
        while peek() == "||":
            take()
            e = ("or", e, andd())
        return e

    tree = orr()
    if pos[0] != len(toks):
        raise ValueError(f"trailing tokens in {s!r}")
    return tree


def _truthy(v: Any) -> Any:
    if v is UNKNOWN:
        return UNKNOWN
    if v is None or v is False or v == "":
        return False
    if isinstance(v, float) and (v == 0 or math.isnan(v)):
        return False
    return True


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, float):
        return v
    if isinstance(v, str):
        if not v.strip():
            return 0.0
        try:
            return (
                float(int(v, 16)) if v.lower().startswith("0x") else float(v)
            )
        except ValueError:
            return math.nan
    return math.nan


def _compare(op: str, a: Any, b: Any) -> Any:
    """GitHub's loose comparison: case-insensitive strings, else numbers."""
    if a is UNKNOWN or b is UNKNOWN:
        return UNKNOWN
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        same = a is b
        return same if op == "==" else (not same if op == "!=" else False)
    x: Any
    y: Any
    if isinstance(a, str) and isinstance(b, str):
        x, y = a.lower(), b.lower()
    elif op in ("==", "!=") and type(a) is type(b):
        x, y = a, b
    else:
        x, y = _num(a), _num(b)
    nan = any(isinstance(v, float) and math.isnan(v) for v in (x, y))
    # Only the operator asked for: `null < null` must not be evaluated by
    # Python, which cannot order None.
    if op == "==":
        return not nan and x == y
    if op == "!=":
        return nan or x != y
    if nan:
        return False
    if op == "<":
        return x < y
    if op == "<=":
        return x <= y
    if op == ">":
        return x > y
    return x >= y


def _lookup(ctx: "dict[str, Any]", path: "tuple[str, ...]") -> Any:
    v: Any = ctx
    for k in path:
        if v is None or isinstance(v, (str, float, bool)):
            return None
        if not isinstance(v, dict) or k.lower() not in v:
            return UNKNOWN
        v = v[k.lower()]
    return v


def evaluate(node: tuple, ctx: "dict[str, Any]") -> Any:
    """*node*'s value in *ctx*, three-valued: UNKNOWN where it cannot know."""
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "ctx":
        return _lookup(ctx, node[1])
    if kind == "not":
        t = _truthy(evaluate(node[1], ctx))
        return UNKNOWN if t is UNKNOWN else not t
    if kind == "and":
        a = evaluate(node[1], ctx)
        ta = _truthy(a)
        if ta is False:
            return a
        b = evaluate(node[2], ctx)
        if ta is True:
            return b
        return False if _truthy(b) is False else UNKNOWN
    if kind == "or":
        a = evaluate(node[1], ctx)
        ta = _truthy(a)
        if ta is True:
            return a
        if ta is False:
            return evaluate(node[2], ctx)
        return UNKNOWN
    if kind == "cmp":
        return _compare(
            node[1], evaluate(node[2], ctx), evaluate(node[3], ctx)
        )
    if kind == "index":
        obj, key = evaluate(node[1], ctx), evaluate(node[2], ctx)
        if obj is UNKNOWN or key is UNKNOWN:
            return UNKNOWN
        return _lookup(obj, (str(key),)) if isinstance(obj, dict) else None
    if kind == "call":
        name, args = node[1], [evaluate(a, ctx) for a in node[2]]
        if name == "always":
            return True
        if any(a is UNKNOWN for a in args) or name not in (
            "contains",
            "startswith",
            "endswith",
        ):
            return UNKNOWN
        hay, needle = args[0], args[1]
        if name == "contains" and isinstance(hay, list):
            return any(_compare("==", x, needle) is True for x in hay)
        h, n = str(hay).lower(), str(needle).lower()
        return {
            "contains": n in h,
            "startswith": h.startswith(n),
            "endswith": h.endswith(n),
        }[name]
    raise ValueError(f"unknown node {kind}")


def truth(node: tuple, ctx: "dict[str, Any]") -> Any:
    return _truthy(evaluate(node, ctx))


#: Stand-ins: a repository, and a fork of it.
REPO, FORK = "owner/repo", "stranger/repo"


def scenario(
    event: str, deleted: bool, cause: str = "pull_request"
) -> "dict[str, Any]":
    """What a fork-driven run of *event* knows: the event, the repository,
    which of the payload's ``pull_request`` / ``workflow_run`` / ``issue``
    it carries, and a head repository that is a fork (or gone). For a
    ``workflow_run``, *cause* is the event that started the triggering run.
    Everything else is UNKNOWN."""
    head = None if deleted else {"full_name": FORK, "fork": True}
    payload: "dict[str, Any]" = {
        "pull_request": None,
        "workflow_run": None,
        "issue": None,
    }
    if event in PR_EVENTS:
        payload["pull_request"] = {"head": {"repo": head}}
    elif event == "workflow_run":
        payload["workflow_run"] = {
            "head_repository": head,
            "event": cause,
        }
    elif event == "issue_comment":
        payload["issue"] = {"pull_request": {"url": "pr"}}
    return {
        "github": {"event_name": event, "repository": REPO, "event": payload}
    }


def _expr_body(s: str) -> "str | None":
    """The expression inside a whole ``${{ }}``, or None if *s* is not one."""
    t = s.strip()
    if t.startswith("${{") and t.endswith("}}") and t.count("${{") == 1:
        return t[3:-2]
    return None


def fork_safe_if(cond: Any, events: "Iterable[str]") -> "tuple[bool, str]":
    """Whether a job ``if:`` is false for a fork's PR on every *event*."""
    if cond is None or str(cond).strip() == "":
        return False, "no if:"
    s = str(cond).strip()
    body = _expr_body(s)
    if body is None:
        if "${{" in s:
            return False, "if: mixes ${{ }} with text, so it is always true"
        body = s
    try:
        tree = parse_expr(body)
    except ValueError as e:
        return False, f"if: cannot be read ({e})"
    for ev in events:
        # A fork can start the triggering run through any pull request
        # event, so a workflow_run is tried as each of them.
        causes = PR_EVENTS if ev == "workflow_run" else ("",)
        for cause in causes:
            for deleted in (False, True):
                if truth(tree, scenario(ev, deleted, cause)) is not False:
                    who = "a deleted fork" if deleted else "a fork"
                    via = f" (via {cause})" if cause else ""
                    return False, f"if: can be true for {ev}{via} from {who}"
    return True, ""


# ------------------------------------------------------------- check


class Dynamic(Exception):
    """A runs-on value the gate cannot resolve to labels."""


class _Canon(NamedTuple):
    what: str  # "output" | "matrix" | "runs_on"


def _triggers(on: Any) -> "set[str]":
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on}
    return set()


class Workflow:
    def __init__(self, path: str, doc: Any) -> None:
        if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
            raise YamlError("no jobs: mapping")
        self.path, self.jobs, self.doc = path, doc["jobs"], doc
        on = doc.get("on", doc.get("true"))
        trig = _triggers(on)
        if "workflow_call" in trig:
            self.pr_events = list(FORK_EVENTS)
        else:
            self.pr_events = [e for e in FORK_EVENTS if e in trig]

    def canonical(self, job: str, out: str) -> bool:
        """Whether ``needs.<job>.outputs.<out>`` is ci-runner's output."""
        j = self.jobs.get(job)
        if not isinstance(j, dict) or not isinstance(j.get("outputs"), dict):
            return False
        body = _expr_body(str(j["outputs"].get(out) or ""))
        try:
            tree = parse_expr(body) if body is not None else None
        except ValueError:
            return False
        if not tree or tree[0] != "ctx" or len(tree[1]) != 4:
            return False
        root, sid, outputs, _ = tree[1]
        if root != "steps" or outputs != "outputs":
            return False
        steps = [x for x in j.get("steps") or [] if isinstance(x, dict)]
        for i, step in enumerate(steps):
            if step.get("id") == sid:
                return trusted_step(
                    step, steps[:i], j, self.doc, self.pr_events
                )
        return False

    def values(self, node: tuple, job: dict) -> "list[Any]":
        kind = node[0]
        if kind == "lit":
            return [node[1]]
        if kind == "and":
            return self.values(node[2], job)
        if kind == "or":
            return self.values(node[1], job) + self.values(node[2], job)
        if kind in ("cmp", "not"):
            return [True, False]
        if kind == "call" and node[1] == "fromjson" and len(node[2]) == 1:
            out = []
            for v in self.values(node[2][0], job):
                if isinstance(v, _Canon) and v.what == "output":
                    out.append(_Canon("matrix"))
                elif isinstance(v, str):
                    try:
                        out.append(json.loads(v))
                    except ValueError as e:
                        raise Dynamic(f"fromJSON of {v!r}: {e}") from e
                else:
                    raise Dynamic("fromJSON of a value it cannot read")
            return out
        if kind == "ctx":
            path = node[1]
            if path[0] == "matrix":
                return self.matrix(job, path[1:])
            if (
                path[0] == "needs"
                and len(path) == 4
                and path[2] == "outputs"
                and self.canonical(path[1], path[3])
            ):
                return [_Canon("output")]
            raise Dynamic(f"{'.'.join(path)} can name any runner")
        raise Dynamic("an expression it cannot resolve")

    def resolve(self, raw: Any, job: dict) -> "list[Any]":
        """Every value *raw* (a YAML value) can take.

        ci-runner's output is trusted only as a WHOLE matrix (``matrix:
        ${{ fromJSON(...) }}``); read into a list or a mapping -- an
        ``include:``, an axis -- its legs' other keys are a planner's, so it
        is unresolvable there.
        """
        if isinstance(raw, (list, dict)):
            items = raw if isinstance(raw, list) else list(raw.values())
            for x in items:
                if _has_canon(self.resolve(x, job)):
                    raise Dynamic(
                        "a ci-runner output inside a matrix, not the whole "
                        "matrix"
                    )
        if isinstance(raw, list):
            return [v for x in raw for v in self.resolve(x, job)]
        if isinstance(raw, dict):
            return [{k: self.resolve(v, job) for k, v in raw.items()}]
        if not isinstance(raw, str) or "${{" not in raw:
            return [raw]
        body = _expr_body(raw)
        if body is None:
            raise Dynamic(f"text around ${{{{ }}}}: {raw!r}")
        try:
            tree = parse_expr(body)
        except ValueError as e:
            raise Dynamic(str(e)) from e
        return self.values(tree, job)

    def matrix(self, job: dict, path: "tuple[str, ...]") -> "list[Any]":
        m = (job.get("strategy") or {}).get("matrix")
        if m is None:
            return [None]
        found: "list[Any]" = []
        for whole in self.resolve(m, job):
            if isinstance(whole, _Canon):
                if path == ("runs_on",):
                    found.append(_Canon("runs_on"))
                    continue
                raise Dynamic(
                    f"matrix.{'.'.join(path)} of a ci-runner matrix: only "
                    "runs_on is decided by ci-runner"
                )
            if not isinstance(whole, dict):
                raise Dynamic("a matrix it cannot resolve")
            cands: "list[Any]" = []
            for k, v in whole.items():
                if k == path[0] and k not in ("include", "exclude"):
                    for x in v if isinstance(v, list) else [v]:
                        cands += x if isinstance(x, list) else [x]
            inc = whole.get("include") or []
            for entry in inc if isinstance(inc, list) else [inc]:
                if isinstance(entry, dict) and path[0] in entry:
                    cands += self.resolve(entry[path[0]], job)
            for key in path[1:]:
                cands = [
                    x.get(key) if isinstance(x, dict) else None for x in cands
                ]
            for c in cands:
                if isinstance(c, list):
                    found += c
                elif isinstance(c, str) and "${{" in c:
                    found += self.resolve(c, job)
                else:
                    found.append(c)
        return found

    def verdicts(self) -> "Iterable[tuple[str, str]]":
        """``(job, problem)`` for each job a fork PR could run self-hosted."""
        for name, job in self.jobs.items():
            if not isinstance(job, dict) or "runs-on" not in job:
                continue
            why = self.reaches(job)
            if not why:
                continue
            if not self.pr_events:
                continue
            ok, how = fork_safe_if(job.get("if"), self.pr_events)
            if not ok:
                yield name, f"{why}; {how}"

    def reaches(self, job: dict) -> str:
        """Why *job* can run self-hosted, or ``""`` if it cannot (or only
        through ci-runner)."""
        try:
            vals = self.resolve(job["runs-on"], job)
        except Dynamic as e:
            return f"runs-on cannot be resolved ({e})"
        for v in _flatten(vals):
            if isinstance(v, _Canon):
                if v.what != "runs_on":
                    return (
                        "runs-on reads a ci-runner output other than runs_on"
                    )
                continue
            if isinstance(v, dict):
                if "group" in v:
                    return "runs-on names a runner group"
                labels = list(_flatten(v.get("labels") or []))
            else:
                labels = [v]
            for x in labels:
                if isinstance(x, str) and x.strip() and not hosted(x):
                    return f"runs-on can be {x!r}, not a GitHub-hosted image"
        return ""


def _has_canon(x: Any) -> bool:
    if isinstance(x, _Canon):
        return True
    if isinstance(x, dict):
        return any(_has_canon(v) for v in x.values())
    if isinstance(x, list):
        return any(_has_canon(v) for v in x)
    return False


_PRINTF_ARG = r"""(?:'[^']*'|"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")"""

#: The ONE shape a trusted step's script may have: optionally ``printf``
#: of literals and plain variables, piped into ``make ci-runner`` (with
#: plain ``NAME=value`` make variables), appended to ``$GITHUB_OUTPUT``.
TRUSTED_RUN = re.compile(
    r"^(?:printf(?:\s+" + _PRINTF_ARG + r")+\s*\|\s*)?"
    r"make(?:\s+-s)?\s+ci-runner(?:\s+[A-Z_][A-Z0-9_]*=[\w./-]+)*"
    r'\s*>>\s*(?:"\$GITHUB_OUTPUT"|"\$\{GITHUB_OUTPUT\}"|\$GITHUB_OUTPUT)$'
)

#: Variables that change what that one command does: a startup file bash
#: sources, make flags or makefiles, where the output goes, what runs.
UNSAFE_ENV = frozenset(
    "BASH_ENV ENV SHELLOPTS BASHOPTS PS4 PATH MAKEFLAGS MFLAGS GNUMAKEFLAGS "
    "MAKEFILES GITHUB_OUTPUT".split()
)

#: Prefixes of variables that also change what runs or what ``pick``
#: reads: Python's startup and path, the loader's preloads, and every
#: ``GITHUB_*`` / ``RUNNER_*`` variable Actions sets (``GITHUB_EVENT_NAME``
#: would tell ``pick`` it is a push). ``GITHUB_TOKEN`` is the one name it
#: may set: ``pick`` reads the queue with it, and a wrong one is an API
#: error, which keeps every leg hosted.
UNSAFE_ENV_PREFIXES = ("PYTHON", "LD_", "DYLD_", "GITHUB_", "RUNNER_")


def unsafe_env(name: str) -> bool:
    """Whether a workflow may not set *name* around the trusted step.

    >>> [unsafe_env(x) for x in ("LEGS", "GITHUB_TOKEN", "PYTHONPATH")]
    [False, False, True]
    """
    if name == "GITHUB_TOKEN":
        return False
    return name in UNSAFE_ENV or name.startswith(UNSAFE_ENV_PREFIXES)


#: actions/checkout inputs that keep the checkout this repository's own
#: commit, in the workspace root.
CHECKOUT_OK = frozenset(
    "fetch-depth fetch-tags persist-credentials submodules lfs clean "
    "filter show-progress sparse-checkout sparse-checkout-cone-mode".split()
)


def run_shape_ok(run: str) -> bool:
    """Whether a ``run:`` script is exactly the trusted shape, comments
    and blank lines aside.

    >>> run_shape_ok("printf 'm=%s' | make -s ci-runner >> $GITHUB_OUTPUT")
    True
    >>> run_shape_ok("printf $(cat x) | make -s ci-runner >> $GITHUB_OUTPUT")
    False
    >>> run_shape_ok('make -s ci-runner >> "$GITHUB_OUTPUT" && ./more.sh')
    False

    No ``${{ }}`` anywhere, not even in a comment or a quoted literal:
    GitHub substitutes it into the script before bash reads it, so a
    fork's ``'`` in a title or branch name would end the quote.

    >>> run_shape_ok("printf 'm=${{ github.head_ref }}' | make -s ci-runner"
    ...              " >> $GITHUB_OUTPUT")
    False
    """
    if "${{" in run:
        return False
    lines = [
        ln.strip()
        for ln in run.replace("\\\n", " ").split("\n")
        if ln.strip() and not ln.strip().startswith("#")
    ]
    return len(lines) == 1 and bool(
        TRUSTED_RUN.match(" ".join(lines[0].split()))
    )


def trusted_step(
    step: dict,
    before: "list[dict]",
    job: dict,
    doc: dict,
    events: "Iterable[str]" = (),
) -> bool:
    """Whether *step*'s outputs can only be what ``make ci-runner`` wrote.

    Its script is :func:`run_shape_ok`; it runs under the default shell,
    in the workspace root, with no :data:`UNSAFE_ENV` variable set by the
    workflow, the job or the step; and nothing before it in the job can
    change its environment or what it runs: each earlier step is a plain
    ``actions/checkout`` (:data:`CHECKOUT_OK` inputs only) or a ``run:``
    that does not write ``$GITHUB_ENV`` or ``$GITHUB_PATH``. It trusts the
    repository's own Makefile at the checked-out commit.

    When the workflow can run on a fork-driven *event* other than plain
    ``pull_request`` -- ``pull_request_target``, ``workflow_run``,
    ``issue_comment``, a review event, or ``workflow_call``, whose
    caller's event is unknown -- the workflow is this repository's but
    the code an earlier ``run:`` fetches can be a fork's (``gh pr
    checkout``, ``git fetch`` of a head SHA), and the trusted step would
    then run the fork's Makefile. There only plain checkouts may come
    first. (Under ``pull_request`` the workflow file itself is the fork's,
    so nothing in it can be trusted more than that.)
    """
    if not run_shape_ok(str(step.get("run") or "")):
        return False
    for where in (doc, job, step):
        env = where.get("env") or {}
        if not isinstance(env, dict) or any(unsafe_env(k) for k in env):
            return False
    for where in (doc, job):
        run = ((where.get("defaults") or {}).get("run")) or {}
        if run.get("shell") not in (None, "bash") or run.get(
            "working-directory"
        ):
            return False
    if step.get("shell") not in (None, "bash") or step.get(
        "working-directory"
    ):
        return False
    strict = any(e != "pull_request" for e in events)
    for b in before:
        if strict and "uses" not in b:
            return False
        if "uses" in b:
            if not str(b["uses"]).startswith("actions/checkout@"):
                return False
            if set(b.get("with") or {}) - CHECKOUT_OK:
                return False
        elif re.search(r"GITHUB_(ENV|PATH)", str(b.get("run") or "")):
            return False
    return True


def _flatten(vals: "Iterable[Any]") -> "Iterable[Any]":
    for v in vals:
        if isinstance(v, list):
            yield from _flatten(v)
        else:
            yield v


def check(paths: "list[str]") -> "tuple[int, list[str], list[str]]":
    """Jobs read, problems, and unreadable files across *paths* (files or
    directories of workflows)."""
    files: "list[pathlib.Path]" = []
    for p in paths:
        q = pathlib.Path(p)
        if q.is_dir():
            files += sorted(
                f for f in q.iterdir() if f.suffix in (".yml", ".yaml")
            )
        elif q.is_file():
            files.append(q)
    jobs, problems, broken = 0, [], []
    for f in files:
        try:
            wf = Workflow(str(f), load_yaml(f.read_text(encoding="utf-8")))
        except (YamlError, OSError) as e:
            broken.append(f"{f}: {e}")
            continue
        jobs += len(wf.jobs)
        problems += [f"{f}: {job}: {why}" for job, why in wf.verdicts()]
    return jobs, problems, broken


# -------------------------------------------------------------- main


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick", help="planner lines on stdin -> runs_on")
    p.add_argument(
        "--key",
        default="runs_on os",
        help="leg keys naming the hosted label, first match wins",
    )
    p.add_argument(
        "--workflow",
        default="",
        help="the workflow file whose jobs the plan feeds, for a runner "
        "group restricted to selected workflows",
    )
    c = sub.add_parser("check", help="refuse a fork-reachable self-hosted job")
    c.add_argument("paths", nargs="+")
    args = ap.parse_args(argv)

    if args.cmd == "pick":
        lines = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]
        try:
            out, log = pick(
                lines,
                tuple(args.key.split()),
                dict(os.environ),
                workflow=args.workflow,
            )
        except ValueError as e:
            print(f"ci-runner: {e}", file=sys.stderr)
            return 1
        for line in out:
            print(line)
        for line in log:
            print(f"ci-runner: {line}", file=sys.stderr)
        return 0

    present = [x for x in args.paths if pathlib.Path(x).exists()]
    if not present:
        print("self-hosted-check: no workflows -- nothing to check")
        return 0
    jobs, problems, broken = check(present)
    if broken:
        print("ERROR: workflow files self-hosted-check cannot read:")
        print("\n".join(f"  {b}" for b in broken))
        print(
            "\n  A file the gate cannot read is a file it has not checked. "
            "Write it\n  in the subset it reads (no anchors or tags), or "
            "fix the parser."
        )
        return 1
    if jobs == 0:
        print("ERROR: workflows exist but no job was parsed under `jobs:`.")
        return 1
    if problems:
        print("ERROR: jobs a fork's pull request could run self-hosted:")
        print("\n".join(f"  {x}" for x in problems))
        print(
            "\n  A fork's code on a self-hosted runner runs on our machine."
            "\n  Take runs-on from `make ci-runner` (runs-on: "
            "${{ matrix.runs_on }}),\n  or gate the job: if: "
            "github.event.pull_request.head.repo.full_name ==\n  "
            "github.repository (just-buildit.github.io#203)."
        )
        return 1
    print(
        f"self-hosted-check: {jobs} job(s); none lets a fork's pull request "
        "reach a self-hosted runner"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
