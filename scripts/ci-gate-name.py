#!/usr/bin/env python3
"""Decide which ci.yml job is the gate, and whether its name makes it one.

VENDORED VERBATIM from https://just-buildit.github.io/scripts/ci-gate-name.py
and checked by ``standard-check`` like ``standard.mk`` itself. Never edit it
in place; change canonical and re-vendor. ``make ci-changes-wiring-check``
walks ``GATES_CI_FILE`` into jobs and hands every job's ``name:``, ``if:``
and lines to this script on stdin; ``make lint`` runs that.

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

Which job carries the name
--------------------------
EVERY job's name is read, because a second job that can be named
``CI passed`` reports a second check of it, and with a conditional ``if:``
carries the verdict off the gate (just-buildit.github.io#243). A job with
no ``name:`` is named its id. Names are compared trimmed and case aside.

1. The name is read as a pattern in which every ``${{ ... }}`` hole
   matches anything. A pattern that cannot match ``CI_CHECK_NAME`` clears
   the job: ``test (${{ matrix.os }})`` can never be ``CI passed``.
2. A pattern that can, whose every hole is ``matrix.<key>`` or
   ``matrix.<key>.<field>``, is resolved from the job's literal
   ``strategy.matrix`` -- scalar lists, lists of maps, ``include:``
   entries -- and every name it yields is compared.
3. A name that is wholly one ``${{ ... }}`` holding the name as a string
   literal is an aggregator expression, judged by the rule above.
4. Anything else that might match is refused, naming the job: a
   ``format()``, a ``fromJSON`` or other dynamic matrix, another context.
   The name is never evaluated, so what cannot be read cannot be cleared.
   A ``name:`` that is not one plain or quoted scalar on its own line is
   unreadable too: a block scalar, a tag, an anchor or alias, a quote or
   plain scalar continued onto the next line, an empty value, and any
   line at the job's key depth that is not a plain id-shaped key,
   ``"name"``/``'name'`` or a sequence item: YAML spells the key in ways
   no pattern for ``name`` sees (``? name``, ``"na\\x6de"``, ``!!str
   name``, a flow mapping, a ``<<:`` merge), so the walk reads an
   ALLOW-list and marks the rest ``UNREAD``. :func:`yaml_scalar` refuses
   the value's own forms by their first character.

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

    Anything that is not one complete scalar on this line is refused: a
    block scalar (``>-``, ``|``), a tag (``!!str``), an anchor or alias
    (``&n``, ``*n``) or a quote that does not close here, which YAML
    continues onto the next line.

    >>> for v in (">-", "!!str CI passed", "&n CI passed", "*n", '"CI'):
    ...     try:
    ...         yaml_scalar(v)
    ...     except Refused as e:
    ...         print(e)
    not one plain or quoted scalar on its line: >-
    not one plain or quoted scalar on its line: !!str CI passed
    not one plain or quoted scalar on its line: &n CI passed
    not one plain or quoted scalar on its line: *n
    not one plain or quoted scalar on its line: "CI
    """
    s = raw.strip()
    whole = "not one plain or quoted scalar on its line"
    if s[:1] and s[0] in "|>&*!%@`":
        raise Refused(f"{whole}: {s}")
    if s[:1] in ("'", '"') and (len(s) < 2 or s[-1] != s[0]):
        raise Refused(f"{whole}: {s}")
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


# -- which job carries the name (just-buildit.github.io#243) --------------

#: ``matrix.<key>`` or ``matrix.<key>.<field>``: the only holes resolved.
#: GitHub reads context and property names case-insensitively.
_MATRIX_REF = re.compile(
    r"\s*matrix\.([A-Za-z0-9_-]+)(?:\.([A-Za-z0-9_-]+))?\s*", re.IGNORECASE
)

#: The most names a matrix-built name may resolve to before it is refused.
_MAX_NAMES = 4096


def holes(name: str) -> tuple[list[str], list[str]]:
    """Split a name into its literal pieces and its ``${{ ... }}`` holes.

    There is one more piece than holes. A ``}}`` inside a quoted string in
    a hole does not close it; an unclosed hole is refused.

    >>> holes("CI ${{ matrix.w }}")
    (['CI ', ''], [' matrix.w '])
    >>> holes("${{ format('{0}}}', 'x') }}!")
    (['', '!'], [" format('{0}}}', 'x') "])
    >>> holes("plain")
    (['plain'], [])
    >>> try:
    ...     holes("CI ${{ 'passed }}")
    ... except Refused as e:
    ...     print(e)
    an unclosed ${{ in the name: CI ${{ 'passed }}
    """
    pieces: list[str] = []
    exprs: list[str] = []
    i = 0
    while True:
        j = name.find("${{", i)
        if j < 0:
            pieces.append(name[i:])
            return pieces, exprs
        pieces.append(name[i:j])
        k, quoted = j + 3, False
        while True:
            if k >= len(name):
                raise Refused(f"an unclosed ${{{{ in the name: {name}")
            if name[k] == "'":
                quoted = not quoted
            elif not quoted and name.startswith("}}", k):
                break
            k += 1
        exprs.append(name[j + 3 : k])
        i = k + 2


def can_match(pieces: list[str], check: str) -> bool:
    """Whether the name ``pieces`` with any text in each hole can be ``check``.

    Compared as the gate compares: trimmed, case aside. A hole is any text,
    so the trimmed name's outer pieces lose their outer whitespace and the
    rest must appear in order.

    >>> can_match(["test (", ")"], "CI passed")
    False
    >>> can_match(["CI ", ""], "CI passed"), can_match(["", ""], "CI passed")
    (True, True)
    >>> can_match([" ci PASSED "], "CI passed")
    True
    >>> can_match(["Build on ", ""], "CI passed")
    False
    """
    parts = [p.casefold() for p in pieces]
    parts[0] = parts[0].lstrip()
    parts[-1] = parts[-1].rstrip()
    pattern = ".*".join(re.escape(p) for p in parts)
    target = check.strip().casefold()
    return re.fullmatch(pattern, target, re.DOTALL) is not None


def _strip_comment(text: str) -> str:
    """``text`` with a YAML comment cut, ignoring ``#`` inside quotes."""
    quote = ""
    for k, c in enumerate(text):
        if quote:
            if c == quote:
                quote = ""
        elif c in "'\"" and (k == 0 or text[k - 1] in " \t[{,:"):
            quote = c
        elif c == "#" and (k == 0 or text[k - 1] in " \t"):
            return text[:k].rstrip()
    return text.rstrip()


def _quoted(s: str, i: int) -> tuple[str, int]:
    """The quoted scalar opening at ``s[i]``, and the index after it."""
    q = s[i]
    j, buf = i + 1, []
    while True:
        if j >= len(s):
            raise Refused(f"an unterminated quoted value: {s}")
        if s[j] == "\\" and q == '"':
            raise Refused(
                "a backslash escape in a double-quoted value is not"
                f" supported: {s}"
            )
        if s[j] == q:
            if q == "'" and s[j + 1 : j + 2] == "'":
                buf.append("'")
                j += 2
                continue
            return "".join(buf), j + 1
        buf.append(s[j])
        j += 1


def _flow(s: str, i: int) -> tuple[object, int]:
    """A flow value at ``s[i]``: ``[...]``, ``{...}``, quoted or plain."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        raise Refused(f"a value is missing: {s}")
    c = s[i]
    if c in "[{":
        close = "]" if c == "[" else "}"
        seq: list[object] = []
        mapping: dict[str, object] = {}
        i += 1
        while True:
            while i < len(s) and s[i] == " ":
                i += 1
            if i < len(s) and s[i] == close:
                return (seq if c == "[" else mapping), i + 1
            if c == "[":
                v, i = _flow(s, i)
                seq.append(v)
            else:
                k, i = _flow(s, i)
                while i < len(s) and s[i] == " ":
                    i += 1
                if not isinstance(k, str) or s[i : i + 1] != ":":
                    raise Refused(f"a flow mapping entry has no key: {s}")
                v, i = _flow(s, i + 1)
                if k in mapping:
                    raise Refused(f"a key is repeated: {k}")
                mapping[k] = v
            while i < len(s) and s[i] == " ":
                i += 1
            if s[i : i + 1] == ",":
                i += 1
            elif s[i : i + 1] != close:
                raise Refused(f"an unterminated flow collection: {s}")
    if c in "'\"":
        return _quoted(s, i)
    if c in "&*!|>?@`%":
        raise Refused(f"{c!r} is not supported in strategy.matrix: {s}")
    m = re.compile(r"[^,\]\}:]*(?::(?! |$)[^,\]\}:]*)*").match(s, i)
    assert m is not None  # the pattern matches the empty string
    return m.group().strip(), m.end()


def _scalar(rest: str) -> object:
    """A block mapping's or sequence's inline value, read whole.

    A plain scalar here runs to the end of the line: ``{``, ``}`` and
    ``,`` are flow indicators only inside a flow collection.
    """
    if rest[0] not in "[{'\"&*!|>?@`%":
        return rest
    v, i = _flow(rest, 0)
    if rest[i:].strip():
        raise Refused(f"unexpected text after a value: {rest}")
    return v


def _key(text: str) -> tuple[str, str] | None:
    """``(key, rest)`` of a ``key: rest`` line, or None if it is not one."""
    if text[:1] in "'\"":
        k, i = _quoted(text, 0)
        if text[i : i + 1] == ":" and text[i + 1 : i + 2] in ("", " "):
            return k, text[i + 1 :].strip()
        return None
    if text[:1] in "[{-?":
        return None
    m = re.match(r"([^:#]+?)\s*:(?: |$)", text)
    if m is None:
        return None
    return m.group(1), text[m.end() :].strip()


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


Line = tuple[int, str]


def _block(lines: list[Line], i: int) -> tuple[object, int]:
    col, text = lines[i]
    if _is_item(text):
        return _seq(lines, i, col)
    return _map(lines, i, col)


def _child(lines: list[Line], i: int, col: int) -> tuple[object, int]:
    """The block value of the key or item on ``lines[i]``, at ``col``."""
    if i + 1 < len(lines) and lines[i + 1][0] > col:
        return _block(lines, i + 1)
    return None, i + 1


def _seq(lines: list[Line], i: int, col: int) -> tuple[object, int]:
    out: list[object] = []
    while i < len(lines) and lines[i][0] == col and _is_item(lines[i][1]):
        text = lines[i][1]
        rest = text[1:].lstrip()
        if not rest:
            v, i = _child(lines, i, col)
        elif _key(rest) is not None:
            lines[i] = (col + len(text) - len(rest), rest)
            v, i = _map(lines, i, lines[i][0])
        else:
            v, i = _scalar(rest), i + 1
        out.append(v)
    return out, _end(lines, i, col)


def _map(lines: list[Line], i: int, col: int) -> tuple[object, int]:
    out: dict[str, object] = {}
    while i < len(lines) and lines[i][0] == col:
        kv = _key(lines[i][1])
        if kv is None:
            break
        k, rest = kv
        if rest:
            v: object = _scalar(rest)
            i += 1
        elif i + 1 < len(lines) and lines[i + 1][0] == col and _is_item(
            lines[i + 1][1]
        ):
            v, i = _seq(lines, i + 1, col)
        else:
            v, i = _child(lines, i, col)
        if k in out:
            raise Refused(f"a key is repeated: {k}")
        out[k] = v
    return out, _end(lines, i, col)


def _end(lines: list[Line], i: int, col: int) -> int:
    """Refuse a line the block at ``col`` should have ended at, or read."""
    if i < len(lines) and lines[i][0] >= col:
        raise Refused(f"cannot read the line: {lines[i][1]}")
    return i


def _get(d: dict[str, object], key: str) -> object:
    """``d[key]`` matched case aside, as GitHub matches; refused if two."""
    hits = [k for k in d if k.casefold() == key.casefold()]
    if len(hits) > 1:
        raise Refused(f"keys differ only in case: {', '.join(hits)}")
    return d[hits[0]] if hits else KeyError


def matrix_of(body: list[str]) -> dict[str, object]:
    r"""The literal ``strategy.matrix`` of a job, from its lines.

    ``body`` is the job's lines below its id, indented as written. Only
    the ``strategy:`` block is read, by a reader of the YAML a matrix is
    written in: block and flow maps and lists, plain and quoted scalars.
    Anything else -- an anchor, a block scalar, an expression where a
    list belongs -- is refused rather than guessed at.

    >>> body = ["    strategy:", "      matrix:", "        san:",
    ...         '          - { target: a, label: "ASan" }',
    ...         "          - target: u", "            label: UBSan",
    ...         "        include:", "          - os: x  # a comment"]
    >>> matrix_of(body)  # doctest: +NORMALIZE_WHITESPACE
    {'san': [{'target': 'a', 'label': 'ASan'},
             {'target': 'u', 'label': 'UBSan'}], 'include': [{'os': 'x'}]}
    >>> matrix_of(["    strategy:", "      matrix: { w: [passed] }"])
    {'w': ['passed']}
    >>> try:
    ...     matrix_of(["    strategy:",
    ...                "      matrix: ${{ fromJSON(needs.a.outputs.m) }}"])
    ... except Refused as e:
    ...     print(e)
    strategy.matrix is not literal: ${{ fromJSON(needs.a.outputs.m) }}
    >>> try:
    ...     matrix_of(["    runs-on: x"])
    ... except Refused as e:
    ...     print(e)
    the job has no strategy.matrix
    """
    lines: list[Line] = []
    for raw in body:
        text = _strip_comment(raw)
        if text.strip():
            lines.append((len(text) - len(text.lstrip(" ")), text.strip()))
    if not lines:
        raise Refused("the job has no strategy.matrix")
    top = min(c for c, _ in lines)
    # Only the job's own keys are read: a line deeper in may be any text,
    # a run: script's among them.
    start = next(
        (
            k
            for k, (c, t) in enumerate(lines)
            if c == top and re.match(r"strategy\s*:(?: |$)", t)
        ),
        None,
    )
    if start is None:
        raise Refused("the job has no strategy.matrix")
    end = start + 1
    while end < len(lines) and lines[end][0] > top:
        end += 1
    tree, _ = _map(lines[start:end], 0, top)
    assert isinstance(tree, dict)
    strategy = tree["strategy"]
    if isinstance(strategy, str) and "${{" in strategy:
        raise Refused(f"strategy is not literal: {strategy}")
    matrix = strategy.get("matrix") if isinstance(strategy, dict) else None
    if isinstance(matrix, str) and "${{" in matrix:
        raise Refused(f"strategy.matrix is not literal: {matrix}")
    if not isinstance(matrix, dict):
        raise Refused("the job has no strategy.matrix")
    return matrix


def _rendered(v: object, field: str | None, ref: str) -> str:
    """The text one matrix value puts in the hole ``ref``."""
    if field is not None:
        if not isinstance(v, dict):
            raise Refused(f"{ref}: a value is not a map: {v!r}")
        v = _get(v, field)
        if v is KeyError:
            return ""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise Refused(f"{ref}: a value is not a scalar: {v!r}")
    if "${{" in v:
        raise Refused(f"{ref}: a value is an expression: {v}")
    return v


def values(matrix: dict[str, object], ref: str) -> set[str]:
    """Every text the hole ``ref`` (``matrix.<key>[.<field>]``) can take.

    The values of the key's list, and of every ``include:`` entry naming
    it, read independently: a superset of what the real combinations
    yield, so a name is never cleared that some combination could build.
    ``exclude:`` is ignored for the same reason. A key that only
    ``include:`` sets may be absent from a combination, which renders as
    the empty string.

    >>> m = {"san": [{"label": "ASan"}, {"label": "TSan"}],
    ...      "include": [{"os": "x"}]}
    >>> sorted(values(m, "matrix.san.label"))
    ['ASan', 'TSan']
    >>> sorted(values(m, "matrix.os"))
    ['', 'x']
    >>> try:
    ...     values(m, "matrix.w")
    ... except Refused as e:
    ...     print(e)
    matrix.w: no such key in strategy.matrix
    """
    ref = ref.strip()
    m = _MATRIX_REF.fullmatch(ref)
    assert m is not None
    key, field = m.group(1), m.group(2)
    if key.casefold() in ("include", "exclude"):
        raise Refused(f"{ref}: not a matrix key")
    out: set[str] = set()
    base = _get(matrix, key)
    if base is not KeyError:
        if not isinstance(base, list):
            raise Refused(f"{ref}: the key is not a literal list: {base!r}")
        out |= {_rendered(v, field, ref) for v in base}
    include = _get(matrix, "include")
    if include is not KeyError:
        if not isinstance(include, list) or not all(
            isinstance(e, dict) for e in include
        ):
            raise Refused(f"include: is not a literal list of maps: {include}")
        for entry in include:
            assert isinstance(entry, dict)
            v = _get(entry, key)
            if v is not KeyError:
                out.add(_rendered(v, field, ref))
    if not out:
        raise Refused(f"{ref}: no such key in strategy.matrix")
    if base is KeyError:
        out.add("")
    return out


def _literals(expr: str) -> list[str]:
    """The single-quoted string literals of an expression, ``''`` undone."""
    found = re.findall(r"'((?:[^']|'')*)'", expr)
    return [s.replace("''", "'") for s in found]


def carries(check: str, job: str, raw_name: str, body: list[str]) -> bool:
    """Whether job ``job`` can report a check named ``check``.

    ``raw_name`` is its ``name:`` as written (``""`` when it has none, and
    then the name is the id); ``body`` its lines. Refused, saying why, when
    the name might be ``check`` and cannot be read.

    >>> carries("CI passed", "t", "test (${{ matrix.os }})", [])
    False
    >>> m = ["    strategy:", "      matrix:", "        w: [passed]"]
    >>> carries("CI passed", "w", "CI ${{ matrix.w }}", m)
    True
    >>> carries("CI passed", "w", "CI ${{ matrix.w }}", m[:2] + [
    ...     "        w: [fails]"])
    False
    >>> carries("CI passed", "ci-passed", "' CI passed '", [])
    True
    >>> carries("CI passed", "agg", "${{ a && 'CI passed' || 'x' }}", [])
    True
    >>> try:
    ...     carries("CI passed", "f", "${{ format('CI {0}', 'passed') }}", [])
    ... except Refused as e:
    ...     print(e)
    its name might be 'CI passed' and cannot be read: \
${{ format('CI {0}', 'passed') }}
    >>> try:
    ...     carries("CI passed", "l", "${{ matrix.label }}", [])
    ... except Refused as e:
    ...     print(e)
    its name might be 'CI passed' and cannot be read: \
${{ matrix.label }} -- the job has no strategy.matrix
    """
    name = yaml_scalar(raw_name) if raw_name.strip() else job
    pieces, exprs = holes(name)
    if not exprs:
        return _same(name, check)
    if not can_match(pieces, check):
        return False
    why = f"its name might be {check!r} and cannot be read: {name}"
    if all(_MATRIX_REF.fullmatch(e) for e in exprs):
        try:
            matrix = matrix_of(body)
            options = [sorted(values(matrix, e)) for e in exprs]
        except Refused as e:
            raise Refused(f"{why} -- {e}") from None
        count = 1
        for o in options:
            count *= len(o)
        if count > _MAX_NAMES:
            raise Refused(f"{why} -- it yields {count} names")
        names = [""]
        for k, o in enumerate(options):
            names = [n + pieces[k] + v for n in names for v in o]
        return any(_same(n + pieces[-1], check) for n in names)
    if unwrap(name) is not None and any(
        _same(s, check) for s in _literals(exprs[0])
    ):
        return True
    raise Refused(why)


def jobs(stream: list[str]) -> dict[str, dict[str, object]]:
    """The jobs a ``ci-changes-wiring-check`` walk printed, in order.

    Each line is ``L <job> <line>`` (a line of the job's body, as written),
    ``NAME <job> <name>`` or ``IF <job> <if>`` (as written; empty when the
    job has none) or ``UNREAD <job> <why>`` (the walk could not read the
    job's name: a flow-style job, a name continued onto the next line);
    anything else is the walk's and ignored here.

    >>> jobs(["L a     runs-on: x", "NAME a CI passed", "IF a ", "TOTAL 1"])
    {'a': {'body': ['    runs-on: x'], 'name': 'CI passed', 'if': ''}}
    """
    out: dict[str, dict[str, object]] = {}
    for line in stream:
        kind, _, rest = line.partition(" ")
        if kind not in ("L", "NAME", "IF", "UNREAD"):
            continue
        job, _, value = rest.partition(" ")
        entry = out.setdefault(job, {"body": [], "name": "", "if": ""})
        if kind == "L":
            body = entry["body"]
            assert isinstance(body, list)
            body.append(value)
        else:
            entry[kind.lower()] = value
    return out


def gate(check: str, ci: str, stream: list[str]) -> tuple[str | None, str]:
    """``(aggregator job, "")``, or ``(None, why)`` naming the file.

    Every job is asked whether it carries ``check``. Exactly one may, and
    that one must pass :func:`refusal`; a job that might and cannot be
    read is refused by name.

    >>> walk = ["NAME a CI passed", "IF a always()",
    ...         "NAME b test (${{ matrix.os }})", "IF b x"]
    >>> gate("CI passed", "ci.yml", walk)
    ('a', '')
    >>> print(gate("CI passed", "ci.yml", walk + [
    ...     "NAME c ${{ matrix.label }}"])[1])
    ERROR: ci.yml has a job whose name might be 'CI passed' and cannot be read:
      c: its name might be 'CI passed' and cannot be read: ${{ matrix.label }}\
 -- the job has no strategy.matrix
      A check of that name is read as the commit's verdict, so a job that
      might carry it must be shown not to. Give the name a literal part
      that rules 'CI passed' out (`sanitizer (${{ matrix.label }})`), or
      build it only from matrix values written in the job's strategy.matrix.
    """
    found = jobs(stream)
    carriers: list[str] = []
    unread: list[str] = []
    for job, entry in found.items():
        name, body = entry["name"], entry["body"]
        assert isinstance(name, str) and isinstance(body, list)
        if "unread" in entry:
            unread.append(f"  {job}: {entry['unread']}")
            continue
        try:
            if carries(check, job, name, body):
                carriers.append(job)
        except Refused as e:
            unread.append(f"  {job}: {e}")
    if unread:
        return None, "\n".join(
            [
                f"ERROR: {ci} has a job whose name might be {check!r}"
                " and cannot be read:",
                *unread,
                "  A check of that name is read as the commit's verdict, so"
                " a job that",
                "  might carry it must be shown not to. Give the name a"
                " literal part",
                f"  that rules {check!r} out (`sanitizer"
                " (${{ matrix.label }})`), or",
                "  build it only from matrix values written in the job's"
                " strategy.matrix.",
            ]
        )
    if not carriers:
        return None, (
            f"ERROR: {ci} has no job named {check!r} (CI_CHECK_NAME).\n"
            "  The aggregator is what turns a skipped matrix into a pass."
        )
    if len(carriers) > 1:
        return None, (
            f"ERROR: {ci} has more than one job that can be named"
            f" {check!r}:\n  {' '.join(carriers)}\n"
            "  Each reports a check of the required name on the same"
            " commit,\n"
            "  and a ruleset may read whichever is newest. Keep one."
        )
    agg = carriers[0]
    name, when = found[agg]["name"], found[agg]["if"]
    assert isinstance(name, str) and isinstance(when, str)
    why = refusal(check, name, when)
    if why is None:
        return agg, ""
    return None, (
        f"ERROR: {ci}: job '{agg}' is not a safe {check!r} gate: {why}\n"
        f"  A check named {check!r} is read as the commit's verdict,"
        " so it must\n"
        "  exist only where the full gate ran. A job whose if: is false"
        " still\n"
        "  reports -- a SKIPPED check, which branch protection counts as"
        " passing --\n"
        "  so the aggregator's if: is exactly always(): an absent if: is"
        " success(),\n"
        "  which SKIPS it when a need fails. A name expression must be\n"
        f"    ${{{{ <cond> && '{check}' || <cond> && '<other>' || "
        "'<fallback>' }}\n"
        f"  with '{check}' only in the first branch, every other value"
        " a\n"
        "  different string literal, and no parentheses or other operators."
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--check-name", required=True, help="CI_CHECK_NAME")
    p.add_argument("--file", required=True, help="the ci.yml, for messages")
    a = p.parse_args(argv)
    agg, why = gate(a.check_name, a.file, sys.stdin.read().splitlines())
    if agg is None:
        print(why)
        return 1
    print(f"AGG {agg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
