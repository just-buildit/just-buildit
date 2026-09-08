"""_version.py — resolving a `dynamic = ["version"]` project's version.

gh-28. PEP 621 lets a project list ``version`` in ``[project] dynamic`` so the
build back-end computes it. just-buildit did not consult ``dynamic`` at all, so
``[project] version`` had to be a literal — a tracked file every commit has to
edit. The cost is not cosmetic: a package index refuses a duplicate filename,
so a re-used version is a rejected upload, which means *every* PR must bump it
and any two open PRs conflict on every file that carries a copy.

A derived version removes the carrier entirely: nothing to bump, nothing to
conflict on, and no way to forget.

Where the value comes from
--------------------------
One source, declared as ``[tool.just-buildit] version-from = "vcs"``, resolved
in two steps:

1. **``PKG-INFO`` beside ``pyproject.toml``.** Its presence *is* the statement
   "this tree is an unpacked sdist", and the version recorded in it is that
   artifact's identity. Checked first, and deliberately so: an sdist unpacked
   inside some other checkout must not pick up that checkout's tags, and a
   wheel built from an sdist must carry the same version the sdist did.

2. **``git describe``.** The nearest ``v*`` tag, plus the distance from it.

That order is what makes the round trip closed. `_sdist` writes the resolved
version into the ``PKG-INFO`` it packs, so a sdist built from a git checkout
carries a concrete number, and the wheel built from that sdist reads it back
rather than needing a repository that is no longer there.

The shape of a derived version
------------------------------
=========================  ===============
git state                  version
=========================  ===============
exactly on tag ``v1.1.3``  ``1.1.3``
5 commits past it          ``1.1.4.dev5``
5 commits past ``v1.1.3-rc1``  ``1.1.3rc2.dev5``
=========================  ===============

Commits past a tag name the release they are working **toward**, never the one
already made. gh-29: this first shipped as ``1.1.3.dev5``, which inverts the
meaning of the segment — ``.devN`` marks a pre-release *of* the version it
names, so that string announces "on the way to 1.1.3" in the one state where
1.1.3 has already been tagged, and sorts below the tag it came after. There is
no workflow in which that reading is right; it was a mistake, not a trade-off.

A tag is PARSED, never string-edited: `_VERSION_RE` is PEP 440's own
grammar, so every spelling the spec makes equivalent resolves to the same
version -- `alpha`/`beta`/`c`/`pre`/`preview`, `rev`/`r`, the bare `-N` post
shorthand, any of `.`/`-`/`_` as a separator, any case, and an omitted
numeral meaning 0. What is emitted is always the canonical form: the tag's
spelling is an input, never the output, because the output becomes a wheel
filename and a requirement string.

Erroring rather than guessing
-----------------------------
PEP 621 is explicit that a back-end "MUST raise an error if the metadata
specifies a key in ``dynamic`` but the build back-end was unable to determine
the data". So an untagged repository, a missing ``git``, and a tree that is
neither a checkout nor an sdist are all errors here, each naming the two ways
out. Falling back to a placeholder such as ``0.0.0`` would upload one.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from pathlib import Path

#: The only `version-from` source implemented. A path-based source (reading
#: `__version__` out of a module) is a reasonable second one, but it is not
#: added speculatively: it does not reach zero carriers, which is the whole
#: point of gh-28, so it waits for someone who wants that trade-off.
VCS = "vcs"

#: Tags a release is expected to carry. Anchored on a digit after the `v` so a
#: `vendor-freeze` style tag is not mistaken for a version.
_TAG_GLOB = "v[0-9]*"

#: `git describe --long` output: `<tag>-<distance>-g<sha>`. The tag itself may
#: contain hyphens (`v1.1.3-rc1`), so the two trailing fields are what anchor
#: this, not a split on the first hyphen.
_DESCRIBE_RE = re.compile(r"^(?P<tag>.+)-(?P<distance>\d+)-g[0-9a-f]+$")

#: `Version:` in a PKG-INFO header. Anchored at column 1: the same word appears
#: indented inside the long description an sdist also packs.
_PKG_INFO_VERSION_RE = re.compile(r"^Version:[ \t]*(?P<ver>\S+)", re.M)


class VersionError(ValueError):
    """A dynamic version that could not be determined.

    A distinct type so a caller can tell "this project asked for a derived
    version and we could not derive one" from "this pyproject.toml is
    malformed" — they have different fixes.
    """


def _from_pkg_info(project_root: Path) -> str | None:
    """Return the version a sibling ``PKG-INFO`` records.

    None when there is no such file — this tree is not an unpacked sdist.
    """
    path = project_root / "PKG-INFO"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = _PKG_INFO_VERSION_RE.search(text)
    return match.group("ver") if match else None


def _git(project_root: Path, *args: str) -> str | None:
    """Run git in *project_root*; None if it fails or is not installed."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


#: PEP 440's own grammar, from the specification's appendix, with the
#: normalising alternatives it requires a tool to accept: `alpha`/`beta`/`c`/
#: `pre`/`preview` beside `a`/`b`/`rc`, `rev`/`r` beside `post`, `.`/`-`/`_`
#: or nothing as separators, the bare `-N` post-release shorthand, and the
#: leading `v` the spec says "MUST be ignored for all purposes".
#:
#: A grammar rather than a string edit, and that is the point. The first
#: version of this bumped "the last run of digits", which cannot see that
#: `1.1.3a` MEANS `1.1.3a0` -- so it bumped the release and produced
#: `1.1.4a.dev3` for a commit that is plainly the first alpha's successor.
#: Nor could it normalise, so `v1.1.3-rc1` and `v1.1.3ALPHA2` reached the
#: wheel FILENAME verbatim, as `1.1.3_rc2.dev3` and `1.1.3ALPHA3.dev3`.
_VERSION_RE = re.compile(
    r"""
    ^\s*v?
    (?:(?P<epoch>[0-9]+)!)?
    (?P<release>[0-9]+(?:\.[0-9]+)*)
    (?:[-_.]?(?P<pre_l>alpha|a|beta|b|preview|pre|c|rc)[-_.]?
        (?P<pre_n>[0-9]+)?)?
    (?:(?:-(?P<post_n1>[0-9]+))
        |(?:[-_.]?(?P<post_l>post|rev|r)[-_.]?(?P<post_n2>[0-9]+)?))?
    (?P<dev_marker>[-_.]?dev[-_.]?(?P<dev_n>[0-9]+)?)?
    (?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: The spellings the spec makes equivalent, mapped to their normal form.
_PRE_NORMAL = {
    "alpha": "a",
    "a": "a",
    "beta": "b",
    "b": "b",
    "c": "rc",
    "pre": "rc",
    "preview": "rc",
    "rc": "rc",
}


class _Version(NamedTuple):
    """A tag parsed into PEP 440's segments.

    `pre` is a ``(letter, number)`` pair with the letter already normalised;
    `post` and `dev` are their numbers. An omitted numeral is **0**, not
    absent -- the spec says so for all three -- and that is exactly the
    distinction a string edit cannot make.
    """

    epoch: int
    release: tuple[int, ...]
    pre: tuple[str, int] | None
    post: int | None
    dev: int | None
    local: str | None


def _parse(text: str) -> _Version | None:
    """Parse *text* as a PEP 440 version, or None if it is not one."""
    match = _VERSION_RE.match(text)
    if match is None:
        return None
    pre = None
    if match.group("pre_l") is not None:
        pre = (
            _PRE_NORMAL[match.group("pre_l").lower()],
            int(match.group("pre_n") or 0),
        )
    post = None
    if match.group("post_n1") is not None:
        post = int(match.group("post_n1"))
    elif match.group("post_l") is not None:
        post = int(match.group("post_n2") or 0)
    dev = None
    if match.group("dev_marker") is not None:
        dev = int(match.group("dev_n") or 0)
    local = match.group("local")
    return _Version(
        epoch=int(match.group("epoch") or 0),
        release=tuple(int(n) for n in match.group("release").split(".")),
        pre=pre,
        post=post,
        dev=dev,
        local=(
            local.lower().replace("-", ".").replace("_", ".")
            if local
            else None
        ),
    )


def _render(version: _Version) -> str:
    """Render *version* in PEP 440's canonical form.

    ``[N!]N(.N)*[{a|b|rc}N][.postN][.devN]`` -- what every other tool writes,
    so a filename or a requirement built from it matches everyone else's.
    """
    out = f"{version.epoch}!" if version.epoch else ""
    out += ".".join(str(n) for n in version.release)
    if version.pre is not None:
        out += f"{version.pre[0]}{version.pre[1]}"
    if version.post is not None:
        out += f".post{version.post}"
    if version.dev is not None:
        out += f".dev{version.dev}"
    if version.local is not None:
        out += f"+{version.local}"
    return out


def _bump(version: _Version) -> _Version:
    """Return the release *version*'s commits are working toward.

    The trailing segment is what a further commit moves past, so that is what
    is incremented -- the pre-release number if there is one, else the
    post-release number, else the last release component:

    ===============  ===============
    tag              next
    ===============  ===============
    ``1.1.3``        ``1.1.4``
    ``1.1.3a1``      ``1.1.3a2``
    ``1.1.3a``       ``1.1.3a1``     (the omitted numeral is 0)
    ``1.1.3.post1``  ``1.1.3.post2``
    ===============  ===============

    Bumping the *release* would be wrong for every row but the first:
    ``1.1.3.dev5`` sorts below ``1.1.3a1``, because a ``.dev`` segment
    precedes every pre-release of the same version.
    """
    if version.pre is not None:
        letter, number = version.pre
        return version._replace(pre=(letter, number + 1))
    if version.post is not None:
        return version._replace(post=version.post + 1)
    release = (*version.release[:-1], version.release[-1] + 1)
    return version._replace(release=release)


def _from_git(project_root: Path) -> str | None:
    """``git describe`` turned into a PEP 440 version, or None.

    None means "no answer from git" — not a repository, git not installed, or
    no matching tag. The caller turns that into the error, because only it
    knows that `PKG-INFO` did not answer either.
    """
    described = _git(
        project_root, "describe", "--tags", "--long", "--match", _TAG_GLOB
    )
    if described is None:
        return None
    match = _DESCRIBE_RE.match(described)
    if match is None:
        return None
    tag = match.group("tag")
    distance = int(match.group("distance"))

    parsed = _parse(tag)
    if parsed is None:
        raise VersionError(
            f"the nearest tag is {tag!r}, which is not a PEP 440 version, so "
            "no version can be derived from it.\n"
            "Tag a release -- 'v1.2.3', or a pre-release such as 'v1.2.3a1' "
            "/ 'v1.2.3rc1'."
        )
    if parsed.dev is not None or parsed.local is not None:
        # Raised, not returned as None. None means "git had no answer", and
        # the caller turns that into a message about a MISSING tag -- which
        # would send someone hunting for the tag they are looking straight at.
        raise VersionError(
            f"the nearest tag is {tag!r}, which cannot be the base of a "
            "derived version.\n"
            "A tag carrying a '.dev' segment would give a version with two of "
            "them (not a valid PEP 440 version), and one carrying a local "
            "'+' segment would put the commit distance inside the local part, "
            "where it orders nothing and where PyPI will not accept it.\n"
            "Tag a release instead -- 'v1.2.3', or a pre-release such as "
            "'v1.2.3a1' / 'v1.2.3rc1', all of which derive correctly."
        )

    # Canonical either way: the tag's own spelling is an input, never the
    # output. `v1.1.3-rc1` and `v1.1.3ALPHA2` are the same versions as
    # `1.1.3rc1` and `1.1.3a2`, and emitting them verbatim put a
    # non-canonical string into the wheel FILENAME.
    if distance == 0:
        return _render(parsed)
    # Commits PAST a tag are work toward the NEXT release, so the version they
    # carry must name that one. Appending `.dev` to the tag itself named the
    # release already made, inverting the meaning of the segment and sorting
    # the build below the tag it came after. See `_bump`.
    return _render(_bump(parsed)._replace(dev=distance))


def resolve(project_root: Path, source: str | None) -> str:
    """Return the version for a project that lists ``version`` in ``dynamic``.

    Parameters
    ----------
    project_root : Path
        The directory holding ``pyproject.toml``.
    source : str or None
        ``[tool.just-buildit] version-from``. Required — PEP 621 asks the
        back-end to determine the value, and an unstated source is not a
        determination.

    Returns
    -------
    str
        A concrete version string.

    Raises
    ------
    VersionError
        If no source is declared, the source is unrecognised, or the version
        could not be determined from it.

    Examples
    --------
    From a checkout sitting five commits past ``v1.1.3``::

        $ git describe --tags --long --match 'v[0-9]*'
        v1.1.3-5-gc0ffee0
        $ python -c "from pathlib import Path
        > from just_buildit._version import resolve
        > print(resolve(Path('.'), 'vcs'))"
        1.1.4.dev5
    """
    if source is None:
        raise VersionError(
            "[project] dynamic lists 'version', but "
            "[tool.just-buildit] version-from is not set, so there is "
            "nothing to derive it from.\n"
            f'Add:\n\n    [tool.just-buildit]\n    version-from = "{VCS}"\n\n'
            "or give [project] a literal version and drop 'version' from "
            "dynamic."
        )
    if source != VCS:
        raise VersionError(
            f"[tool.just-buildit] version-from = {source!r} is not a source "
            f"just-buildit knows. The only supported value is {VCS!r} "
            "(nearest v* git tag, falling back to a sdist's PKG-INFO)."
        )

    from_sdist = _from_pkg_info(project_root)
    if from_sdist is not None:
        return from_sdist

    from_git = _from_git(project_root)
    if from_git is not None:
        return from_git

    raise VersionError(
        "[project] dynamic lists 'version' with version-from = "
        f"{VCS!r}, but the version could not be determined.\n"
        f"  - no PKG-INFO in {project_root} (so this is not an unpacked "
        "sdist), and\n"
        f"  - `git describe --tags --match '{_TAG_GLOB}'` gave no answer "
        "(not a git checkout, git not installed, or no matching tag yet).\n"
        "Tag a release (`git tag v0.1.0`), or give [project] a literal "
        "version and drop 'version' from dynamic."
    )
