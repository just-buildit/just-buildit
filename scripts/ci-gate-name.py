#!/usr/bin/env python3
"""Decide whether a ci.yml job's ``name:`` and ``if:`` make it the gate.

VENDORED VERBATIM from https://just-buildit.github.io/scripts/ci-gate-name.py
and checked by ``standard-check`` like ``standard.mk`` itself. Never edit it
in place; change canonical and re-vendor. ``make ci-changes-wiring-check``
runs it on the job it took for the aggregator, and ``make lint`` runs that.

Why
---
``CI_CHECK_NAME`` (``CI passed``) is the check the required-check ruleset
and ``release-verify-ci`` read. A check of that name on a commit is read
as that commit's verdict, so the name must exist only where the full gate
ran. Two shapes put it somewhere else:

* a literal ``name: CI passed`` whose ``if:`` can be false. A job whose
  ``if:`` is false still reports: a SKIPPED check of that name, and a
  skipped required check counts as passing for branch protection;
* a name EXPRESSION that can yield ``CI passed`` on a run that is not the
  gate. doppler needed the name to depend on the run (#3302): a push with no
  PR runs a minimal set, a push heading an open PR is skipped because the
  PR run is the gate, and each must report under ANOTHER name, or a ruleset
  reading the newest check of the name sees a green that was never the gate
  (just-buildit.github.io#241).

The rule
--------
A **literal** name equal to ``CI_CHECK_NAME`` is the gate when its job's
``if:`` is exactly ``always()`` -- with or without ``${{ }}``, whitespace
aside. Anything else is refused: no other condition can be shown to be
always true without evaluating it. An ABSENT ``if:`` is refused too: the
aggregator ``needs:`` the jobs it judges, and with no status function
GitHub ANDs in ``success()``, so a failed need SKIPS it -- and a skipped
required check counts as passing.

An **expression** name is the gate when the whole value is one
``${{ ... }}`` of the single-branch shape::

    <cond> && 'CI passed' || <cond> && '<other>' || ... || '<fallback>'

* the first branch's value is ``CI_CHECK_NAME``, exactly once;
* every other value -- each later branch and the fallback -- is a string
  literal that differs from it. ``'CI passed (push, minimal set)'``
  differs: values are compared whole, never by substring. Failing closed,
  a value equal to it but for case or surrounding whitespace
  (``'ci passed'``, ``' CI passed '``) counts as the name;
* each condition reads a context (``needs.scope.outputs.scope == 'full'``);
  a constant condition is no gate;
* the job's ``if:`` obeys the literal rule above, for the same reason.

The expression is never evaluated. It is tokenized -- string literals with
``''`` escapes, ``&&``, ``||``, ``==`` and ``!=``, and context words -- and
its SHAPE is checked. Parentheses, ``!``, an index, a function call or any
other operator are refused, naming it, rather than guessed at: a reader
that guesses is a loophole, not a gate.

A backslash anywhere in a double-quoted ``name:`` or ``if:`` is refused.
YAML decodes escapes there (``"CI\\x20passed"`` is ``CI passed``), and
a reader that decodes only some of them would compare the wrong text.

Examples
--------
>>> full = ("${{ s == 'full' && 'CI passed' || "
...         "s == 'minimal' && "
...         "'CI passed (push, minimal set)' || 'CI passed (skipped)' }}")
>>> refusal("CI passed", full, "always()") is None
True
>>> off = full.replace(" (push, minimal set)", "")
>>> print(refusal("CI passed", off, "always()"))
branch 2 yields 'CI passed' off the gate: s == 'minimal' && 'CI passed'
>>> refusal("CI passed", "CI passed", "${{ always() }}") is None
True
>>> print(refusal("CI passed", "CI passed", ""))
it has no if: -- with needs: GitHub adds success(), so a failed need SKIPS it
>>> print(refusal("CI passed", "CI passed", "github.event_name == 'push'"))
its if: is not always(): github.event_name == 'push'
"""

from __future__ import annotations

import argparse
import re
import sys

#: A context word: ``needs.scope.outputs.scope``, ``github.event_name``, a
#: number, ``true``. Hyphens are legal in job ids (``needs.my-job``).
_WORD = re.compile(r"[A-Za-z0-9_.-]+")

#: Words that are constants, not contexts: a condition of only these is
#: always true or always false, so it selects nothing.
_CONSTANTS = {"true", "false", "null"}


#: One token: ``(kind, value, start, end)``.
Token = tuple[str, str, int, int]


class Refused(ValueError):
    """Not the shape this gate accepts; the message says why."""


def yaml_scalar(raw: str) -> str:
    r"""The text of a one-line YAML scalar as written after ``key:``.

    Single quotes take ``''``; a plain scalar is returned stripped. A
    double-quoted scalar is returned unquoted, and refused if it holds a
    backslash: YAML decodes a dozen escapes there (``\x20``, ``\u0020``,
    a line continuation), so failing closed beats decoding some of them.

    >>> yaml_scalar('"${{ a && ' + "'x' }}" + '"')
    "${{ a && 'x' }}"
    >>> try:
    ...     yaml_scalar(r'"CI\x20"')
    ... except Refused as e:
    ...     print(e)
    a backslash escape in a double-quoted value is not supported: "CI\x20"
    >>> yaml_scalar("'${{ a && ''x'' || ''y'' }}'")
    "${{ a && 'x' || 'y' }}"
    >>> yaml_scalar("  CI passed ")
    'CI passed'
    """
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if len(s) >= 2 and s[0] == s[-1] == '"':
        if "\\" in s:
            raise Refused(
                "a backslash escape in a double-quoted value is not"
                f" supported: {s}"
            )
        return s[1:-1]
    return s


def unwrap(value: str) -> str | None:
    """The contents of a value that is wholly one ``${{ ... }}``, else None.

    >>> unwrap("${{ always() }}")
    ' always() '
    >>> unwrap("always()") is None
    True
    >>> unwrap("x ${{ a }}") is None
    True
    """
    s = value.strip()
    if s.startswith("${{") and s.endswith("}}") and s.count("${{") == 1:
        return s[3:-2]
    return None


def tokens(expr: str) -> list[Token]:
    """``(kind, value, start, end)`` for each token of an expression.

    Kinds: ``str`` (a literal, ``''`` unescaped), ``and``, ``or``, ``cmp``
    (``==``/``!=``) and ``word``. Anything else is refused, naming it.

    >>> [(k, v) for k, v, _, _ in tokens("a == 'it''s' && 'x'")][:3]
    [('word', 'a'), ('cmp', '=='), ('str', "it's")]
    >>> [(k, v) for k, v, _, _ in tokens("a == 'it''s' && 'x'")][3:]
    [('and', '&&'), ('str', 'x')]
    >>> try:
    ...     tokens("!a && 'x'")
    ... except Refused as e:
    ...     print(e)
    unsupported '!' at column 1 of the expression
    >>> try:
    ...     tokens("(a) && 'x'")
    ... except Refused as e:
    ...     print(e)
    unsupported '(' at column 1 of the expression
    >>> try:
    ...     tokens("a && 'x")
    ... except Refused as e:
    ...     print(e)
    unterminated string at column 6 of the expression
    """
    out: list[Token] = []
    i, n = 0, len(expr)
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
        elif c == "'":
            j, buf = i + 1, []
            while True:
                if j >= n:
                    raise Refused(
                        f"unterminated string at column {i + 1}"
                        " of the expression"
                    )
                if expr[j] == "'":
                    if expr[j + 1 : j + 2] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(expr[j])
                j += 1
            out.append(("str", "".join(buf), i, j + 1))
            i = j + 1
        elif expr.startswith("&&", i):
            out.append(("and", "&&", i, i + 2))
            i += 2
        elif expr.startswith("||", i):
            out.append(("or", "||", i, i + 2))
            i += 2
        elif expr.startswith("==", i) or expr.startswith("!=", i):
            out.append(("cmp", expr[i : i + 2], i, i + 2))
            i += 2
        else:
            m = _WORD.match(expr, i)
            if not m:
                raise Refused(
                    f"unsupported {c!r} at column {i + 1} of the expression"
                )
            out.append(("word", m.group(), i, m.end()))
            i = m.end()
    return out


def _split(toks: list[Token], kind: str) -> list[list[Token]]:
    parts: list[list[Token]] = [[]]
    for t in toks:
        if t[0] == kind:
            parts.append([])
        else:
            parts[-1].append(t)
    return parts


def branches(expr: str) -> list[tuple[str | None, str, str]]:
    """``(condition, value, source)`` per branch of a single-branch chain.

    The last branch is the fallback, its condition None. Refused when a
    branch is not ``<cond> && '<string>'``, the fallback is not a string
    literal, or a condition reads no context.

    >>> for b in branches("a == 'f' && 'x' || b && 'y' || 'z'"):
    ...     print(b)
    ("a == 'f'", 'x', "a == 'f' && 'x'")
    ('b', 'y', "b && 'y'")
    (None, 'z', "'z'")
    >>> try:
    ...     branches("a && b || 'z'")
    ... except Refused as e:
    ...     print(e)
    branch 1 does not end in a string literal: a && b
    >>> try:
    ...     branches("true && 'x' || 'y'")
    ... except Refused as e:
    ...     print(e)
    branch 1's condition reads no context: true && 'x'
    >>> try:
    ...     branches("a && 'x'")
    ... except Refused as e:
    ...     print(e)
    no fallback: the last branch must be a string literal, not a && 'x'
    """
    toks = tokens(expr)
    terms = _split(toks, "or")
    out: list[tuple[str | None, str, str]] = []
    for k, term in enumerate(terms, 1):
        if not term:
            raise Refused(f"branch {k} is empty")
        src = expr[term[0][2] : term[-1][3]]
        ops = _split(term, "and")
        if any(not op for op in ops):
            raise Refused(f"branch {k} has an empty operand: {src}")
        last = k == len(terms)
        if last and len(ops) == 1:
            if len(ops[0]) != 1 or ops[0][0][0] != "str":
                raise Refused(
                    f"the fallback is not a string literal: {src}"
                )
            out.append((None, ops[0][0][1], src))
            continue
        if last:
            raise Refused(
                "no fallback: the last branch must be a string literal,"
                f" not {src}"
            )
        if len(ops) < 2:
            raise Refused(f"branch {k} has no condition: {src}")
        val = ops[-1]
        if len(val) != 1 or val[0][0] != "str":
            raise Refused(
                f"branch {k} does not end in a string literal: {src}"
            )
        for op in ops[:-1]:
            if not any(
                t[0] == "word"
                and t[1] not in _CONSTANTS
                and not t[1][0].isdigit()
                for t in op
            ):
                raise Refused(
                    f"branch {k}'s condition reads no context: {src}"
                )
        cond = expr[ops[0][0][2] : ops[-2][-1][3]]
        out.append((cond, val[0][1], src))
    return out


def _always(when: str) -> bool:
    s = when
    inner = unwrap(s)
    s = inner if inner is not None else s
    return re.sub(r"\s+", "", s) == "always()"


def _same(a: str, b: str) -> bool:
    """Whether two names are one, failing closed: case and ends aside.

    >>> _same(" ci PASSED ", "CI passed"), _same("CI  passed", "CI passed")
    (True, False)
    """
    return a.strip().casefold() == b.strip().casefold()


def refusal(check: str, raw_name: str, raw_if: str) -> str | None:
    """Why a job named ``raw_name`` with ``if: raw_if`` is no gate, or None.

    ``raw_name`` and ``raw_if`` are the YAML scalars as written (an absent
    ``if:`` is ``""``); ``check`` is ``CI_CHECK_NAME``.

    >>> ok = "always()"
    >>> print(refusal("CI passed", "${{ a && 'x' || ' ci passed' }}", ok))
    the fallback yields 'CI passed' off the gate: ' ci passed'
    >>> print(refusal("CI passed", "${{ 'CI passed' }}", ok))
    it yields 'CI passed' unconditionally: 'CI passed'
    >>> print(refusal("CI passed", "${{ a && 'x' || b && 'y' || 'z' }}", ok))
    the first branch yields 'x', not 'CI passed'
    >>> print(refusal("CI passed", "${{ a && 'ci passed' || 'z' }}", ok))
    the first branch yields 'ci passed', not 'CI passed'
    >>> print(refusal("CI passed", "${{ a && 'CI passed' || 'z' }}", "b"))
    its if: is not always(): b
    >>> print(refusal("CI passed", "x-${{ a }}", ok))
    the name is not 'CI passed' nor wholly one ${{ ... }}: x-${{ a }}
    >>> print(refusal("CI passed", "ci passed", ok))
    the name is 'CI passed' but for case or whitespace: ci passed
    """
    try:
        name = yaml_scalar(raw_name)
        when = yaml_scalar(raw_if)
    except Refused as e:
        return str(e)
    if when == "":
        return (
            "it has no if: -- with needs: GitHub adds success(),"
            " so a failed need SKIPS it"
        )
    if not _always(when):
        return f"its if: is not always(): {when}"
    if name == check:
        return None
    if _same(name, check):
        return f"the name is {check!r} but for case or whitespace: {name}"
    expr = unwrap(name)
    if expr is None:
        whole = "wholly one ${{ ... }}"
        return f"the name is not {check!r} nor {whole}: {name}"
    try:
        chain = branches(expr)
    except Refused as e:
        return str(e)
    for k, (cond, val, src) in enumerate(chain, 1):
        if _same(val, check) and cond is None and k == 1:
            return f"it yields {check!r} unconditionally: {src}"
        if _same(val, check) and k > 1:
            where = "the fallback" if cond is None else f"branch {k}"
            return f"{where} yields {check!r} off the gate: {src}"
    if chain[0][1] != check:
        return f"the first branch yields {chain[0][1]!r}, not {check!r}"
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--check-name", required=True, help="CI_CHECK_NAME")
    p.add_argument("--job", required=True, help="the job id, for messages")
    p.add_argument("--name", required=True, help="the job's name: as written")
    p.add_argument("--if", dest="cond", default="", help="its if: as written")
    a = p.parse_args(argv)
    why = refusal(a.check_name, a.name, a.cond)
    if why is None:
        return 0
    print(
        f"ERROR: job '{a.job}' is not a safe '{a.check_name}' gate: {why}\n"
        f"  A check named '{a.check_name}' is read as the commit's verdict,"
        " so it must\n"
        "  exist only where the full gate ran. A job whose if: is false"
        " still\n"
        "  reports -- a SKIPPED check, which branch protection counts as"
        " passing --\n"
        "  so the aggregator's if: is exactly always(): an absent if: is"
        " success(),\n"
        "  which SKIPS it when a need fails. A name expression must be\n"
        f"    ${{{{ <cond> && '{a.check_name}' || <cond> && '<other>' || "
        "'<fallback>' }}\n"
        f"  with '{a.check_name}' only in the first branch, every other value"
        " a\n"
        "  different string literal, and no parentheses or other operators."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
