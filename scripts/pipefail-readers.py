#!/usr/bin/env python3
"""Find pipelines that end in a reader which may stop reading early.

``grep -q`` exits at its first match, ``head`` once it has its lines,
``sed 1q`` and ``awk '{...; exit}'`` when their script says so. A producer
still writing then takes SIGPIPE and exits 141, and under ``pipefail`` the
pipeline fails, though the reader got what it wanted. Whether it fails
depends on whether the producer had finished writing first: canonical's
close-keywords step, ``make -pn lint | grep -qE ...``, failed every time on
a local box (rc 141, 3 of 3) and passed on the runner by timing alone.
Under ``!`` the race inverts: ``! make ci-image-config | grep -qx
packager=1`` is TRUE when grep matched and make took SIGPIPE, so an owed
check was skipped.

``grep ... >/dev/null`` and ``sed -n 1p`` read all of their input, so the
producer always finishes and the exit status is the reader's verdict alone.

The rule has no exceptions. A pipeline whose status is thrown away -- one
ending in ``|| true`` or ``|| :``, or one nothing tests -- is flagged all
the same: making it safe costs one ``sed -n 1p``, a rule without exceptions
needs no judgement to apply, and a status discarded today is tested the
day someone edits the line.

What it reads: PIPELINES, not lines. A command continued with a trailing
``\\`` or ``|`` is joined first; the words are split as the shell splits
them, so ``grep -E -q``, ``egrep -q`` and a pipe split across lines are all
seen; each command substitution, ``$(...)`` or backticks, is read as a
command line of its own, inside double quotes too; and assignments and
wrapper words (``command``, ``builtin``, ``env``, ``exec``) before the
reader are skipped, so ``| LC_ALL=C grep -q`` is seen.

Canonical: just-buildit.github.io's ``scripts/pipefail-readers.py``. A repo
vendors it and runs it over its own pipefail shell; canonical's tests hold
the rules (tests/test_no_grep_q_pipe.py).

Usage::

    python3 pipefail-readers.py [--pipefail-only] FILE...

A ``.yml`` / ``.yaml`` file is read as a workflow (a ``run: |`` is YAML's,
not a pipe). ``--pipefail-only`` skips a SHELL file that never sets
pipefail; a workflow is always read, since a step runs under pipefail when
it names ``shell: bash`` (GitHub's ``bash -eo pipefail``), and adding that
later is one line that would arm the race silently.
Exit 0 when nothing is found, 1 naming each offender, 2 when no file was
scanned at all: a check that read nothing has not passed.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys

#: A YAML key opening a block scalar (``run: |``, ``body: >-``): its ``|``
#: is YAML's, not a pipe.
_BLOCK = re.compile(r"^\s*(?:-\s+)?[\w.-]+:\s*[|>][-+0-9]*\s*(?:#.*)?$")
#: A file that turns pipefail on.
PIPEFAIL = re.compile(r"^\s*set\b[^#\n]*\bpipefail\b", re.M)
#: grep's short options that stop reading early: -q, -m N, -l, -L.
_EARLY = set("qmlL")
#: grep's short options that take an argument: the rest of the bundle, or
#: the next word, is that argument and not an option.
_TAKES_ARG = set("efmABCDd")
_GREPS = {"grep", "egrep", "fgrep"}
#: Words that run the command after them: the reader is that command.
_WRAPPERS = {"command", "builtin", "exec", "env", "nohup", "time"}
#: A wrapper option that takes the next word as its argument.
_WRAPPER_ARG = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
#: A sed ``q`` / ``Q`` command: after an address, ``;``, ``{`` or a blank,
#: optionally with an exit code, then the end of the command.
_SED_Q = re.compile(r"(?:^|[;{}\s\d$/])[qQ]\d*\s*(?:$|[;}\s])")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def pipelines(text: str, yaml: bool = False) -> list[tuple[int, str]]:
    """Each logical command line of *text*, with its first line's number.

    >>> pipelines("a |\\n  grep -q x\\nb \\\\\\n c\\n")
    [(1, 'a | grep -q x'), (3, 'b  c')]
    >>> pipelines("run: |\\n  a || b\\n", yaml=True)
    [(2, 'a || b')]
    """
    out: list[tuple[int, str]] = []
    held, first = "", 0
    for n, raw in enumerate(text.splitlines(), 1):
        if yaml and not held and _BLOCK.match(raw):
            continue
        line = raw.strip()
        if not held:
            first = n
        if line.endswith("\\"):
            held += line[:-1] + " "
            continue
        if line.endswith("|") and not line.endswith("||"):
            held += line + " "
            continue
        out.append((first, held + line))
        held = ""
    if held:
        out.append((first, held.strip()))
    return out


def substitutions(line: str) -> list[str]:
    """The command text of each ``$(...)`` and backtick substitution in
    *line* that the shell runs: outside single quotes, inside double
    quotes or bare. ``$((...))`` is arithmetic, not a command.

    >>> substitutions('v="$(gh --version | head -n 1)"')
    ['gh --version | head -n 1']
    >>> substitutions("echo '$(not | run)' `a | b` $((1 + 2))")
    ['a | b']
    >>> substitutions('x=$(a "$(b | c)" | d)')
    ['a "$(b | c)" | d']
    """
    out: list[str] = []
    i, n, single, double = 0, len(line), False, False
    while i < n:
        c = line[i]
        if c == "\\" and not single:
            i += 2
            continue
        if c == "'" and not double:
            single = not single
        elif c == '"' and not single:
            double = not double
        elif single:
            pass
        elif line.startswith("$(", i) and not line.startswith("$((", i):
            depth, j, sq, dq = 1, i + 2, False, False
            while j < n and depth:
                d = line[j]
                if d == "\\" and not sq:
                    j += 2
                    continue
                if d == "'" and not dq:
                    sq = not sq
                elif d == '"' and not sq:
                    dq = not dq
                elif not sq and not dq:
                    depth += {"(": 1, ")": -1}.get(d, 0)
                j += 1
            out.append(line[i + 2 : j - 1] if depth == 0 else line[i + 2 :])
            i = j
            continue
        elif c == "`":
            j = i + 1
            while j < n and line[j] != "`":
                j += 2 if line[j] == "\\" else 1
            out.append(line[i + 1 : j])
            i = j + 1
            continue
        i += 1
    return out


def _words(line: str) -> list[str]:
    """The shell words and operators of *line*; ValueError when a quote is
    left open."""
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = "#"
    return list(lex)


def _readers(line: str) -> list[list[str]]:
    """The words of each command that a ``|`` in *line* feeds.

    A line that is part of a quoted string spanning lines (a jq program)
    has a quote left open, so it is read from each ``|`` onward instead: a
    suffix that parses is a real pipe's reader, and one that does not is
    inside the string.

    >>> _readers("a | grep -q x; b")
    [['grep', '-q', 'x']]
    >>> _readers('| select(.x)] | length" 2>/dev/null | awk \\'{exit}\\'')
    [['awk', '{exit}']]
    """
    try:
        words = _words(line)
        starts = [i + 1 for i, w in enumerate(words) if w in ("|", "|&")]
        tails = [words[i:] for i in starts]
    except ValueError:
        tails = []
        for i, c in enumerate(line):
            # A `|` of `||` is no pipe.
            if c != "|" or "|" in (line[i - 1 : i], line[i + 1 : i + 2]):
                continue
            try:
                tails.append(_words(line[i + 1 :].lstrip("&")))
            except ValueError:
                continue
    out = []
    for tail in tails:
        cmd = []
        for x in tail:
            if x and set(x) <= set("();<>|&"):
                break
            cmd.append(x)
        out.append(cmd)
    return out


def _command(cmd: list[str]) -> list[str]:
    """*cmd* from the command that actually runs: assignments and wrapper
    words before it (with the wrapper's options) dropped.

    >>> _command(["LC_ALL=C", "command", "grep", "-q", "x"])
    ['grep', '-q', 'x']
    >>> _command(["env", "-u", "X", "A=1", "head"])
    ['head']
    """
    i = 0
    while i < len(cmd):
        w = cmd[i]
        if _ASSIGN.match(w):
            i += 1
        elif w.lstrip("\\").rsplit("/", 1)[-1] in _WRAPPERS:
            i += 1
            while i < len(cmd) and cmd[i].startswith("-"):
                i += 2 if cmd[i] in _WRAPPER_ARG else 1
        else:
            break
    return cmd[i:]


def _program(args: list[str], takes_arg: set[str]) -> str:
    """The first operand of *args*: the program of an awk or sed call
    that names none with -e / -f. Options in *takes_arg* consume the next
    word."""
    skip = False
    for a in args:
        if skip:
            skip = False
        elif a in takes_arg:
            skip = True
        elif not (a.startswith("-") and len(a) > 1):
            return a
    return ""


def _sed_stops(args: list[str]) -> bool:
    scripts = [
        args[k + 1]
        for k, a in enumerate(args[:-1])
        if a in ("-e", "--expression")
    ]
    scripts += [
        a.split("=", 1)[1] for a in args if a.startswith("--expression=")
    ]
    if not scripts and not {"-f", "--file"} & set(args):
        scripts = [_program(args, {"-l"})]
    return any(_SED_Q.search(s) for s in scripts)


def _grep_stops(args: list[str]) -> bool:
    skip = False
    for w in args:
        if skip:
            skip = False
            continue
        if w == "--":
            break
        if w.startswith("--"):
            if w in (
                "--quiet",
                "--silent",
                "--files-with-matches",
                "--files-without-match",
            ) or w.startswith("--max-count"):
                return True
            continue
        if w.startswith("-") and len(w) > 1:
            for i, ch in enumerate(w[1:]):
                if ch in _EARLY:
                    return True
                if ch in _TAKES_ARG:
                    skip = i == len(w) - 2
                    break
    return False


def early_reader(cmd: list[str]) -> bool:
    """Whether the command *cmd* (its words) may stop reading its input.

    >>> early_reader(["grep", "-E", "-q", "x"])
    True
    >>> early_reader(["grep", "x", "--quiet"])
    True
    >>> early_reader(["egrep", "-xq", "y"]), early_reader(["fgrep", "-m1"])
    (True, True)
    >>> early_reader(["head", "-n1"])
    True
    >>> early_reader(["grep", "-e", "-q", "x"])
    False
    >>> early_reader(["grep", "-c", "x"]), early_reader(["sed", "-n", "1p"])
    (False, False)
    >>> early_reader(["sed", "1q"]), early_reader(["sed", "-n", "1{p;q}"])
    (True, True)
    >>> early_reader(["sed", "s/q/x/"]), early_reader(["sed", "-e", "/x/q"])
    (False, True)
    >>> early_reader(["awk", "NR==1 {print; exit}"])
    True
    >>> early_reader(["awk", "-F:", "{print $1}"])
    False
    >>> early_reader(["command", "grep", "-q", "x"])
    True
    >>> early_reader(["LC_ALL=C", "grep", "-q", "x"])
    True
    >>> early_reader(["env", "LC_ALL=C", "head", "-1"])
    True
    >>> early_reader(["builtin", "echo", "x"])
    False
    """
    cmd = _command(cmd)
    if not cmd:
        return False
    name, args = cmd[0].lstrip("\\").rsplit("/", 1)[-1], cmd[1:]
    if name == "head":
        return True
    if name in _GREPS:
        return _grep_stops(args)
    if name == "sed":
        return _sed_stops(args)
    if name in ("awk", "gawk", "mawk", "nawk"):
        if {"-f", "--file"} & set(args):
            return False
        return bool(re.search(r"\bexit\b", _program(args, {"-F", "-v"})))
    return False


def _pipes_into_reader(line: str) -> bool:
    if any(early_reader(cmd) for cmd in _readers(line)):
        return True
    return any(_pipes_into_reader(s) for s in substitutions(line))


def offenders(text: str, yaml: bool = False) -> list[tuple[int, str]]:
    """Each (line number, pipeline) of *text* piping into an early reader.

    >>> offenders("a | grep -q x\\nb | grep x >/dev/null\\n")
    [(1, 'a | grep -q x')]
    >>> offenders("! make c | grep -qx packager=1")
    [(1, '! make c | grep -qx packager=1')]
    >>> [n for n, _ in offenders("x |\\n  egrep -q y\\nz | grep -E -q w\\n")]
    [1, 3]
    >>> offenders('v="$(gh --version | head -n 1)"')
    [(1, 'v="$(gh --version | head -n 1)"')]
    >>> [n for n, _ in offenders("a | LC_ALL=C grep -q x\\nb | sed 1q\\n")]
    [1, 2]
    >>> offenders("grep -q x file\\na || grep -q y f\\n# a | grep -q c\\n")
    []
    >>> offenders("echo '$(a | head)'\\n")
    []
    >>> offenders("run: |\\n  grep -q x f\\n", yaml=True)
    []

    No exceptions: a status thrown away is flagged all the same.

    >>> discarded = "v=$(x | head -1 || true)\\ny | grep -q z || :\\n"
    >>> [n for n, _ in offenders(discarded)]
    [1, 2]
    """
    return [
        (n, line)
        for n, line in pipelines(text, yaml)
        if _pipes_into_reader(line)
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument(
        "--pipefail-only",
        action="store_true",
        help="skip a shell file that never sets pipefail",
    )
    args = ap.parse_args(argv)
    scanned, found = 0, []
    for f in args.files:
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        yaml = f.endswith((".yml", ".yaml"))
        if args.pipefail_only and not yaml and not PIPEFAIL.search(text):
            continue
        scanned += 1
        found += [f"{f}:{n}: {line}" for n, line in offenders(text, yaml)]
    if not scanned:
        print("pipefail-readers: scanned no file -- nothing was checked")
        return 2
    if found:
        print("\n".join(found))
        print(
            "pipefail-readers: a pipe into an early reader (grep -q/-m/-l, "
            "head, sed q, awk exit) fails under pipefail when the producer "
            "is still writing (SIGPIPE, rc 141), and a `!` before it "
            "inverts that; use `grep ... >/dev/null` or `sed -n 1p`, which "
            "drain their input"
        )
        return 1
    print(f"pipefail-readers: {scanned} file(s), no pipe into an early reader")
    return 0


if __name__ == "__main__":
    sys.exit(main())
