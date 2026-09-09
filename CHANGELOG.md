# Changelog

## [Unreleased]

### Added

- **`just-buildit --next-version` prints the version the next release would
    carry (#34).** Deriving the version removes it from every tracked file,
    which is the point of #28 -- and the reason CI then has nothing to read it
    out of: no `[project] version` to grep, no file for a version check to
    probe. A release job's only options were to re-implement `git describe`
    parsing in shell, free to disagree with the wheel the build produces, or
    to reintroduce the carrier the dynamic version had just deleted.

    It invents no policy, and that is the argument for it. A build five
    commits past `v1.1.3` is already called `1.1.4.dev5`, and `.devN` means
    "on the way to" -- so that build already names 1.1.4 as the next release.
    The query reports the same number with the `.devN` removed, from the same
    parse of the same tag: `_describe` was split out of `_from_git` so the two
    readings cannot drift into disagreeing about which tag is nearest or
    whether it is usable. A test asserts the equality directly.

    Bare on stdout, so `VERSION=$(just-buildit --next-version)` works, with
    every diagnostic on stderr and a non-zero exit -- a failed query must not
    be capturable and pushable as a tag.

    It refuses rather than guesses in the two cases with no answer: a literal
    `[project] version` (which digit a release bumps is a judgement, not a
    fact about the repository) and a repository with no tag yet. Deliberately
    asymmetric with the build's own version, which consults a sibling
    `PKG-INFO` first: "what comes next" is a question about a repository's
    history, and an sdist has neither tags nor a future.

### Changed

- **Re-vendored `standard.mk` to pick up `INSTALL_DEPS_CMD`
    (just-buildit.github.io#37).** The two-line `install-deps` recipe becomes
    `$(INSTALL_DEPS_CMD)`, backed by a canned recipe whose default is the
    previous fetch verbatim. This repo sets no override, so it takes the
    default and nothing about `make install-deps` changes here.

    The hook exists for the repo that OWNS the script the target fetches:
    just-bashit runs `src/just_bashit/install-deps.sh` in CI while
    `make install-deps` ran the *published* copy, so one step had two
    execution homes and the source under development was never the thing
    exercised locally. Overriding the command is the fix; a private copy of
    the target would be the same drift in a different file.

    Fetched with `make standard-update` rather than a hand-run curl.
    `scripts/release-watch.sh`, the other `VENDORED_FILES` entry, was
    re-fetched and matched, so only `standard.mk` moved.

- **`make help` files every standard target, and a gate says so
    (just-buildit.github.io#38).** `gates-home-check` was in `STD_TARGETS`
    with a recipe and a description, and every gate passed -- yet `help`
    listed it under **Local**, because `_STD_SECTION` had no matching arm and
    the fallthrough is Local by design. The standard was advertising a shared
    target as repo-specific.

    Upstream fixed both halves: the target joins the Aggregates arm beside
    `gates` and `gates-check`, and `help-check` gained a third direction --
    every `STD_TARGETS` member must resolve to a section other than Local.
    Registration-free, so a future standard target added without a menu arm
    fails here on the next `make lint` with no list to maintain.

    Visible here as `gates-home-check` moving from Local to Aggregates in
    `make help`. The `help-check` success line gained a second count, the
    number of standard targets it filed, so the added half cannot pass by
    staying silent.

## [0.4.0] — 2026-09-09

### Added

- **`dynamic = ["version"]` is honoured, so the version can be derived at
    build time (#28).** `dynamic` was consulted nowhere in `_meta`, so
    `[project] version` had to be a literal -- a tracked file every commit has
    to edit. That is not cosmetic: a package index refuses a duplicate
    filename, so a re-used version is a rejected upload, which means every PR
    must bump it and any two open PRs conflict on every file carrying a copy
    whatever they actually changed.

    Declare a source with `[tool.just-buildit] version-from = "vcs"`. It
    resolves a sibling `PKG-INFO` first, then `git describe`: on tag `v1.1.3`
    gives `1.1.3`, five commits past it gives `1.1.3.dev5`, and an unpacked
    sdist with no `.git` gives whatever its `PKG-INFO` records. `PKG-INFO`
    first is what closes the round trip -- an sdist built from a checkout
    carries a concrete number, so the wheel built from that sdist agrees with
    it without needing a repository that is no longer there, and an sdist
    unpacked inside an unrelated checkout cannot take that checkout's tags.

    Four refusals, all PEP 621's rather than house style: `name` in `dynamic`,
    `version` given both statically and dynamically, a `dynamic` that is not a
    list, and a field listed in `dynamic` that cannot be determined. That last
    one is deliberately an error rather than a `0.0.0` placeholder, which
    would upload a wrong version instead of failing the build. A project that
    says nothing about `dynamic` behaves exactly as before.

    A derived version names the release its commits are working **toward**:
    five commits past `v1.1.3` is `1.1.4.dev5`, and five past `v1.1.3-rc1` is
    `1.1.3-rc2.dev5`. Each one therefore sorts strictly after the tag it
    followed and strictly before the release it anticipates (#29 -- this
    briefly read `1.1.3.dev5` on the branch, which inverted the meaning of the
    `.dev` segment; it never reached a release).

    Pre-release phases are reached by **tagging** them: `v1.1.3a1` derives
    `1.1.3a1`, and commits past it derive `1.1.3a2.dev3`. Tags are parsed with
    PEP 440's own grammar rather than string-edited, so every spelling the
    spec makes equivalent (`alpha`/`beta`/`c`/`pre`/`preview`, `rev`/`r`, the
    bare `-N` post shorthand, `.`/`-`/`_` separators, any case, an omitted
    numeral meaning 0) gives the same version -- and what is emitted is always
    the canonical form, since it becomes a wheel filename and a requirement
    string. A tag already
    carrying a `.dev` segment, or a local `+` segment, is refused by name --
    the first would produce a version with two `.dev` segments (not valid PEP
    440), and the second would bury the commit distance in the local part,
    where it orders nothing and PyPI will not accept it.

### CI

- **`make test` discovers test modules from the tree instead of a
    hand-maintained list.** `_TEST_MODULES` named each module explicitly --
    the same second copy the comment above it warns about -- so a new
    `tests/test_*.py` was run by neither `make test` nor CI, and nothing said
    so. #28's tests sat unrun that way until the target was compared against
    `ls tests/`. The only way to keep a file out is now to name it in
    `_TEST_EXCLUDE`; `test_pypi` is the one, because it exercises the
    published package and so tests the last release rather than the branch.

- **`make test` no longer inherits the shell's virtualenv.** `uv run   --no-project` still honours an ACTIVE virtualenv, so the target tested
    against whatever the developer happened to have installed while CI tested
    against the Makefile line alone -- the same command giving two answers. An
    undeclared `packaging` import passed locally for exactly that reason and
    then failed on all 24 CI legs. The runner now unsets `VIRTUAL_ENV` and
    declares `packaging`, so the local command is the command CI runs.

## [0.3.12] — 2026-09-02

### Fixed

- **The sdist no longer carries `_build/` output.** `_EXCLUDE_DIRS` had
    `build` and `dist` but not the underscore spelling, so building an sdist
    in a tree where anything had been compiled swept the artifacts in. This
    affects **every project that uses just-buildit as its backend**, not just
    this repo — `_build` is the conventional name for cmake, meson and Sphinx
    output. Measured here: a local 0.3.11 sdist carried 92 entries under
    `examples/`, 62 of them object files, ninja logs and meson caches; the
    published one carried 30, because CI builds from a fresh checkout — which
    is precisely why the release path could not see this. (#25)
- `tests/test_sdist_excludes.py` builds an sdist over a tree that contains
    build output at top level *and* nested inside an example, then asserts
    none of it appears and that real source still does. The exclusion list is
    a list of names, so the only way to know it covers a directory is to put
    that directory in a tree and build from it; asserting on the constant
    would have passed for the value that shipped the bug.

### CI

- `changelog-check` now has an execution home in `lint`, so a release tag
    without a CHANGELOG section, or work in flight without an `[Unreleased]`
    one, fails CI. It found five tags with no section on its first run
    (v0.1.0, v0.2.2-v0.2.5); those are ratcheted in `.changelog-allow`, which
    may only shrink — and a stale entry, a listed tag that has since gained a
    section, fails too. (#20)
- The `lint` job checks out with `fetch-depth: 0`. `actions/checkout` fetches
    no tags, so the per-tag scan would have run over an empty set and reported
    success; the gate refuses on zero tags rather than reading silence as a
    pass.
- Corrected the sdist figure in 0.3.11's notes above. It was measured on a
    local build over a tree where the example tests had run, and `_sdist.py`
    excludes `build` but not `_build` — so 62 of the 92 `examples/` entries
    quoted were object files and ninja logs. The published sdist has none,
    because CI builds from a fresh checkout. (#25)
- `bump-version` runs `uv lock`, and `uv.lock` joined `VERSION_PROBES`. The
    lock pins this project's own version, so a bump that touched only
    `pyproject.toml` left a tree that would not commit. (#21)

## [0.3.11] — 2026-09-01

`src/just_buildit/` is byte-identical to 0.3.10, so the **wheel** differs only
in its version metadata. This release publishes an **sdist** for the first
time, which is what actually carries the examples work below to PyPI — the
release path had only ever built a wheel, so nothing outside
`src/just_buildit/` had ever reached a consumer at any version.

### Fixed

- **Examples now build for the interpreter just-buildit targets**, instead
    of letting their build system search for one. just-buildit tells every
    build which interpreter it is building *for* (`JUST_BUILDIT_PYTHON`,
    `JUST_BUILDIT_INCLUDE_DIR`); two examples took neither.
    - `examples/cmake` was the dangerous half: its
        `find_package` call for `Development.Module` compiled against the
        *system* headers while the example forced `SUFFIX` from
        `JUST_BUILDIT_EXT_SUFFIX` — producing a right-named, wrong-ABI
        extension that built cleanly and failed at import. It takes
        `Python3_INCLUDE_DIR` from `JUST_BUILDIT_INCLUDE_DIR` now. Setting
        `Python3_EXECUTABLE` alone does not fix it: `Development.Module`
        looks for headers.
    - `examples/meson` built a `.cpython-314-*.so` when 3.12 was the
        target, and failed as "Build produced no extension" — pointing at
        the copy step rather than the interpreter. `meson.build` cannot
        read the environment, so it takes a `python_path` option that the
        Makefile passes through, defaulting to `python3` so the example
        still runs standalone.
    - Covered by a static, per-example gate. Static because CI cannot see
        this class at all — there the default `python3` *is* the
        interpreter under test, so the two can never disagree; it only
        appears where they differ, which is every machine with a venv.
- `make test` could not pass in this repo while CI was green: the Makefile
    omitted the `--with pip --with numpy` that ci.yml supplied, so
    `TestJustMakeitExample` failed in `setUpClass`. The test command now
    exists once.

### Changed

- Adopted the cross-org `standard.mk`: 135 lines that reimplemented
    thirteen of its fourteen targets by hand are now configuration plus
    `include standard.mk`. `help` is generated from each rule's
    description (29 targets, up from the 14 listed by hand).
- Two target renames, neither of which anything in this repo invoked:
    `make build` → `make wheel`, and `make check-version` →
    `make version-check`.

### Added

- **The release now publishes an sdist.** `release.yml` built
    `uv build --wheel` and nothing else, so PyPI received a wheel containing
    only `just_buildit/` — 17 entries — and everything else in the repo,
    `examples/` above all, reached no consumer at any version. The published
    0.3.11 sdist carries 30 files under `examples/` and 12 under `docs/`,
    verified by downloading it from PyPI.
    The smoke job now asserts the sdist carries the tree and that it builds,
    because an sdist that is published but never installed is an unchecked
    artifact. (#19)

### Docs

- **`docs/examples.md` taught the bug this release fixes.** Its cmake and
    meson snippets were hand-copied from the example files and never updated,
    so a reader following the CMake page got
    `find_package(Python3 COMPONENTS Development.Module)` with no header hint
    — the exact configuration that produces a right-named, wrong-ABI
    extension. The meson page had the bare `find_installation()`, its Makefile
    snippet was missing `-Dpython_path=`, and `meson_options.txt` was not
    documented at all. All three snippets now match the files they claim to
    show, verified needle-by-needle against those files rather than by eye.

### CI

- **Added a `lint` job. There was none** — every pre-commit hook, every
    drift gate and every check in `make lint` ran on no pull request,
    which is worse than not having them, because the repo reads as gated.
- Added the `CI passed` aggregate check that `main`'s ruleset requires.
    No job produced it, so every pull request sat at
    `mergeable_state=blocked` with zero failing and zero pending — the
    repository could not merge at all, and it read as ordinary CI
    slowness.
- ci.yml calls `make test` rather than restating the test command, which
    is how the two drifted in the first place.
- Vendored canonical's `release-watch.sh`. The release path had no
    watcher: `tag-release` pushed the tag and stopped, with nothing
    following the run, recovering a pre-publish flake, or verifying that
    PyPI and the GitHub Release carried the version.
- pre-commit hooks dispatch inward to `make lint-<tool>`, with tool
    versions in the dev dependency group rather than upstream mirror
    `rev:` pins — so the hook and `make format` can no longer format
    differently. Verified to change no formatting.
- `.vscode/settings.json` is no longer tracked. It pinned
    `cmake.sourceDirectory` to one machine's `$HOME`.

## [0.3.10] — 2026-07-14

### CI

- Added Linux aarch64 (`ubuntu-24.04-arm`, native GitHub runner) to the
    `ci.yml`/`release.yml` test matrix — no longer x86-64-Linux/arm64-macOS
    only.
- Added a `Makefile` with the standard target set (`test`, `test-fast`,
    `lint`, `build`, `docs`, `docs-serve`, `setup`, `bump-version`,
    `check-version`, `release-branch`, `tag-release`, `clean`, `help`).
- `release.yml`: added a `smoke` job (fresh-venv wheel install + version
    check + CLI smoke) between `build` and `publish`; added a
    `github-release` job that extracts the CHANGELOG section for the tag
    and creates a GitHub Release.
- Bumped GitHub Actions to node24-compatible versions
    (`checkout@v6.0.2`, `setup-uv@v8.1.0`, `upload-artifact@v7.0.1`,
    `download-artifact@v8.0.1`) ahead of GitHub's node20 deprecation.
- Fixed macOS CI: `setup-uv@v8` fell back to the Xcode system Python (no
    `Python.h`) for `uv run --no-project`; pinned the interpreter
    explicitly and forced `UV_PYTHON_PREFERENCE=only-managed`.
- Added a guarded `workflow_dispatch` dry-run to `release.yml` to verify
    the full test + build matrix before cutting a tag (never touches
    PyPI).
- Added a `trigger-mirror` job that dispatches an immediate refresh to
    `just-buildit.github.io`'s mirror workflow on push to `main`, instead
    of waiting for its daily cron.
- Added `.pre-commit-config.yaml` — ruff (lint + format) and mdformat,
    matching the rest of the toolchain. `mypy` is configured in
    `pyproject.toml` (`[tool.mypy]`) for manual/CI use but intentionally
    not run via pre-commit.

### Fixed

- `run_repair`'s `repair_command` parameter was typed as `bool` instead
    of `Literal[False]`, letting it silently accept `True` — never a
    legal value. Caught by bringing the codebase to a clean
    `mypy --strict` pass, which also fixed a handful of missing PEP 517
    hook annotations and a `str`/`bool` type mismatch in `_meta.py`'s
    `repair` handling.

### Docs

- `configuration.md`: the editable-install fallback claim was wrong —
    `build_editable` raises `RuntimeError` when no editable source root
    is found; it does not silently fall back to a full wheel build.
- `environment-variables.md`: `SOURCE_DATE_EPOCH`'s documented default
    was "current time"; it's actually a fixed `315532800` (1980-01-01
    UTC) — builds are reproducible by default, with no configuration
    needed.
- `contributing.md`: the test command was missing `tests.test_metadata`;
    the platform-support table now accurately reflects CI coverage
    (including aarch64); rewrote the "Releasing" checklist with the
    workflow lessons learned (bump via PR, tag `origin/main` not a local
    commit, never re-push a tag after a successful publish).
- `docs/index.md` (the published docs homepage) was missing the
    just-makeit scaffold link that `README.md` already had.
- `docs/llms.txt`: fixed a description that mischaracterized
    just-buildit as CMake-specific — it's build-system-agnostic — and
    added the file itself for AI/search discoverability.

______________________________________________________________________

## [0.3.9] — 2026-06-04

### Added

- Support for Python 3.8, 3.9, and 3.10 — the minimum supported version is now
    **3.8**, down from 3.11. `pyproject.toml` is parsed with stdlib `tomllib` on
    3.11+ and a vendored copy of `tomli` (MIT, under `_vendor/`) on older
    versions, so just-buildit stays dependency-free on every supported Python.

### Changed

- `requires-python` lowered to `>=3.8`; classifiers, examples, and docs updated
    to match.
- CI and release matrices now test Python 3.8–3.14. The `just-makeit`
    integration job stays on 3.11+, which that tool requires.

______________________________________________________________________

## [0.3.8] — 2026-06-02

### Fixed

- Wheels and sdists were missing `Requires-Dist`, `Provides-Extra`, `License`,
    `Author`, `Maintainer`, and `License-File` headers — `license`, `authors`,
    `maintainers`, and `optional-dependencies` from `[project]` were parsed by
    `_meta.load` but never wired through to `_metadata_bytes`. All six header
    types now appear correctly in built wheel and sdist METADATA.
- Added `tests/test_metadata.py` — 54 unit and integration tests covering every
    PEP 621 metadata field that just-buildit maps to wheel METADATA.

______________________________________________________________________

## [0.3.7] — 2026-05-23

### Docs

- `configuration.md`: added `repair-args` to the full reference block; added admonitions explaining package-name normalization, `.c`/`.h` exclusion behaviour, the `pure`+`command` conflict error, editable-install auto-detection, and the fallback-to-full-build warning
- `environment-variables.md`: split into "set by" and "read by" sections; added `CC` and `SOURCE_DATE_EPOCH` to the "read by" table; added admonitions for output-directory usage, link-order pitfall, `CC` override tip, and reproducible-builds note; center-aligned value columns in the link-flags table
- `examples.md`: updated just-makeit section file tree to match v0.13.7 scaffold output (added Doxyfile, zensical.toml, docs/, cmake config files, benchmarks, jm_bench.h, `__init__.py` files); noted `jm apply` regeneration step
- `posts/python-c-extensions-shouldnt-be-this-hard.md`: corrected `--component` → `--object` in both code examples
- `zensical.toml`: removed explicit `markdown_extensions` override that was shadowing Zensical's full default set — admonitions, `attr_list`, `pymdownx.details`, and all other defaults now apply correctly

______________________________________________________________________

## [0.3.6] — 2026-05-19

### Added

- `pure` option in `[tool.just-buildit]` — declares a pure-Python package: just-buildit compiles nothing, copies the `src/{package}/` tree verbatim (keeping `.c`/`.h` files as package data), tags the wheel `py3-none-any`, and skips wheel repair. For pure-Python packages that ship `.c` sources as data, where the zero-config build would otherwise try to compile them.
- `TestPureBuild` integration tests and a `fixture_pure/` test fixture (ships an uncompilable `sample.c` to prove pure builds never invoke the compiler)

### Changed

- `[tool.just-buildit]` rejects setting both `pure` and `command` — `pure` means "compile nothing", so a build command is contradictory

______________________________________________________________________

## [0.3.5] — 2026-05-10

### Added

- MinGW UCRT64 example (`examples/mingw/`) — explicit Makefile build demonstrating `JUST_BUILDIT_LIBS` placement after `-o` on Windows
- `TestMinGWExample` (Windows-only) and `TestJustMakeitExample` integration tests
- CI `test-just-makeit` job: scaffolds a project with `just-makeit new`, verifies layout, builds wheel, and smoke-tests `my_dsp.Gain`

### Fixed

- `examples/meson/meson.build`: added `build_by_default: true` — without it, `install: false` implies `build_by_default: false` since Meson 0.38, causing ninja to produce no output
- `examples/meson/Makefile`: changed `--reconfigure` to `--wipe` so a clean configure is forced each build
- CI `test` job: install meson via `uv tool install meson` instead of `apt-get install meson` — apt meson 1.3.x silently produces no build targets when `find_installation()` encounters a uv-managed Python path

### Docs

- `examples.md` overhauled: every section now shows actual runnable code from `examples/`, browse links, prerequisite lists, and `pip install` smoke-test commands
- `environment-variables.md`: corrected `JUST_BUILDIT_LDFLAGS` for Windows/MinGW — it is `-shared` (not `-shared -fPIC`); `-fPIC` is meaningless on Windows x64
- `examples.md` just-makeit section updated: `--component` → `--object`, config file is `just-makeit.toml`, layout tree reflects current scaffold output

______________________________________________________________________

## [0.3.4] — 2026-05-07

### Added

- `repair-args` config option in `[tool.just-buildit]` — accepts a list or string of extra arguments passed to the wheel repair command (e.g. `--plat manylinux_2_28_x86_64` for `auditwheel repair`)

______________________________________________________________________

## [0.3.3] — 2026-05-06

### Fixed

- Sdist `PKG-INFO` now includes classifiers, keywords, project URLs, and dependencies (previously only written into wheel `METADATA`)
- `__version__` now derived from installed package metadata instead of a hardcoded string

______________________________________________________________________

## [0.3.2] — 2026-05-06

### Fixed

- Classifiers, keywords, project URLs, and dependencies were parsed from `pyproject.toml` but never written into the wheel METADATA or sdist PKG-INFO — they now appear correctly on PyPI

______________________________________________________________________

## [0.3.1] — 2026-05-05

### Added

- PyPI metadata: keywords, classifiers (Python 3.11–3.14), project URLs (Homepage, Documentation, Changelog)
- README: just-makeit callout and cross-link for projects needing a CMake scaffold

______________________________________________________________________

## [0.3.0] — 2026-04-30

### Added

- Bazel example (`examples/bazel/`) — `genrule`-based build with a `build_ext.py` bridge script forwarding just-buildit env vars via `--action_env`
- Nested package example (`examples/nested/`) — recursive package tree with multiple extensions across subdirectories
- CLI integration tests (`tests/test_cli.py`) — 15 tests covering `inspect`, `build`, `sdist`, `help`, and error handling via subprocess
- CI: dedicated `test-bazel` job running the Bazel example across all Python versions

### Docs

- Env variable table split into platform-neutral and platform-specific sections
- Examples page updated with Bazel and recursive package tree sections
- Quickstart updated to call out flat, nested, multi-extension, and mixed layouts
- PyPI doc links updated to point to GitHub Pages

______________________________________________________________________

## [0.2.1] — 2026-04-15

### Breaking

- Renamed config section from `[tool.just-build]` to `[tool.just-buildit]`

______________________________________________________________________

## [0.2.0] — 2026-04-15

### Breaking

- Renamed Python module from `just_build` to `just_buildit`. Update your `pyproject.toml`:
    ```toml
    [build-system]
    requires = ["just-buildit"]
    build-backend = "just_buildit"   # was: just_build
    ```
- Renamed all environment variables from `JUST_BUILD_*` to `JUST_BUILDIT_*`. Update your Makefiles and build scripts:
    - `JUST_BUILD_NAME` → `JUST_BUILDIT_NAME`
    - `JUST_BUILD_PYTHON` → `JUST_BUILDIT_PYTHON`
    - `JUST_BUILD_INCLUDE_DIR` → `JUST_BUILDIT_INCLUDE_DIR`
    - `JUST_BUILD_OUTPUT_DIR` → `JUST_BUILDIT_OUTPUT_DIR`
    - `JUST_BUILD_EXT_SUFFIX` → `JUST_BUILDIT_EXT_SUFFIX`
    - `JUST_BUILD_LDFLAGS` → `JUST_BUILDIT_LDFLAGS`
    - `JUST_BUILD_LIBS` → `JUST_BUILDIT_LIBS`

### Added

- CLI entry point: `just-buildit inspect`, `just-buildit build [DIR]`, `just-buildit sdist [DIR]`
    - `inspect` shows parsed config, build mode, env vars, and predicted wheel filename without running anything
    - `build` builds a wheel into the given directory (default: `dist/`)
    - `sdist` builds a source distribution into the given directory (default: `dist/`)
- `build_sdist()` / `get_requires_for_build_sdist()` — PEP 517 sdist support

______________________________________________________________________

## [0.1.5] — 2026-04-03

### Fixed

- Don't delete the original wheel when the repair tool writes an output file with the same filename

______________________________________________________________________

## [0.1.4] — 2026-04-03

### Fixed

- Repair into a temp subdirectory to avoid a `PermissionError` on Windows when pip holds the source wheel open

______________________________________________________________________

## [0.1.3] — 2026-04-02

### Fixed

- MSYS2 Python 3.14: search `lib/` and check `.dll.a` suffix for link flags
- Windows native CPython link flags via `libs/python3X.lib`
- CI: release gate, example Makefile fixes

______________________________________________________________________

## [0.1.2] — 2026-04-02

### Added

- `editable_path` config option: `build_editable()` writes a `.pth` file instead of rebuilding, enabling instant `uv sync` for projects with C extensions compiled in place

______________________________________________________________________

## [0.1.1] — 2026-04-02

### Added

- Initial release on PyPI
- Zero-config `src/{package}/*.c` auto-discovery and compilation
- PEP 517 `build_wheel()` and `build_editable()`
- Platform auto-repair: auditwheel (Linux), delocate (macOS), delvewheel (Windows)
- Pure Python detection: no `*{ext_suffix}` in output → `py3-none-any` tags
