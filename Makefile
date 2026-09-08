# just-buildit — configuration only.
#
# The shared targets are NOT written here. `standard.mk` is vendored from the
# cross-org standard (canonical: https://just-buildit.github.io/standard.mk)
# and this file is feature flags and command variables.
#
# It used to be 135 lines that reimplemented THIRTEEN of the standard's
# fourteen targets by hand -- including a hand-written `help` listing them,
# which is what let `make wheel` stay advertised in doppler after its rule was
# gone. `help` is generated from the `## description` on each rule now, so it
# cannot disagree with what exists.
#
# Two targets changed name in the move, and nothing called either one -- no
# workflow, README or doc invokes `make` in this repo:
#   make build         -> make wheel          (`build` is the native-library
#                                              target in the standard)
#   make check-version -> make version-check
#
# Never edit standard.mk or anything in VENDORED_FILES in place: the
# `standard-check` drift gate holds them to canonical byte-for-byte. Per-repo
# variation is a variable here; a shared change goes to canonical and comes
# back through the vendored copy.

HAS_PYTHON  = 1

# `test-all` has no second suite here, so `gates` depends on the one that
# exists. A gate naming a target no CI job runs is a gate with no execution
# home -- `gates-home-check` is what says so.
GATES_DEPS  = lint test
HAS_DOCS    = 1
HAS_RELEASE = 1

UV         = uv
DEV_RUN    = $(UV) run --group dev
SYNC_CMD   = $(UV) sync --group dev

# ── test ─────────────────────────────────────────────────────────────────────
# `--no-project` deliberately: the suite exercises the INSTALLED entry points
# rather than the working tree, so resolving this project into the environment
# would test something the user never runs.
#
# `--with pip --with numpy` is not decoration: `TestJustMakeitExample`
# scaffolds a just-makeit project and builds it, which needs both. The
# Makefile omitted them while ci.yml supplied them, so `make test` could NOT
# pass in this repo -- it failed in `setUpClass` with `make just-build` exit 2
# while CI was green, and the same command run CI's way passes. That is the
# drift a hand-maintained second copy of the test command produces; the
# standard's `gates-check` is what holds them together, and adopting it is the
# follow-up.
# `TEST_PYTHON=3.12` selects an interpreter, so CI's matrix can CALL this
# target instead of restating it. That restating is what let the two drift:
# ci.yml passed `--with pip --with numpy` and this file did not, so `make test`
# could not pass while CI was green.
TEST_PYTHON ?=
_TEST_RUN     = $(UV) run --no-project \
                    $(if $(TEST_PYTHON),-p $(TEST_PYTHON),) \
                    --with pip --with numpy python
# Registration-free, and deliberately so. This was a hand-maintained list of
# module names, which is the same second copy the comment above is about: a new
# `tests/test_*.py` was simply never run, in `make test` or in CI, and nothing
# said so. gh-28's tests sat unrun that way until `make test` was compared
# against `ls tests/`.
#
# So the list is derived from the tree, and the only way to keep a file out is
# to name it here. `test_pypi` is the one: it installs the PUBLISHED package
# from PyPI and exercises that, so running it from a branch tests the last
# release rather than the change in hand. Run it directly when you want it --
# `python -m unittest tests.test_pypi -v`, as its docstring says.
_TEST_EXCLUDE = test_pypi
_TEST_FILES   = $(filter-out $(addprefix tests/,$(addsuffix .py,$(_TEST_EXCLUDE))),\
                    $(wildcard tests/test_*.py))
_TEST_MODULES = $(subst /,.,$(basename $(_TEST_FILES)))
TEST_CMD      = $(_TEST_RUN) -m unittest $(_TEST_MODULES) -v
TEST_FAST_CMD = $(_TEST_RUN) -m unittest --failfast $(_TEST_MODULES)

# ── wheel ────────────────────────────────────────────────────────────────────
# PYTHONPATH=src and --no-build-isolation because the build backend imports the
# package it is building; --python 3.11 pins the interpreter the wheel is
# produced with.
WHEEL_CMD = PYTHONPATH=src $(UV) build --wheel --no-build-isolation \
                --python 3.11

# ── docs ─────────────────────────────────────────────────────────────────────
DOCS_CMD = $(ZENSICAL) build --clean

# ── clean ────────────────────────────────────────────────────────────────────
CLEAN_PATHS = dist site .pytest_cache
CLEAN_CMD   = find src -name '*.pyc' -delete; \
              find src -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true

# ── lint ─────────────────────────────────────────────────────────────────────
# EVERY pre-commit hook dispatches inward to `make lint-<tool>`, so the hook
# and `make format` cannot format differently. Before this the ruff, ruff-format
# and mdformat hooks came from upstream MIRRORS: the version lived in a `rev:`
# rather than in pyproject's dev group, and nothing held the hook's invocation
# equal to the Makefile's. `hook-dispatch-check` -- which arrived with
# standard.mk -- is what named it.
RUFF       = $(DEV_RUN) ruff
MDFORMAT   = $(DEV_RUN) mdformat
PRE_COMMIT = $(DEV_RUN) pre-commit

LINT_TOOLS = ruff ruff-format mdformat
# ruff before ruff-format when FIXING, so the formatter has the last word.
FORMAT_TOOLS = ruff-format ruff mdformat

# The vendored tomli backport is left byte-for-byte as upstream ships it.
RUFF_PATHS = src tests
# examples/** are quoted verbatim in docs/examples.md; formatting them would
# desync the docs from the fixture code they document.
RUFF_EXCLUDE = --exclude src/just_buildit/_vendor
MD_EXCLUDE_RE = ^(src/just_buildit/_vendor/)

LINT_ruff        = $(RUFF) check --fix --unsafe-fixes $(RUFF_EXCLUDE) \
                       $(RUFF_PATHS)
LINT_ruff-format = $(RUFF) format $(RUFF_EXCLUDE) $(RUFF_PATHS)

define LINT_mdformat
@git ls-files '*.md' \
    | grep -Ev '$(MD_EXCLUDE_RE)' \
    | xargs -r $(MDFORMAT)
endef

# ── release ──────────────────────────────────────────────────────────────────
PROJECT = just-buildit

# `uv lock` too: uv.lock pins this project's own version, so a bump that
# touched pyproject alone left a tree that would not commit -- the `uv-lock`
# hook rewrites the lock, then pre-commit rolls the commit back because the
# rewrite conflicts with the stashed changes (#21). The target's help already
# promised "manifests", plural.
BUMP_VERSION_CMD = sed -i 's/^version = "[^"]*"/version = "$(VERSION)"/' \
                       pyproject.toml && uv lock --quiet

# Every file that states the version, and how to read it back. `version-check`
# fails when any two disagree, so a bump that misses a file is caught before
# the tag rather than by a consumer.
define VERSION_PROBES
pyproject.toml|grep '^version = ' pyproject.toml | sed 's/.*"\(.*\)".*/\1/'
uv.lock|grep -A1 '^name = "just-buildit"$$' uv.lock | grep '^version' | sed 's/.*"\(.*\)".*/\1/'
endef

# The release watcher is VENDORED from canonical and gated by standard-check;
# everything repo-specific is here.
#
# This repo previously had NO watcher: `tag-release` pushed the tag, printed
# "release workflow starting on GitHub", and stopped. Nothing followed the run,
# nothing recovered a pre-publish flake, and nothing verified that PyPI or the
# GitHub Release actually carried the version.
RELEASE_WATCH_CMD = REPO=just-buildit/just-buildit RW_PKG=just-buildit \
                        scripts/release-watch.sh "$(VERSION)"

# ── Vendored from canonical ──────────────────────────────────────────────────
# Verbatim copies the drift gate holds to canonical, alongside standard.mk
# itself. Edit canonical and re-vendor; never edit these in place.
VENDORED_FILES = scripts/release-watch.sh

include standard.mk
