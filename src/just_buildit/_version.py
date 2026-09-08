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
5 commits past ``v1.1.3-rc1``  ``1.1.3-rc2.dev5``
=========================  ===============

Commits past a tag name the release they are working **toward**, never the one
already made. gh-29: this first shipped as ``1.1.3.dev5``, which inverts the
meaning of the segment — ``.devN`` marks a pre-release *of* the version it
names, so that string announces "on the way to 1.1.3" in the one state where
1.1.3 has already been tagged, and sorts below the tag it came after. There is
no workflow in which that reading is right; it was a mistake, not a trade-off.

`_bump_last_number` has the rule and why one rule covers a pre-release too.

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
from typing import TYPE_CHECKING

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


#: The last run of digits in a tag. What gets incremented to name the release
#: the current commits are working TOWARD, rather than the one already made.
_LAST_NUMBER_RE = re.compile(r"(?P<num>\d+)(?P<rest>\D*)$")


#: A tag that cannot be the BASE of a derived version, because appending a
#: `.devN` to it does not produce a well-formed one.
#:
#: Two shapes, both found by probing the alpha path rather than by reading the
#: code:
#:
#: - it already carries a ``.dev``. `v1.1.3.dev5` + 2 commits gave
#:   ``1.1.3.dev6.dev2``, which is not a PEP 440 version at all -- the failure
#:   would surface later, as a rejected upload or an unparseable requirement.
#: - it carries a local segment (``+``). `v1.1.3+local` gave
#:   ``1.1.4+local.dev3``, which *is* well-formed and is worse for it: the
#:   distance lands inside the LOCAL part, so every build past the tag compares
#:   equal on its public version and nothing can order them. PyPI refuses local
#:   versions outright.
#:
#: Neither is a release tag, so refusing is honest rather than restrictive --
#: and it is what PEP 621 asks for, the module docstring's "erroring rather
#: than guessing" applied to the tag instead of to its absence.
_UNBUMPABLE_RE = re.compile(r"(?i)(?:[-_.]?dev\d*|\+)")


def _bump_last_number(base: str) -> str | None:
    """Increment the trailing number of a version, naming the NEXT release.

    One rule, correct for a final release and a pre-release alike, because in
    both the trailing number is the thing a further commit moves past:

    =============  =============  ==============================
    tag            bumped         why
    =============  =============  ==============================
    ``1.1.3``      ``1.1.4``      the next patch
    ``1.1.3rc1``   ``1.1.3rc2``   the next release candidate
    ``1.1.3-rc1``  ``1.1.3-rc2``  same; PEP 440 normalises the ``-``
    =============  =============  ==============================

    Bumping the *release* instead would be wrong for the second row:
    ``1.1.3.dev5`` sorts BELOW ``1.1.3rc1``, because a ``.dev`` segment
    precedes every pre-release of the same version. Bumping the trailing
    number keeps each derived version strictly between the tag it followed and
    the release it anticipates.

    None when the tag carries no digits at all, which the ``v[0-9]*`` match
    glob already prevents; the caller reads that as "no answer from git".
    """
    if _UNBUMPABLE_RE.search(base):
        return None
    match = _LAST_NUMBER_RE.search(base)
    if match is None:
        return None
    start, end = match.span("num")
    return f"{base[:start]}{int(match.group('num')) + 1}{base[end:]}"


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
    base = tag[1:] if tag.startswith("v") else tag
    if not base:
        return None
    if distance == 0:
        return base
    # Commits PAST a tag are work toward the NEXT release, so the version they
    # carry must name that one. Appending `.dev` to the tag itself named the
    # release already made, which inverts the meaning of the segment and sorts
    # the build below the tag it came after. See `_bump_last_number`.
    upcoming = _bump_last_number(base)
    if upcoming is None:
        # Raised, not returned as None. None here means "git had no answer",
        # and the caller turns that into a message about a missing tag -- which
        # would send someone hunting for the tag they are looking straight at.
        raise VersionError(
            f"the nearest tag is {tag!r}, which cannot be the base of a "
            "derived version.\n"
            "A tag carrying a '.dev' segment would give a version with two of "
            "them (not a valid PEP 440 version), and one carrying a local "
            "'+' segment would put the commit distance inside the local part, "
            "where it cannot order anything and where PyPI will not accept "
            "it.\n"
            "Tag a release instead -- 'v1.2.3', or a pre-release such as "
            "'v1.2.3a1' / 'v1.2.3rc1', all of which derive correctly."
        )
    return f"{upcoming}.dev{distance}"


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
