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
======================  ==============
git state               version
======================  ==============
exactly on tag ``v1.1.3``  ``1.1.3``
5 commits past it          ``1.1.3.dev5``
======================  ==============

Note for anyone reading a published index: ``1.1.3.dev5`` sorts *before*
``1.1.3`` under PEP 440, because a ``.devN`` segment marks a pre-release of the
version it names rather than a successor to it. That is the documented,
requested mapping, and it is the right one for a project whose tag marks the
*end* of a series — but if these builds are ever published alongside the
release they follow, the release wins the resolution and the dev builds are
unreachable. gh-29 tracks offering the bump-the-patch alternative.

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
    return base if distance == 0 else f"{base}.dev{distance}"


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
        1.1.3.dev5
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
