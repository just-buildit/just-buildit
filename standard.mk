# standard.mk — the shared Makefile for just-buildit and doppler-dsp repos.
#
# Canonical copy:  https://just-buildit.github.io/standard.mk
# Design RFC:      doppler-dsp/doppler#555
# Plan + criteria: just-buildit/.github README, "Makefile standard"
#
# This file is VENDORED VERBATIM and never edited in place. `make lint` runs
# the drift gate (`standard-check`), which fetches the canonical copy and fails
# on any difference. Per-repo variation is expressed as CONFIGURATION — the
# variables below, set in the repo's own Makefile before `include standard.mk`
# — never as a local edit, because a local edit is the fork this exists to
# prevent.
#
# The contract:
#
#   Makefile                configuration only: feature flags, command
#                           variables, `include standard.mk`, and any target
#                           genuinely local to the repo.
#   standard.mk             the shared targets (this file).
#   local.mk                optional, auto-included; may only ADD targets,
#                           never redefine a standard one.
#   pyproject.toml          WHICH tools, at WHAT versions.
#   uv.lock                 pins them, committed.
#   .pre-commit-config.yaml WHEN a check fires; dispatches to `make -s
#                           lint-<tool>` so it cannot drift from `make format`.
#   bootstrap.toml          system packages, consumed by `install-deps`.
#   .github/workflows       calls `make <target>`; anything else must be
#                           provably environment plumbing.
#
# Two rules keep the whole thing honest, and both are gates rather than
# review, because none of the drift this replaces was decided — it accumulated:
#
#   * `help` is GENERATED. Every active target carries a `## description` on
#     its rule line, and `help-check` fails if one is missing or if `help`
#     would advertise something that does not exist.
#   * `.PHONY` is derived from `STD_TARGETS`, and `ghost-check` fails if a
#     declared target has no recipe behind it — the failure mode where `make
#     wheel` exits 0 having done nothing.
#
# ── Configuration reference ──────────────────────────────────────────────────
#
# Feature flags (set to 1 to enable; unset means the group is not defined at
# all, so its targets do not exist and `help` does not list them):
#
#   HAS_C HAS_PYTHON HAS_RUST HAS_DOCS HAS_DOXYGEN HAS_BENCH HAS_COVERAGE
#   HAS_RELEASE HAS_EXAMPLES
#
# A command variable either has a universally correct default (`TEST_RUST_CMD`
# is `cargo test`) or is REQUIRED once its flag is on — see "Required
# configuration" below for why that is a parse-time error rather than a gate.
# Genuinely optional hooks (`DOCS_PREPARE`, `DOCS_CHECK_CMD`,
# `RELEASE_BRANCH_NOTES`) default to empty and simply do nothing.

# ── Preconditions ────────────────────────────────────────────────────────────

# GNU make only, 3.81 or newer. `.FEATURES` arrived in 3.81 and exists in no
# BSD make, so its absence is the probe. Checked because the failure otherwise
# surfaces as an inscrutable syntax error hundreds of lines away.
#
# 3.81 specifically, NOT 3.82: that is what macOS still ships as `make`, so a
# probe for anything newer rejects every macOS CI runner. It cost a red matrix
# to learn — `.RECIPEPREFIX` (3.82+) was the first probe here.
ifeq ($(origin .FEATURES),undefined)
$(error standard.mk requires GNU make 3.81+ (try gmake))
endif

# POSIX sh, so no recipe may rely on a bashism. Overridable, but only
# deliberately: make always has SHELL defined, so `?=` here would never fire.
STD_SHELL ?= /bin/sh
SHELL      = $(STD_SHELL)

# The vendored file the drift gate compares, and where it compares against.
#
# The URL is the DEFAULT, not something each adopter opts into, because the
# opt-in version fails open: a repo that vendors this file and forgets the one
# line has no drift protection at all, and says so only as a cheerful "inert"
# notice that reads like a pass. Armed on vendoring is the only default that
# cannot be silently skipped.
#
# A repo can still opt out deliberately with `STANDARD_URL =` in its Makefile,
# which is greppable across the org — unlike an omission.
STANDARD_FILE ?= standard.mk
STANDARD_URL  ?= https://just-buildit.github.io/standard.mk

# Everything ELSE vendored verbatim from canonical, as repo-relative paths —
# shared scripts today, and anything a target invokes rather than defines.
# `standard.mk` is not listed: it carries the URL that locates all the others.
#
# The base is DERIVED from STANDARD_URL rather than stated again, so a repo
# aimed at a staging mirror moves its whole vendored set together instead of
# checking one file against staging and the rest against production.
VENDORED_FILES  ?=
VENDOR_BASE_URL ?= $(dir $(STANDARD_URL))

# ── Tooling ──────────────────────────────────────────────────────────────────
# The ONLY place a tool binary is named. Versions live in pyproject.toml's dev
# group and are pinned by uv.lock; humans, hooks and CI all reach the tools
# through the targets below, so a flag change is a one-line edit rather than a
# hunt through the Makefile, the hook config and the workflows.
#
# Corollary: never invoke a linter with `uvx` or a global install. `uvx ruff`
# resolves to whatever released today, which formats differently from the
# pinned ruff and silently rewrites unrelated files.
UV         ?= uv
DEV_RUN    ?= $(UV) run --group dev
PRE_COMMIT ?= $(DEV_RUN) pre-commit
SYNC_CMD   ?= $(UV) sync

# ── Required configuration ───────────────────────────────────────────────────
# A flag turns a group ON, which makes that group's commands mandatory.
#
# This is a parse-time error rather than a gate because an empty command is
# invisible to every gate: it stamps out a target with an EMPTY recipe, and
# make records that as having a recipe, so ghost-check sees a healthy target
# and `help` advertises it — while `make <it>` exits 0 having done nothing.
# That is the exact shape of the bug this standard exists to end, so the
# standard must not be able to reintroduce it through configuration.
_std_require = $(if $(strip $($(1))),,$(error $(2) is on, but $(1) is empty \
    — set it in the Makefile, or turn $(2) off))

# ── Universal command variables ──────────────────────────────────────────────

# The table's rule: the suite, or the build where there is native code.
ALL_DEPS       ?= $(if $(filter 1,$(HAS_C)),build,test)
TEST_CMD       ?=
TEST_FAST_CMD  ?=
CLEAN_PATHS    ?=
CLEAN_CMD      ?=

# `lint-<tool>` dispatch. LINT_TOOLS names the tools; LINT_<tool> holds the
# command (a `define` block for anything multi-line). The rules are stamped out
# below, so adding a tool is one entry plus one variable, in the repo Makefile,
# with the hook config dispatching inward to the target that results.
LINT_TOOLS   ?=
# Which of those to run, in order, for `format`. Separate from LINT_TOOLS
# because a checker that cannot fix anything has no business in `format`.
FORMAT_TOOLS ?= $(LINT_TOOLS)

# Aggregates. TEST_ALL_DEPS and GATES_DEPS are prerequisite lists, so a repo
# extends them by naming targets rather than by copying recipes.
TEST_ALL_DEPS ?= test
GATES_DEPS    ?= lint test-all

# `gates` promises "every gate that guards a merge", but only the repo knows its
# CI job list — so this list, defaulted or hand-set, can silently omit one (it
# lacked `coverage-gate` in more than one repo). Rather than require the list
# (which forces a declaration, not a correct one), `gates-check` verifies it:
# every make target CI runs must be reachable from `gates`. GATES_PROVISION
# names the CI make-targets that are setup, not gates (install-deps, a build
# step), excluded by name so adding one is deliberate. GATES_CI_FILE is the
# workflow scanned; the check skips where it is absent.
GATES_CI_FILE   ?= .github/workflows/ci.yml
GATES_PROVISION ?= install-deps

# The converse, and it went unchecked for as long as `gates-check` existed: a
# target sitting in GATES_DEPS that NO workflow runs passes without a word, so
# the repo declares a gate, `make gates` runs it locally, and it guards no pull
# request. Not hypothetical -- doppler recorded it twice, and then found
# `test-ubsan` and `test-tsan` had run on no PR ever. UBSan, once wired, found
# four undefined operations on its first run.
#
# GATES_LOCAL_ONLY is the deliberate exception, named the way GATES_PROVISION
# is, so that adding one is a decision that shows up in a diff. Two reasons
# qualify, and they are different questions:
#
#   * the gate CANNOT run on a runner -- hardware, a network the runner lacks.
#     It is still a gate you run before merging, and forcing it out of
#     GATES_DEPS would lose it.
#   * the gate is an AGGREGATE for pre-push convenience whose work already has
#     a home under other names. just-makeit's `docs-check` is the case that
#     taught this: its strict build runs in docs.yml as `make docs` and its
#     `test_docs.py` half runs in ci.yml as `make test`, so every check it
#     performs gates a merge -- only the name does not.
#
# The first was the only reason this variable documented when it landed, which
# would have pushed the second case into either a wrong remedy or a wrong
# exemption. An escape hatch described more narrowly than the cases it must
# take is one that gets used for the wrong reason and then means nothing.
#
# What does NOT qualify: a gate whose work runs nowhere. That is the finding,
# not an exception to it.
GATES_LOCAL_ONLY ?=

# Targets CI runs that the scan cannot see for itself -- one driven from an
# `env` expression, or run by a workflow other than GATES_CI_FILE. Naming them
# is better than widening the scan into a guess: the check refuses to run at
# all when it meets an interpolation it cannot resolve, so a repo is told
# exactly what to add rather than handed a wrong answer.
GATES_CI_EXTRA ?=

$(call _std_require,TEST_CMD,every repo)
$(call _std_require,TEST_FAST_CMD,every repo)
# `clean` needs at least one of the two to be doing anything at all.
ifeq ($(strip $(CLEAN_PATHS)$(CLEAN_CMD)),)
$(error neither CLEAN_PATHS nor CLEAN_CMD is set, so `make clean` is a no-op)
endif

# ── Universal targets ────────────────────────────────────────────────────────

STD_TARGETS += all help setup clean test test-fast lint format install-deps

.DEFAULT_GOAL := all

all: $(ALL_DEPS) ## Default goal

test: ## Run the default test suite
	$(TEST_CMD)

test-fast: ## Run tests, stopping at the first failure
	$(TEST_FAST_CMD)

# `lint` is the gate — CI runs exactly this and nothing else. The three
# consistency gates come first because they are near-free and catch the class
# of rot that review demonstrably does not.
lint: standard-check help-check ghost-check hook-dispatch-check hook-stage-check gates-check gates-home-check ## Run the full lint gate (CI runs this)
	@hook=$$(git rev-parse --git-path hooks/pre-commit 2>/dev/null); \
	 if [ -n "$$hook" ] && [ ! -f "$$hook" ]; then \
	     $(PRE_COMMIT) install >/dev/null 2>&1 \
	         || echo "note: git hook not installed (continuing with lint)"; \
	 fi
	$(PRE_COMMIT) run --all-files

# The fixer. Runs the tools sequentially via recursive make rather than as
# prerequisites, because prerequisite order is only guaranteed without -j and
# formatters are order-dependent (a reformat can invalidate a fix).
format: ## Auto-fix formatting with every configured formatter
	@for t in $(FORMAT_TOOLS); do $(MAKE) -s lint-$$t || exit 1; done

# System packages, from bootstrap.toml. A repo that declares none still gets a
# working target — `jbx install-deps` is a no-op there.
#
# INSTALL_DEPS_CMD exists for the repo that OWNS the script this target
# fetches. just-bashit runs `bash src/just_bashit/install-deps.sh` in CI and
# the published copy from `make install-deps`, so one step had two execution
# homes and the source under development was never the thing exercised
# locally. Overriding the command is the fix; a private copy of this target
# would be the same drift in a different file.
#
# The default is the fetch, so every repo that does not set it is unchanged.
# A canned recipe rather than a one-liner, like RELEASE_WATCH_CMD: joining the
# two commands with `;` would put them in one shell and silence the second,
# changing what every repo sees for no reason.
define _STD_INSTALL_DEPS_CMD
@command -v jbx >/dev/null 2>&1 \
    || curl -sSL https://just-buildit.github.io/get-jb.sh | bash
PATH="$$HOME/.local/bin:$$PATH" jbx install-deps
endef

INSTALL_DEPS_CMD ?= $(_STD_INSTALL_DEPS_CMD)

install-deps: ## Install system build dependencies (bootstrap.toml)
	$(INSTALL_DEPS_CMD)

# Project dependencies plus the git hook. There is deliberately no second
# deps-ish target: `install` was a strict subset of this and has been folded in.
setup: ## One-time per clone: sync dependencies + install the git hook
	$(SYNC_CMD)
	$(PRE_COMMIT) install

clean: ## Remove build artifacts
	$(if $(CLEAN_PATHS),rm -rf $(CLEAN_PATHS))
	$(CLEAN_CMD)

# ── lint-<tool> dispatch ─────────────────────────────────────────────────────
# One rule per configured tool. The hook config calls `make -s lint-<tool>`,
# so the hook and `make format` cannot disagree about how a tool runs — which
# is what closes the "same command, different environment" class of drift.
#
# `$$(LINT_$(1))` is expanded when the rule runs, so a `define`d multi-line
# command works as a canned recipe.
define _std_lint_rule
STD_TARGETS += lint-$(1)
lint-$(1):
	$$(LINT_$(1))
endef
$(foreach _t,$(LINT_TOOLS),$(eval $(call _std_lint_rule,$(_t))))

# ── Aggregates ───────────────────────────────────────────────────────────────

STD_TARGETS += test-all gates gates-check gates-home-check

test-all: $(TEST_ALL_DEPS) ## Run every test suite in the repo

# Re-invoked with `-k` rather than declared as prerequisites, so ONE red gate
# does not hide every gate ordered behind it. As a prerequisite list, make stops
# at the first failure and the rest never run -- which reads as an ordinary
# failure while a third of the set was silently skipped. Measured in doppler:
# `glibc-check` cannot pass on a modern dev box BY DESIGN (its own comment says
# so), sits mid-list, and made the six targets behind it structurally
# unreachable. A broken `coverage` hid there for weeks.
#
# `docs-check` already settled this shape one level down -- "every check runs,
# every failure is reported in one pass" -- and this is the same problem one
# level up.
#
# Not a weakening: `-k` still exits non-zero if any gate failed, so the run
# fails and `ALL PASS` cannot print. Recursion is what buys it; a target-
# specific flag cannot, because the running make fixed its keep-going mode at
# startup. Under `-j` the gates still schedule in parallel, which a shell loop
# over the list would have serialised.
gates: ## Run every gate that guards a merge
	@$(MAKE) --no-print-directory -k $(GATES_DEPS)
	@echo ""
	@echo "gates: ALL PASS"

# Makes `gates`' promise true by construction: every `make <target>` CI runs
# must be reachable from `gates`, or this fails naming it. The extractor takes
# `make` only at a command position (start of a run: line or block-scalar body,
# or after ; & |), never `cmake` or a `make X` mentioned in a comment/name:, and
# the first token only so a target invoked with args still counts. The closure
# is walked from `gates` over make's own database, the way ghost-check reads it.
gates-check: ## Verify `gates` runs every make target CI invokes
	@ci="$(GATES_CI_FILE)"; \
	 if [ ! -f "$$ci" ]; then echo "gates-check: no $$ci — skipped"; exit 0; fi; \
	 db=$$($(_STD_TMP)); trap 'rm -f "$$db"' EXIT; \
	 $(MAKE) -rpn --no-print-directory .std-db-goal >"$$db" 2>/dev/null; \
	 ci_targets=$$($(_STD_CI_TARGETS)); \
	 if [ -z "$$ci_targets" ]; then \
	     echo "ERROR: gates-check matched no 'make <target>' in $$ci —"; \
	     echo "  the scan found nothing, so it did not run, so it has not passed."; \
	     exit 1; \
	 fi; \
	 : "Seeded from the VARIABLE, not just the prerequisite edge: gates now"; \
	 : "re-invokes its list with -k, so the edge no longer exists and a walk"; \
	 : "of prerequisites alone finds an EMPTY closure -- every CI target then"; \
	 : "reports as uncovered. Reading GATES_DEPS makes the check independent"; \
	 : "of HOW gates invokes them, which is what it was always asserting."; \
	 closure=" $(GATES_DEPS) "; frontier="gates $(GATES_DEPS)"; \
	 while [ -n "$$frontier" ]; do \
	     next=""; \
	     for t in $$frontier; do \
	         for p in $$(sed -n "s/^$$t:[ ]*//p" "$$db" | sed 's/|.*//'); do \
	             case "$$closure" in *" $$p "*) ;; \
	                 *) closure="$$closure$$p "; next="$$next $$p";; esac; \
	         done; \
	     done; \
	     frontier="$$next"; \
	 done; \
	 rc=0; \
	 for t in $$ci_targets; do \
	     case " $(GATES_PROVISION) " in *" $$t "*) continue;; esac; \
	     case "$$closure" in *" $$t "*) continue;; esac; \
	     echo "ERROR: CI runs 'make $$t', but 'make gates' does not"; \
	     rc=1; \
	 done; \
	 if [ $$rc -ne 0 ]; then \
	     echo ""; \
	     echo "  'gates' claims to run every merge gate. Add each to GATES_DEPS,"; \
	     echo "  or to GATES_PROVISION if it is setup rather than a gate."; \
	     exit 1; \
	 fi; \
	 echo "gates-check: gates covers all $$(set -- $$ci_targets; echo $$#) CI make-targets"

# The other direction. `gates-check` makes `gates`' promise true; this one makes
# each entry's promise true -- that a target named as a gate actually guards a
# pull request. A GATES_DEPS entry no workflow reaches is a check the repo
# believes it has: `make gates` runs it, every dev sees it pass, and nothing
# blocks on it. doppler carried two like that for their whole lives.
#
# Reachability is not a grep, and that is the whole difficulty. Three of
# doppler's entries have no literal `make <t>` in any workflow and are covered
# anyway, by two different mechanisms:
#
#   * `changelog-check` and `release-notes-size-check` are prerequisites of
#     `lint`, and CI runs `make lint`. Found by walking DOWN from the CI
#     targets, the mirror of the walk `gates-check` does from `gates`.
#   * `test-all` is an aggregate whose four components CI runs separately.
#     Walking down never reaches it -- it is above the CI targets, not below.
#     It is covered because every one of its prerequisites is, and because it
#     has NO RECIPE of its own, so running the parts does all the work running
#     it would. An aggregate WITH a recipe is not covered by its parts, and the
#     make database distinguishes the two ("recipe to execute"), so this does
#     not have to guess.
#
# A grep-only check would report all three on a correct repo, and a check that
# is wrong on the repo that prompted it is one nobody keeps.
gates-home-check: ## Verify every gate in GATES_DEPS runs in some CI job
	@ci="$(GATES_CI_FILE)"; \
	 if [ ! -f "$$ci" ]; then echo "gates-home-check: no $$ci — skipped"; exit 0; fi; \
	 if [ -z "$(strip $(GATES_DEPS))" ]; then \
	     echo "gates-home-check: GATES_DEPS is empty — skipped"; exit 0; fi; \
	 db=$$($(_STD_TMP)); trap 'rm -f "$$db"' EXIT; \
	 $(MAKE) -rpn --no-print-directory .std-db-goal >"$$db" 2>/dev/null; \
	 ci_targets=$$($(_STD_CI_TARGETS)); \
	 if [ -z "$$ci_targets" ]; then \
	     echo "ERROR: gates-home-check matched no 'make <target>' in $$ci —"; \
	     echo "  the scan found nothing, so it did not run, so it has not passed."; \
	     exit 1; \
	 fi; \
	 : "Down from every CI target: a gate spliced into one (changelog-check"; \
	 : "under lint) has its home there."; \
	 covered=" "; frontier="$$ci_targets"; \
	 for t in $$ci_targets; do covered="$$covered$$t "; done; \
	 while [ -n "$$frontier" ]; do \
	     next=""; \
	     for t in $$frontier; do \
	         for p in $$(sed -n "s/^$$t:[ ]*//p" "$$db" | sed 's/|.*//'); do \
	             case "$$covered" in *" $$p "*) ;; \
	                 *) covered="$$covered$$p "; next="$$next $$p";; esac; \
	         done; \
	     done; \
	     frontier="$$next"; \
	 done; \
	 : "Then upward, to a fixpoint: a recipe-less aggregate whose every"; \
	 : "prerequisite is covered is covered, because running the parts is"; \
	 : "running it. One with a recipe of its own is NOT."; \
	 added=1; \
	 while [ "$$added" = 1 ]; do \
	     added=0; \
	     for t in $(GATES_DEPS); do \
	         case "$$covered" in *" $$t "*) continue;; esac; \
	         line=$$(sed -n "s/^$$t:[ ]*//p" "$$db" | sed 's/|.*//' | head -n1); \
	         [ -n "$$line" ] || continue; \
	         sed -n "/^$$t:/,/^$$/p" "$$db" | grep -q 'recipe to execute' && continue; \
	         all=1; \
	         for p in $$line; do \
	             case "$$covered" in *" $$p "*) ;; *) all=0;; esac; \
	         done; \
	         if [ "$$all" = 1 ]; then covered="$$covered$$t "; added=1; fi; \
	     done; \
	 done; \
	 rc=0; n=0; \
	 for t in $(GATES_DEPS); do \
	     case " $(GATES_LOCAL_ONLY) " in *" $$t "*) continue;; esac; \
	     n=$$((n+1)); \
	     case "$$covered" in *" $$t "*) continue;; esac; \
	     echo "ERROR: 'make $$t' is in GATES_DEPS, but no job in $$ci runs it"; \
	     rc=1; \
	 done; \
	 if [ $$rc -ne 0 ]; then \
	     echo ""; \
	     echo "  A gate nothing runs guards nothing. Wire it into $$ci, drop it"; \
	     echo "  from GATES_DEPS, or name it in GATES_LOCAL_ONLY — which takes"; \
	     echo "  a gate that cannot run on a runner AND an aggregate whose work"; \
	     echo "  already runs under other names. See the comment on it."; \
	     exit 1; \
	 fi; \
	 echo "gates-home-check: $$n gate(s) have an execution home in CI"

# ── HAS_C ────────────────────────────────────────────────────────────────────
# `release` is RESERVED for the C build type. The release workflow is `ship`
# and `tag-release`, so the two senses never collide.
ifeq ($(HAS_C),1)
STD_TARGETS += build debug release compile-commands tidy

BUILD_DIR     ?= build
BUILD_TYPE    ?= RelWithDebInfo
CMAKE         ?= cmake
CMAKE_FLAGS   ?=
CLANG_TIDY    ?= clang-tidy

# How the root compile_commands.json is produced: `copy` (default) or
# `symlink`. A symlink CANNOT go stale -- it resolves to whatever the last
# configure wrote, so there is nothing to refresh -- and a relative one carries
# no absolute path, so it survives a worktree or a fresh clone. It is not the
# default only because a symlink is not free everywhere (Windows without
# developer mode). Either way this target is idempotent: a root entry that
# already resolves to the build one is left alone.
COMPILE_DB    ?= copy

# The translation units `tidy` lints, one per line. sed rather than an
# interpreter on purpose: a C-only repo should not need Python or jq installed
# to lint its C, and cmake writes compile_commands.json one "file" key per
# line. Override it if your generator emits something denser.
TIDY_FILES    ?= sed -n 's/.*"file": *"\([^"]*\)".*/\1/p' \
                     compile_commands.json | LC_ALL=C sort -u
PYEXT_CMD     ?=

# The in-place extension build belongs to the OVERLAP of the two flags, not to
# either alone: a C repo with no Python bindings has no extension to build.
ifeq ($(HAS_PYTHON),1)
STD_TARGETS += pyext
$(call _std_require,PYEXT_CMD,HAS_C=1 with HAS_PYTHON=1)
endif

# BUILD_TARGET=<name> builds ONE cmake target instead of the whole tree, for
# the edit-compile-run loop on a single binary. Everything else is unchanged,
# so `make build` is still the full build and still what CI runs.
#
# It exists because the alternative developers actually reach for is a raw
# `cmake --build <dir> --target <name>`, which bypasses this file entirely --
# the configure step, BUILD_TYPE, CMAKE_FLAGS and the compiler launcher all
# come from here, so the hand-run command is a DIFFERENT build wearing the
# same name. A repo with a hook that blocks raw cmake (doppler has one) then
# gets the bypass env-var instead, which is worse: the rule is off for the
# whole command, not just the part that needed it.
#
# Deliberately NOT called TARGET: `make TARGET=<goals>` is already the
# convention for passing goals into a container/runner wrapper, and a name
# that means two things is a name that will be passed to the wrong one.
build: ## Configure and build the native library (BUILD_TARGET=<t> for one)
	$(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(BUILD_TYPE) \
	    $(CMAKE_FLAGS)
	$(CMAKE) --build $(BUILD_DIR) $(if $(BUILD_TARGET),--target $(BUILD_TARGET))

debug: ## Build the native library with BUILD_TYPE=Debug
	@$(MAKE) build BUILD_TYPE=Debug

release: ## Build the native library clean, with BUILD_TYPE=Release
	@$(MAKE) clean
	@$(MAKE) build BUILD_TYPE=Release

# `test` and `test-fast` execute COMPILED artifacts, so they must not execute
# stale ones. A prerequisite-only line: it adds to the recipes defined in the
# Core section above rather than replacing them, so there is no second recipe
# and no `overriding recipe` warning.
#
# The failure this closes is not the noisy one. Editing a test and re-running
# reported a failure quoting the OLD assertion at the OLD line numbers, which
# is confusing but self-correcting the moment you read it. The one that
# matters is the inverse: edit a source, `make test`, see green, ship -- with
# the suite having never compiled the change, and nothing in the output
# distinguishing that from a real pass. Reported from doppler
# (doppler-dsp/doppler#659), where `make` is the only sanctioned way to run
# the C suite -- a pre-commit hook blocks raw ctest -- so this was the single
# path to a result and it was the one that could be silently stale.
#
# Inside HAS_C because `build` only exists here; a Python-only repo compiles
# nothing and keeps `test` free-standing.
#
# No separate gate: a missing prerequisite reproduces the bug immediately, so
# the dependency IS the check and there is nothing here that can rot.
test test-fast: build

ifeq ($(HAS_PYTHON),1)
pyext: ## Build the Python extension in place
	$(PYEXT_CMD)
endif

# clangd and clang-tidy read compile_commands.json from the PROJECT ROOT, while
# cmake writes it into $(BUILD_DIR) -- hence the copy.
#
# Phony, and re-configuring every time. A file target keyed on
# $(BUILD_DIR)/CMakeCache.txt is the obvious shape and it is wrong: the cache
# does not move when the source list does, so the copy runs once and never
# again, and anything that later touches the root copy pins it as up to date
# forever. That exact rule shipped in just-makeit's generated projects and
# could not re-copy at all (just-buildit/just-makeit#940). There is no
# timestamp here to get wrong; configure is idempotent and costs a second.
compile-commands: ## Refresh compile_commands.json for clangd / clang-tidy
	$(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(BUILD_TYPE) \
	    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON $(CMAKE_FLAGS)
	@src=$(BUILD_DIR)/compile_commands.json; dst=compile_commands.json; \
	 if [ "$(COMPILE_DB)" = symlink ]; then \
	     ln -sfn "$$src" "$$dst"; \
	     echo "compile-commands: $$dst -> $$src"; \
	 elif [ "$$dst" -ef "$$src" ]; then \
	     : "Already the same file -- a relative symlink into the build tree."; \
	     : "cp refuses that outright ('are the same file') and took the whole"; \
	     : "target, and tidy with it, down in the first HAS_C adopter."; \
	     echo "compile-commands: $$dst already resolves to $$src"; \
	 else \
	     cp "$$src" "$$dst"; \
	 fi

# The file list comes from the compile DATABASE, not a directory walk, so tidy
# sees exactly the translation units cmake compiles -- no more (a generated .c
# that no target references, which would fail to lint for reasons that are not
# about the code) and no less.
#
# A repo with no .clang-tidy gets a clear refusal rather than clang-tidy's own
# default check set, which is not the same thing as "the project's checks".
tidy: compile-commands ## Run clang-tidy over the compile database
	@command -v $(CLANG_TIDY) >/dev/null 2>&1 || \
	    { echo "tidy: $(CLANG_TIDY) not found -- install it first"; exit 1; }
	@[ -f .clang-tidy ] || \
	    { echo "tidy: no .clang-tidy in this repo; refusing to lint against"; \
	      echo "  clang-tidy's defaults, which are not your project's checks."; \
	      exit 1; }
	@$(TIDY_FILES) | xargs $(CLANG_TIDY) -p .
endif

# ── HAS_PYTHON ───────────────────────────────────────────────────────────────
# `wheel`, not `build`: in a repo with C the noun `build` is the native build,
# and one standard target may not mean two things (criterion 9).
ifeq ($(HAS_PYTHON),1)
STD_TARGETS += wheel

WHEEL_CMD       ?= $(UV) build --wheel

wheel: ## Build a wheel into dist/
	$(WHEEL_CMD)
	@echo ""
	@ls -lh dist/*.whl

# `test-python` only where it is NOT already `test`: in a Python-only repo
# (HAS_C off) TEST_CMD == TEST_PYTHON_CMD, so the two run the identical command
# and `make help` advertises both. It earns its place only alongside a C `test`
# (ctest), where it names the distinct Python suite.
ifeq ($(HAS_C),1)
STD_TARGETS += test-python
TEST_PYTHON_CMD ?= $(TEST_CMD)

test-python: ## Run the Python test suite
	$(TEST_PYTHON_CMD)
endif
endif

# ── HAS_RUST ─────────────────────────────────────────────────────────────────
ifeq ($(HAS_RUST),1)
STD_TARGETS += test-rust

TEST_RUST_CMD ?= cargo test

test-rust: ## Run the Rust test suite
	$(TEST_RUST_CMD)
endif

# ── HAS_DOCS ─────────────────────────────────────────────────────────────────
# `docs-check` is the pre-push gate: a strict build (which catches broken
# anchors that the test suite does not) plus whatever invariants the repo
# checks. It exists so `zensical build --strict` has exactly ONE implementation
# — CI calls this target rather than carrying its own copy of the command.
ifeq ($(HAS_DOCS),1)
STD_TARGETS += docs docs-serve docs-check

ZENSICAL        ?= $(DEV_RUN) zensical
DOCS_PREPARE    ?=
DOCS_BUILD_CMD  ?= $(ZENSICAL) build --clean --strict
DOCS_SERVE_CMD  ?= $(ZENSICAL) serve
# The strict build for `docs-check`, as a variable so CI calls this target
# instead of carrying its own copy of the command — the duplication that put
# `zensical build --strict` in three disagreeing places (criterion 5).
#
# Exported, not interpolated into the recipe: a value containing quotes
# would otherwise be re-parsed by the shell and break. make hands it over.
DOCS_CHECK_BUILD_CMD ?= $(ZENSICAL) build --strict
export DOCS_CHECK_BUILD_CMD

# Gates that run around the build, in order, one shell command per line.
# PRE runs before it, POST after — `check_site_links`-shaped checks need a
# built site, cheap script gates want to fail before you pay for a build.
#
# They ACCUMULATE: every command runs, every failure is reported, and the
# target fails at the end if any did. A gate that stops at the first failure
# lets a later red hide behind an earlier one, so you fix one thing, push, and
# discover the next — which is how a docs gate teaches people to stop running
# it locally.
DOCS_CHECK_PRE_CMDS  ?=
DOCS_CHECK_POST_CMDS ?=
export DOCS_CHECK_PRE_CMDS
export DOCS_CHECK_POST_CMDS

# Legacy: a single canned recipe run after everything above. Superseded by
# DOCS_CHECK_POST_CMDS, and kept because it may be a `define` beginning with a
# recipe prefix (`@`), which only works as a recipe line and cannot be folded
# into the accumulator. It runs only if the accumulator passed; migrate to
# POST to get accumulate-don't-abort for it too.
DOCS_CHECK_CMD  ?=

docs: ## Build the docs site
	$(DOCS_PREPARE)
	$(DOCS_BUILD_CMD)

docs-serve: ## Build and serve the docs with live reload
	$(DOCS_PREPARE)
	$(DOCS_SERVE_CMD)

docs-check: ## Pre-push docs gate: strict build + docs invariants
	@echo "Docs gate: strict build (broken anchors) + docs invariants..."
	$(DOCS_PREPARE)
	@tmp=$$($(_STD_TMP)); trap 'rm -f "$$tmp"' EXIT; fail=0; \
	 run() { echo "=== $$1 ==="; sh -c "$$1" || fail=1; }; \
	 printf '%s\n' "$$DOCS_CHECK_PRE_CMDS" >"$$tmp"; \
	 while IFS= read -r c; do [ -n "$$c" ] && run "$$c"; done <"$$tmp"; \
	 run "$$DOCS_CHECK_BUILD_CMD"; \
	 printf '%s\n' "$$DOCS_CHECK_POST_CMDS" >"$$tmp"; \
	 while IFS= read -r c; do [ -n "$$c" ] && run "$$c"; done <"$$tmp"; \
	 if [ "$$fail" != 0 ]; then \
	     echo "docs-check: FAILURES above — every gate ran, all reported"; \
	     exit 1; \
	 fi
	$(DOCS_CHECK_CMD)
endif

# ── HAS_DOXYGEN ──────────────────────────────────────────────────────────────
ifeq ($(HAS_DOXYGEN),1)
STD_TARGETS += doxygen doxygen-check

DOXYGEN_CMD       ?= doxygen
DOXYGEN_CHECK_CMD ?=

$(call _std_require,DOXYGEN_CHECK_CMD,HAS_DOXYGEN)

doxygen: ## Build the C API documentation
	$(DOXYGEN_CMD)

doxygen-check: ## Fail on any Doxygen warning
	$(DOXYGEN_CHECK_CMD)
endif

# ── HAS_BENCH ────────────────────────────────────────────────────────────────
ifeq ($(HAS_BENCH),1)
STD_TARGETS += bench bench-save bench-compare

BENCH_CMD         ?=
BENCH_SAVE_CMD    ?=
BENCH_COMPARE_CMD ?=

$(call _std_require,BENCH_CMD,HAS_BENCH)
$(call _std_require,BENCH_SAVE_CMD,HAS_BENCH)
$(call _std_require,BENCH_COMPARE_CMD,HAS_BENCH)

bench: ## Run the benchmarks
	$(BENCH_CMD)

bench-save: ## Save a benchmark baseline
	$(BENCH_SAVE_CMD)

bench-compare: ## Compare against the last saved baseline
	$(BENCH_COMPARE_CMD)
endif

# ── HAS_COVERAGE ─────────────────────────────────────────────────────────────
ifeq ($(HAS_COVERAGE),1)
STD_TARGETS += coverage coverage-gate

COVERAGE_CMD      ?=
COVERAGE_GATE_CMD ?=

$(call _std_require,COVERAGE_CMD,HAS_COVERAGE)
$(call _std_require,COVERAGE_GATE_CMD,HAS_COVERAGE)

coverage: ## Produce a coverage report
	$(COVERAGE_CMD)

# Separate from `coverage` because a report is not a gate. This one fails when
# the threshold is missed, so CI can call exactly that rather than "produce a
# report" and hope someone reads it.
coverage-gate: ## Fail when coverage falls below the threshold
	$(COVERAGE_GATE_CMD)
endif

# ── HAS_RELEASE ──────────────────────────────────────────────────────────────
# The release workflow, in dependency order: release-branch (bump on a branch)
# -> PR -> merge -> tag-release -> release-watch, with `ship` doing the last
# two in one go. `release` is NOT part of this — it is the C build type.
ifeq ($(HAS_RELEASE),1)
STD_TARGETS += bump-version version-check release-branch tag-release \
               release-watch ship

BUMP_VERSION_CMD  ?=
RELEASE_WATCH_CMD ?=
# Newline-separated `label|command` pairs; each command prints a version
# string. `version-check` requires every probe to agree — and to equal
# VERSION= when one is given. Exported so the recipe's shell can read it.
VERSION_PROBES ?=
export VERSION_PROBES
# Extra guidance echoed after `release-branch`, repo-specific by nature.
RELEASE_BRANCH_NOTES ?=

$(call _std_require,BUMP_VERSION_CMD,HAS_RELEASE)
$(call _std_require,VERSION_PROBES,HAS_RELEASE)
$(call _std_require,RELEASE_WATCH_CMD,HAS_RELEASE)

# Where VERSION may come from, and where it may not.
#
# `VERSION` is one of the most commonly exported names there is -- CI systems,
# build wrappers and half the shell profiles in existence set it -- and make
# imports the environment as make variables. So a bare exported VERSION
# satisfies `ifndef VERSION` below and ARMS a release target that was invoked
# with no argument at all. Measured in doppler:
#
#     $ VERSION=9.9.9 make -n bump-version
#     sed -i 's/^version = "[^"]*"/version = "9.9.9"/' pyproject.toml
#     ...
#
# Every manifest rewritten to a number nobody typed, and `release-branch` would
# branch and bump on it too -- a wrong release, from a variable that may have
# been exported three shells ago for something else entirely.
#
# The fix is NOT to ban the environment, which would cost the perfectly good
# `VERSION=x make bump-version` habit. It is to insist the NAME carry evidence
# of intent, which `VERSION` cannot: nothing distinguishes one typed at the
# front of this command from one exported by a CI runner. So a repo declares
# its own PROJECT and the namespaced spelling is accepted:
#
#     make bump-version VERSION=1.2.3        # command line, always wins
#     JUST_BUILDIT_DOPPLER_VERSION=1.2.3 make bump-version
#     VERSION=1.2.3 make bump-version        # REFUSED, with both of the above
#
# `JUST_BUILDIT_<PROJECT>_VERSION` follows the convention the build backend
# already uses (JUST_BUILDIT_PYTHON, JUST_BUILDIT_OUTPUT_DIR), and PROJECT
# scopes it so one shell can carry versions for several repos at once without
# them colliding -- which is the situation that makes a bare VERSION dangerous
# in the first place.
#
# A repo that does not set PROJECT keeps command-line-only, which is the safe
# default rather than a silent downgrade.
PROJECT     ?=
VERSION_ENV ?= $(if $(PROJECT),JUST_BUILDIT_$(PROJECT)_VERSION)
VERSION_TARGETS ?= bump-version version-check release-branch tag-release \
                   release-watch ship

ifneq ($(origin VERSION),command line)
# The namespaced spelling, read INDIRECTLY: make imports the environment, so
# `$($(VERSION_ENV))` is that variable's value without naming it twice.
_std_version_env := $(if $(VERSION_ENV),$($(VERSION_ENV)))
ifneq ($(_std_version_env),)
override VERSION := $(_std_version_env)
else
ifneq ($(filter environment environment override,$(origin VERSION)),)
ifneq ($(filter $(VERSION_TARGETS),$(MAKECMDGOALS)),)
$(error VERSION=$(VERSION) came from the ENVIRONMENT, where the name carries \
no evidence that you meant it -- a release target invoked with no argument \
would act on it. Use `make <target> VERSION=$(VERSION)`$(if $(VERSION_ENV), \
or export $(VERSION_ENV) instead))
else
# Some other target in a shell that happens to export VERSION. Ignore it
# rather than fail: erroring here would make this guard worse than the bug.
override VERSION :=
endif
endif
endif
endif

bump-version: ## VERSION=x.y.z — write the version into the repo's manifests
ifndef VERSION
	@echo "usage: make bump-version VERSION=<x.y.z>"
	@exit 1
endif
	$(BUMP_VERSION_CMD)
	@echo "Bumped to $(VERSION)"

# Two jobs in one target, because they are the same question: do the manifests
# agree with each other, and (when asked) with the version being released?
# doppler answered only the first and just-makeit only the second under the
# same name, which is exactly the divergence this standard exists to end.
version-check: ## [VERSION=x.y.z] Verify version strings agree
	@printf '%s\n' "$$VERSION_PROBES" | grep -v '^[[:space:]]*$$' \
	 | while IFS='|' read -r label cmd; do \
	     got=$$(eval "$$cmd"); \
	     printf '  %-24s %s\n' "$$label" "$$got"; \
	     if [ -n "$(VERSION)" ] && [ "$$got" != "$(VERSION)" ]; then \
	         echo "ERROR: $$label has $$got, expected $(VERSION)"; exit 1; \
	     fi; \
	     if [ -n "$$first" ] && [ "$$got" != "$$first" ]; then \
	         echo "ERROR: $$label has $$got, but $$firstlabel has $$first"; \
	         exit 1; \
	     fi; \
	     first=$$got; firstlabel=$$label; \
	 done
	@echo "Version OK"

# The explicit origin/main start point matters: a bare `checkout -b` forks from
# whatever HEAD the invoker happens to be on (a feature branch, a stale main),
# silently building the release on the wrong base — the bump then misses
# everything merged since.
release-branch: ## VERSION=x.y.z — branch off origin/main and bump
ifndef VERSION
	@echo "usage: make release-branch VERSION=<x.y.z>"
	@exit 1
endif
	git fetch origin main
	git checkout -b chore/release-$(VERSION) origin/main
	@$(MAKE) bump-version VERSION=$(VERSION)
	@echo ""
	@echo "Now:"
	@echo "  - edit CHANGELOG.md ([Unreleased] -> [$(VERSION)])"
	$(RELEASE_BRANCH_NOTES)
	@echo "  - git commit -am 'chore: release v$(VERSION)', push, open a PR"
	@echo "  - merge once green, then: git checkout main && git pull &&"
	@echo "    make ship VERSION=$(VERSION)"

# Tags an already-merged, CI-green main commit and pushes ONLY the tag. main is
# never pushed to directly, so the tag always points at code the required
# checks already passed.
tag-release: ## VERSION=x.y.z — tag merged main and push the tag
ifndef VERSION
	@echo "usage: make tag-release VERSION=<x.y.z>"
	@exit 1
endif
	@test "$$(git rev-parse --abbrev-ref HEAD)" = "main" || \
	    { echo "ERROR: not on main — tags only point at merged main"; exit 1; }
	@git fetch --quiet origin main
	@test "$$(git rev-parse HEAD)" = "$$(git rev-parse origin/main)" || \
	    { echo "ERROR: local main != origin/main — git pull first"; exit 1; }
	@$(MAKE) version-check VERSION=$(VERSION)
# Idempotent, so `ship` can be RE-RUN after its watch is interrupted. The tag
# push is the point of no return -- it starts the release -- but the watch that
# follows runs for tens of minutes, and anything cutting it short (a timeout, a
# dropped connection, Ctrl-C) used to leave `ship` unusable: `git tag` fails on
# an existing tag, so the way back was to know that `release-watch` is a
# separate target. Re-running the command you already ran is the obvious move,
# and it now works.
#
# An existing tag on a DIFFERENT commit is still refused. That is the case
# worth failing on: the artifacts were built from wherever the tag pointed when
# the workflow ran, so moving it makes the tag disagree with what was published.
	@if git rev-parse -q --verify "refs/tags/v$(VERSION)" >/dev/null 2>&1; then \
	    test "$$(git rev-parse "v$(VERSION)^{commit}")" = "$$(git rev-parse HEAD)" || \
	        { echo "ERROR: v$(VERSION) exists and points at another commit."; \
	          echo "  A released tag must not move — its artifacts were built"; \
	          echo "  from where it pointed. Cut the next patch version."; \
	          exit 1; }; \
	    echo "tag-release: v$(VERSION) already tags HEAD — reusing it"; \
	else \
	    git tag -a "v$(VERSION)" -m "Release v$(VERSION)"; \
	fi
	@git push origin "v$(VERSION)"
	@echo "Tagged v$(VERSION) — release workflow starting on GitHub"

release-watch: ## VERSION=x.y.z — watch the release workflow and verify it
ifndef VERSION
	@echo "usage: make release-watch VERSION=<x.y.z>"
	@exit 1
endif
	$(RELEASE_WATCH_CMD)

ship: tag-release release-watch ## VERSION=x.y.z — tag-release then release-watch
endif

# ── HAS_EXAMPLES ─────────────────────────────────────────────────────────────
ifeq ($(HAS_EXAMPLES),1)
STD_TARGETS += test-examples

TEST_EXAMPLES_CMD ?=

$(call _std_require,TEST_EXAMPLES_CMD,HAS_EXAMPLES)

test-examples: ## Run the end-to-end example builds
	$(TEST_EXAMPLES_CMD)
endif

# ── Gates ────────────────────────────────────────────────────────────────────
# Three invariants that review has been shown not to catch, each failing rather
# than warning. A gate that cannot run has not passed.

STD_TARGETS += standard-check standard-update help-check ghost-check hook-dispatch-check
STD_TARGETS += hook-stage-check

# A temp file, portably: bare `mktemp` is a GNU extension, and the BSD one
# macOS ships requires a template. The gates parse make's own database, which
# is far too big to hold in a shell variable comfortably.
_STD_TMP = mktemp "$${TMPDIR:-/tmp}/std.XXXXXX"

# The `make <target>` invocations in $$ci, one per line, sorted and unique.
# ONE extractor because `gates-check` and `gates-home-check` are the two
# directions of a single claim, and two copies of a scan is how the directions
# come to disagree about what CI runs. Takes `make` only at a command position
# (start of a `run:` line or block-scalar body, or after ; & |), so neither
# `cmake` nor a `make X` inside a comment or a `name:` counts, and the first
# token only, so a target invoked with arguments still does. Reads `ci` from
# the calling recipe's shell.
#
# `\#`, not a bare `#`: in a variable definition make takes `#` as the start
# of a comment and truncates the pipeline mid-regex, which the shell then
# reports as `Unterminated quoted string` -- a syntax error with no syntax
# error in it. Bracketing it as `[#]` does NOT help; make does not know a
# regex from a comment. In a recipe LINE, where this lived before, `#` is
# passed through untouched, which is why the move needed the escape.
# The same applies to a shell `$${var\#pattern}` further down: make sees a
# `#`, not a parameter expansion.
#
# The matrix arm is why this could not stay a plain grep. doppler runs its
# sanitizers as `run: make $${{ matrix.san.target }}`, with `test-asan` /
# `test-ubsan` / `test-tsan` listed in the matrix -- so there is no literal
# `make test-asan` anywhere. A missed CI target is a harmless under-count for
# `gates-check` (it demands less of `gates`); for `gates-home-check` the same
# blind spot is a FALSE FINDING against three targets that do run, on the very
# repo the check was written for. The interpolation names the key that supplies
# it, so the values are resolved rather than guessed at: `matrix.san.target`
# reads `target:` under `san:`, and a flat `matrix.thing` reads the list.
_STD_CI_TARGETS = { sed -E 's/(^|[[:space:]])\#.*$$//' "$$ci" \
	     | grep -hoE '(^[[:space:]]*(- )?run:[[:space:]]*make|^[[:space:]]*make|[;&|][[:space:]]*make)[[:space:]]+[a-zA-Z_][a-zA-Z0-9_-]*' \
	     | grep -oE 'make[[:space:]]+[a-zA-Z_][a-zA-Z0-9_-]*$$' \
	     | sed -E 's/make[[:space:]]+//'; \
	   for _e in $$(grep -oE 'make[[:space:]]+\$$\{\{[[:space:]]*matrix\.[a-zA-Z0-9_.]+' "$$ci" \
	       | sed -E 's/.*matrix\.//' | LC_ALL=C sort -u); do \
	     _k=$${_e%%.*}; _f=$${_e\#*.}; \
	     if [ "$$_f" = "$$_e" ]; then \
	       sed -n "/^[[:space:]]*$$_k:[[:space:]]*$$/,/^[[:space:]]*[a-zA-Z_-]*:[[:space:]]*$$/p" "$$ci" \
	         | grep -oE '^[[:space:]]*-[[:space:]]*[a-zA-Z_][a-zA-Z0-9_-]*[[:space:]]*$$' \
	         | sed -E 's/[[:space:]]*-[[:space:]]*//;s/[[:space:]]*$$//'; \
	     else \
	       sed -n "/^[[:space:]]*$$_k:[[:space:]]*$$/,/^[[:space:]]*[a-zA-Z_-]*:[[:space:]]*$$/p" "$$ci" \
	         | grep -oE "[{,][[:space:]]*$$_f:[[:space:]]*[a-zA-Z_][a-zA-Z0-9_-]*|^[[:space:]]*$$_f:[[:space:]]*[a-zA-Z_][a-zA-Z0-9_-]*" \
	         | sed -E "s/.*$$_f:[[:space:]]*//"; \
	     fi; \
	   done; \
	   for _x in $(GATES_CI_EXTRA); do echo "$$_x"; done; \
	 } | LC_ALL=C sort -u

# The goal the gates hand to their database dump, and the only reason it
# exists. `-p` prints the full database whatever the goal is, but with NO goal
# named the sub-make builds `.DEFAULT_GOAL` — and `-n` still EXECUTES recipe
# lines containing $(MAKE), by the documented recursion rule. In a repo that
# configures `ALL_DEPS` to reach `lint` (which skills://makefile-convention
# prescribes for shell repos: `all: lint test`), the gates then re-enter
# themselves, twice per level, until the machine gives up — measured at ~900
# processes on a bare `make`. Naming an inert goal pins the dump to something
# with no prerequisites, so the default goal is irrelevant.
#
# Dot-prefixed so both gates' scrapes skip it, as they already do for make's
# own special targets, and so it never reaches `help`.
.std-db-goal: ; @:

# Resolve one target's help text, for both `help` and `help-check`. Defined
# once here so the two can never disagree about what counts as documented.
#
# The `## description` on the rule line is the source. The dispatch rules are
# the one exception: they are stamped out by `$(eval)`, so their source text
# reads `lint-$(1):` and no scrape can find them by name — their description
# comes from the macro that generated them.
_STD_DESC = d=$$(sed -n "s/^$$t:.*\#\# *//p" $(MAKEFILE_LIST) | head -1); \
            case "$$t" in \
                lint-*) [ -n "$$d" ] \
                    || d="Run $${t\#lint-} (pre-commit dispatch target)";; \
            esac

# Section for a target, resolved from its name — used only by `help` to
# group the listing. Mirrors the file's own block structure (Core, then one
# section per HAS_* feature, in file order), so a reader who already knows
# the file knows the menu. Anything unmatched (i.e. LOCAL_TARGETS) falls
# into "Local", the correct home for repo-specific targets.
_STD_SECTION = case "$$t" in \
    all|help|setup|clean|test|test-fast|lint|format|install-deps) \
        tsec="Core";; \
    lint-*) tsec="Lint";; \
    test-all|gates|gates-check|gates-home-check) tsec="Aggregates";; \
    build|debug|release|pyext|compile-commands|tidy) tsec="C";; \
    wheel|test-python) tsec="Python";; \
    test-rust) tsec="Rust";; \
    docs|docs-serve|docs-check) tsec="Docs";; \
    doxygen|doxygen-check) tsec="Doxygen";; \
    bench|bench-save|bench-compare) tsec="Bench";; \
    coverage|coverage-gate) tsec="Coverage";; \
    bump-version|version-check|release-branch|tag-release|release-watch \
        |ship) tsec="Release";; \
    test-examples) tsec="Examples";; \
    standard-check|standard-update|help-check|ghost-check|hook-dispatch-check|hook-stage-check) \
        tsec="Gates";; \
    *) tsec="Local";; \
esac

_STD_SECTION_ORDER = Core Lint Aggregates C Python Rust Docs Doxygen Bench \
                      Coverage Release Examples Gates Local

# Drift. Fetches canonical EVERY time, with no cache: a cache would mean the
# most likely failure — the fetch failing while the network is fine (CDN
# outage, bad deploy, a 404 after a rename) — silently degrades into "compared
# against something older", and one bad deploy would disable the drift gate
# across every repo at once with nothing going red.
#
# It walks a LIST, not a single file, because standard.mk is not the only thing
# vendored verbatim from canonical. `release-watch.sh` proved the point: two
# repos wired the same filename to the same target and the scripts silently
# forked, one growing a CI-repair path the other never got. Sharing the target
# name while hand-copying the file it runs shares nothing.
#
# One gate rather than two. A second target with its own fetch-and-diff loop
# would be a peer implementation of this one, which is the duplication the list
# exists to end.
# The FIX half of the drift gate. `standard-check` reports drift and its
# message said to run `curl -fsSL <url> -o <file>` by hand -- so the only way
# to act on this gate was outside make, which is the exact shape this file
# exists to stamp out. Measured the day it was written: four repos re-vendored
# by hand-run curl, in a session whose other two commits were about not
# bypassing make.
#
# It shares VENDORED_FILES and the URL derivation with the check rather than
# restating either, so the two cannot disagree about what is vendored or where
# it comes from. It re-runs the check afterwards: a fetch that leaves the tree
# still drifted has not updated anything, and saying so is the point.
standard-update: ## Re-fetch every vendored file from canonical
	@if [ -z "$(STANDARD_URL)" ]; then \
	    echo "standard-update: STANDARD_URL is empty — nothing is vendored"; \
	    echo "  in this repo, so there is nothing to update."; \
	    exit 0; \
	fi; \
	for f in $(STANDARD_FILE) $(VENDORED_FILES); do \
	    case "x$$f" in \
	        "x$(STANDARD_FILE)") u="$(STANDARD_URL)" ;; \
	        *)                   u="$(VENDOR_BASE_URL)$$f" ;; \
	    esac; \
	    tmp=$$(mktemp); \
	    if ! curl -fsSL "$$u" -o "$$tmp" 2>/dev/null; then \
	        rm -f "$$tmp"; \
	        echo "standard-update: cannot fetch $$u — refusing to leave a"; \
	        echo "  half-updated tree. Fix the fetch and re-run."; \
	        exit 1; \
	    fi; \
	    if cmp -s "$$tmp" "$$f" 2>/dev/null; then rm -f "$$tmp"; \
	    else mkdir -p "$$(dirname "$$f")"; \
	         if [ -x "$$f" ]; then mv "$$tmp" "$$f"; chmod +x "$$f"; \
	         else mv "$$tmp" "$$f"; chmod 644 "$$f"; fi; \
	         echo "  updated $$f"; fi; \
	done; \
	$(MAKE) --no-print-directory standard-check

standard-check: ## Verify every vendored file matches canonical
	@if [ -z "$(STANDARD_URL)" ]; then \
	    echo "standard-check: OFF — STANDARD_URL is empty, so drift is NOT"; \
	    echo "  checked in this repo. That is a deliberate opt-out, not a"; \
	    echo "  pass; unset it only if you mean it."; \
	    exit 0; \
	fi; \
	n=0; fail=0; \
	for f in $(STANDARD_FILE) $(VENDORED_FILES); do \
	    : "The x prefix is load-bearing: an empty STANDARD_FILE expands the"; \
	    : "pattern to a bare ) and the shell dies on a syntax error instead"; \
	    : "of reaching the compared-0-files guard below. Quoted, so an exact"; \
	    : "match rather than a glob."; \
	    case "x$$f" in \
	        "x$(STANDARD_FILE)") u="$(STANDARD_URL)" ;; \
	        *)                   u="$(VENDOR_BASE_URL)$$f" ;; \
	    esac; \
	    if [ ! -f "$$f" ]; then \
	        echo "ERROR: $$f is vendored but missing from this repo."; \
	        echo "  A gate that compares nothing has not passed. Fetch it:"; \
	        echo "    curl -fsSL $$u -o $$f"; \
	        fail=1; continue; \
	    fi; \
	    tmp=$$(mktemp); \
	    if ! curl -fsSL "$$u" -o "$$tmp" 2>/dev/null; then \
	        rm -f "$$tmp"; \
	        echo "ERROR: cannot fetch $$u"; \
	        echo "  A gate that cannot reach its reference has not passed;"; \
	        echo "  it has not run. Fix the fetch, do not skip the gate."; \
	        fail=1; continue; \
	    fi; \
	    if ! diff -u "$$tmp" "$$f" >/dev/null 2>&1; then \
	        echo "ERROR: $$f differs from $$u"; \
	        diff -u "$$tmp" "$$f" | head -40; \
	        rm -f "$$tmp"; \
	        echo ""; \
	        echo "  Vendored files are verbatim. Per-repo variation is"; \
	        echo "  configuration in the Makefile; change canonical, not this."; \
	        fail=1; continue; \
	    fi; \
	    rm -f "$$tmp"; \
	    n=$$((n + 1)); \
	done; \
	[ "$$fail" -eq 0 ] || exit 1; \
	if [ "$$n" -eq 0 ]; then \
	    echo "ERROR: standard-check compared 0 files — it did not run."; \
	    exit 1; \
	fi; \
	echo "standard-check: $$n vendored file(s) match canonical"

# Help completeness, both directions: every listed target carries a
# description, and every target that exists is listed.
#
# The second direction is deliberately NOT "does each listed target exist" —
# that check cannot fail, because `.PHONY` alone is enough to put a name in the
# make database, so a name with nothing behind it still looks like a target.
# The case that DOES happen is the reverse: a rule gets added without being
# named in STD_TARGETS/LOCAL_TARGETS, so `help` silently omits it. Whether the
# targets `help` lists actually do anything is ghost-check's job.
#
# The THIRD direction is the section menu. `gates-home-check` was added to
# STD_TARGETS and given a recipe and a description, and every check above
# passed -- it is a real target, it is documented, and help lists it. It was
# listed under "Local", because _STD_SECTION never got a matching arm and the
# fallthrough is Local by design. So the standard shipped a shared target that
# every adopter's `make help` advertised as repo-specific, which is precisely
# backwards: just-makeit's own CLAUDE.md tells readers that `make help`'s Local
# section is the authoritative answer to which targets are that repo's alone.
#
# One direction only. A menu arm with no STD_TARGETS member is NOT an error --
# most arms name feature-gated targets (`build`, `test-rust`, `doxygen`) that a
# repo with that HAS_* flag off never defines, so the reverse check would fire
# in almost every repo for nothing.
help-check: ## Verify help documents every target, and every target is listed
	@rc=0; \
	 db=$$($(_STD_TMP)); trap 'rm -f "$$db"' EXIT; \
	 $(MAKE) -rpn --no-print-directory .std-db-goal >"$$db" 2>/dev/null; \
	 for t in $(ALL_TARGETS); do \
	     $(_STD_DESC); \
	     if [ -z "$$d" ]; then \
	         echo "ERROR: '$$t' has no '## description', so help omits it"; \
	         rc=1; \
	     fi; \
	 done; \
	 nsec=0; \
	 for t in $(STD_TARGETS); do \
	     $(_STD_SECTION); \
	     if [ "$$tsec" = "Local" ]; then \
	         echo "ERROR: '$$t' is a STANDARD target, but help files it under"; \
	         echo "  Local. A shared target advertised as repo-local is the"; \
	         echo "  drift this file exists to prevent, and it is how a repo"; \
	         echo "  comes to believe it owns something it merely vendors."; \
	         echo "  Give it an arm in _STD_SECTION, beside its siblings."; \
	         rc=1; \
	     else nsec=$$((nsec + 1)); fi; \
	 done; \
	 withrecipe=$$(awk '/^[a-zA-Z0-9_.-]+:/ { n = $$0; sub(/:.*/, "", n); \
	                                          b = 1; r = 0; next } \
	      b && / to execute/ { r = 1 } \
	      b && /^$$/ { if (r) print n; b = 0 } \
	      END { if (b && r) print n }' "$$db" | LC_ALL=C sort -u); \
	 if [ -z "$$withrecipe" ]; then \
	     echo "ERROR: parsed no rules out of make's database"; \
	     echo "  This half of the gate did not run, so it has not passed."; \
	     rc=1; \
	 fi; \
	 for t in $$withrecipe; do \
	     case " $(ALL_TARGETS) " in *" $$t "*) continue;; esac; \
	     case "$$t" in .*) continue;; esac; \
	     if [ -e "$$t" ]; then continue; fi; \
	     echo "ERROR: '$$t' has a rule but help does not list it"; \
	     echo "  add it to LOCAL_TARGETS (or STD_TARGETS, if it is shared)"; \
	     rc=1; \
	 done; \
	 if [ $$rc -eq 0 ]; then \
	     echo "help-check: $(words $(ALL_TARGETS)) targets documented,"\
	          "$$nsec standard target(s) filed"; \
	 fi; \
	 exit $$rc

# Ghost targets: declared .PHONY with no recipe AND no prerequisites, so they
# exit 0 having done nothing. doppler shipped `make wheel` in this state
# through a lint gate, CI on every PR, and a help entry advertising it.
#
# The prerequisite half of that test is what keeps the aggregates legitimate:
# `all: test`, `test-all: ...` and `ship: ...` carry no recipe by design and do
# their work entirely through what they depend on.
#
# EVERY `sort` AND THE `comm` BELOW PIN LC_ALL=C, AND THAT IS LOAD-BEARING.
# Target names are hyphen- and underscore-heavy, and a UTF-8 collation ignores
# punctuation at the primary weight — so this gate broke two ways at once on a
# developer box running en_US.UTF-8 (doppler, 2026-08-18):
#
#   `sort -u` DROPS DISTINCT NAMES. Under en_US, `test-stubs`, `teststubs` and
#   `test_stubs` all compare equal, so three targets dedup to one and two
#   vanish from the gate's input before anything is compared.
#
#   `comm` DESYNCS. It compares byte-wise while `sort` ordered by locale, so it
#   printed `comm: input is not in sorted order` on every run and silently
#   skipped matches in the disordered window.
#
# Net effect: a genuine ghost (`.PHONY`, no recipe, `make X` says "Nothing to
# be done" and exits 0) sailed through as `ghost-check: no ghost targets`,
# exit 0. Two of four probe names were missed — unreliable rather than
# uniformly broken, which is why it looked fine for so long. CI mostly runs
# C.UTF-8, so the gate was WEAKER on a workstation than in CI, backwards from
# what a pre-commit gate should be.
#
# The same reasoning applies to the other pinned sites in this file: any
# `sort -u` deduping names or paths can silently drop entries, so the gates
# that dedup CI targets, tidy file lists and hook stages pin it too.
ghost-check: ## Verify every .PHONY target has a recipe
	@db=$$($(_STD_TMP)); phony=$$($(_STD_TMP)); norecipe=$$($(_STD_TMP)); \
	 trap 'rm -f "$$db" "$$phony" "$$norecipe"' EXIT; \
	 $(MAKE) -rpn --no-print-directory .std-db-goal >"$$db" 2>/dev/null; \
	 sed -n 's/^\.PHONY:[ ]*//p' "$$db" | tr ' ' '\n' | sed '/^$$/d' \
	     | LC_ALL=C sort -u >"$$phony"; \
	 awk '/^[a-zA-Z0-9_.-]+:/ { n = $$0; sub(/:.*/, "", n); \
	                            p = $$0; sub(/^[^:]*:/, "", p); \
	                            b = 1; r = 0; next } \
	      b && / to execute/ { r = 1 } \
	      b && /^$$/ { if (!r && p !~ /[^[:space:]]/) print n; b = 0 } \
	      END { if (b && !r && p !~ /[^[:space:]]/) print n }' "$$db" \
	     | LC_ALL=C sort -u >"$$norecipe"; \
	 ghosts=$$(LC_ALL=C comm -12 "$$phony" "$$norecipe"); \
	 if [ -n "$$ghosts" ]; then \
	     echo "ERROR: .PHONY targets with no recipe behind them:"; \
	     printf '  %s\n' $$ghosts; \
	     echo ""; \
	     echo "  These exit 0 having done nothing."; \
	     exit 1; \
	 fi; \
	 echo "ghost-check: no ghost targets"

# Every `entry: make -s <target>` in .pre-commit-config.yaml must name a target
# make actually defines.
#
# The convention is that hooks dispatch through make, so the config holds make
# TARGET NAMES -- and nothing checked they resolve. doppler pointed a hook at
# `make -s lint-clang-tidy` and pinned clang-tidy in its dev group, but never
# added it to LINT_TOOLS. The target did not exist, so the hook could only die
# with "No rule to make target", and the commit that introduced it said "every
# pre-commit hook dispatches through make". It stayed broken because three
# things hid it at once: `ghost-check` looks for a .PHONY with no recipe and an
# UNDECLARED target is not a ghost, the hook was `stages: [pre-push]` while
# `setup` installs only the pre-commit stage, and `lint` runs pre-commit at the
# default stage so CI never reached it either. Filed as
# just-buildit/just-makeit#943.
#
# Reads make's DATABASE rather than trying each target: `make -n <target>`
# expands recipes and, by the documented recursion rule, still EXECUTES lines
# containing $(MAKE). Probing a target must not run it.
#
# Inert with no config file, so a repo without pre-commit is not asked to care.
hook-dispatch-check: ## Verify every pre-commit `make` dispatch names a real target
	@cfg=.pre-commit-config.yaml; \
	 if [ ! -f "$$cfg" ]; then \
	     echo "hook-dispatch-check: no $$cfg — nothing to check"; \
	     exit 0; \
	 fi; \
	 db=$$($(_STD_TMP)); trap 'rm -f "$$db"' EXIT; \
	 $(MAKE) -rpn --no-print-directory .std-db-goal >"$$db" 2>/dev/null; \
	 n=0; missing=""; \
	 for t in $$(sed -n "s/^[[:space:]]*entry:[[:space:]]*make[[:space:]]\{1,\}\(-s[[:space:]]\{1,\}\)\{0,1\}\([a-zA-Z0-9_.-]\{1,\}\).*/\2/p" "$$cfg"); do \
	     n=$$((n + 1)); \
	     grep -q "^$$t:" "$$db" || missing="$$missing $$t"; \
	 done; \
	 if [ -n "$$missing" ]; then \
	     echo "ERROR: pre-commit dispatches to make targets that do not exist:"; \
	     printf '  %s\n' $$missing; \
	     echo ""; \
	     echo "  Each hook runs \`make <target>\` and can only fail with"; \
	     echo "  'No rule to make target'. Add the target, or fix the entry."; \
	     exit 1; \
	 fi; \
	 : "A config that exists and matched NOTHING is a disarmed gate, not a"; \
	 : "clean one. Quoting every entry -- a valid YAML rewrite -- moved the"; \
	 : "shape out from under the pattern and took all 8 dispatches with it,"; \
	 : "green: the thesis of this gate, reproduced inside the gate."; \
	 if [ "$$n" -eq 0 ]; then \
	     echo "ERROR: $$cfg exists but no \`make\` dispatch matched."; \
	     echo ""; \
	     echo "  Either no hook dispatches through make -- in which case delete"; \
	     echo "  this gate deliberately -- or the \`entry:\` shape has moved and"; \
	     echo "  the pattern no longer sees it. A gate matching nothing is"; \
	     echo "  indistinguishable from a gate passing, which is what it was"; \
	     echo "  written to prevent."; \
	     exit 1; \
	 fi; \
	 echo "hook-dispatch-check: $$n make dispatch(es) resolve"

# ── hook-stage-check ────────────────────────────────────────────────────────
#
# `hook-dispatch-check` above proves each hook names a real target. It says
# NOTHING about whether the hook is ever reached, and that is the hole that let
# two of doppler's gates run nowhere for months (doppler#737).
#
# The mechanism, which is worth stating because every part of it reads healthy
# on its own:
#
#   * a hook at `stages: [pre-push]` is installed by `pre-commit install` ONLY
#     when the config also declares `default_install_hook_types`. Without it,
#     plain `pre-commit install` writes `.git/hooks/pre-commit` and nothing
#     else, so the pre-push hook has no git hook to fire from;
#   * `make lint` runs pre-commit at the DEFAULT stage, so CI does not reach it
#     either.
#
# Both halves are individually reasonable. Together they produce a hook that is
# configured, dispatches correctly, passes `hook-dispatch-check`, and executes
# on no machine and in no pipeline. Its findings count is zero because it never
# looked -- a dead gate that happens to be green, which is the one failure mode
# nothing downstream can distinguish from success.
#
# THE TRAP, recorded because it cost a wrong plan once: clearing a backlog does
# not revive such a gate. The backlog is why it cannot be switched on; it is
# not why it does not run. A repo that fixes every finding still runs the tool
# nowhere.
#
# Checked STATICALLY, from the config alone, because that is the property that
# survives a fresh clone: CI has no `.git/hooks` to inspect, and a check that
# passes only on a developer machine that happens to have run `make setup` is
# the same class of illusion being fixed.
#
# `manual` is exempt and deliberately so: it means "never run automatically",
# which is a choice rather than an accident. A `manual` hook that no target
# invokes is still dead, but that is not knowable from this file.
hook-stage-check: ## Verify every pre-commit hook stage is actually installed
	@cfg=.pre-commit-config.yaml; \
	 if [ ! -f "$$cfg" ]; then \
	     echo "hook-stage-check: no $$cfg — nothing to check"; \
	     exit 0; \
	 fi; \
	 : "Both YAML spellings, because either is valid and a gate that reads"; \
	 : "only one goes quietly blind the day someone reformats the file --"; \
	 : "which is exactly how hook-dispatch-check lost all 8 dispatches."; \
	 parsed=$$(awk ' \
	   function emit(kind, list,   n, i, arr) { \
	     gsub(/[][]/, " ", list); gsub(/,/, " ", list); \
	     n = split(list, arr, /[[:space:]]+/); \
	     for (i = 1; i <= n; i++) if (arr[i] != "") print kind "\t" arr[i]; \
	   } \
	   /^[[:space:]]*#/ { next } \
	   /^[[:space:]]*$$/ { next } \
	   /^[[:space:]]*default_install_hook_types:/ { \
	     v = $$0; sub(/^[^:]*:[[:space:]]*/, "", v); sub(/[[:space:]]*#.*/, "", v); \
	     if (v ~ /[[]/) { emit("install", v); mode = "" } else { mode = "install" } \
	     next \
	   } \
	   /^[[:space:]]*stages:/ { \
	     v = $$0; sub(/^[^:]*:[[:space:]]*/, "", v); sub(/[[:space:]]*#.*/, "", v); \
	     if (v ~ /[[]/) { emit("stage", v); mode = "" } else { mode = "stage" } \
	     next \
	   } \
	   mode != "" && /^[[:space:]]*-[[:space:]]*/ { \
	     v = $$0; sub(/^[[:space:]]*-[[:space:]]*/, "", v); sub(/[[:space:]]*#.*/, "", v); \
	     if (v != "") print mode "\t" v; \
	     next \
	   } \
	   { mode = "" } \
	 ' "$$cfg"); \
	 : "Old pre-commit spelled these without the prefix, and a config using"; \
	 : "the legacy name is correctly wired -- normalise rather than fail it."; \
	 norm() { \
	     case "$$1" in \
	         commit) echo pre-commit ;; \
	         push) echo pre-push ;; \
	         merge-commit) echo pre-merge-commit ;; \
	         *) echo "$$1" ;; \
	     esac; \
	 }; \
	 installed=$$(printf '%s\n' "$$parsed" | sed -n 's/^install\t//p'); \
	 : "No declaration means pre-commit installs the pre-commit type ALONE."; \
	 : "That default is the whole bug: it is silent, and it is not nothing."; \
	 if [ -z "$$installed" ]; then installed=pre-commit; declared=0; else declared=1; fi; \
	 inst=""; for s in $$installed; do inst="$$inst $$(norm $$s)"; done; \
	 n=0; orphan=""; \
	 for s in $$(printf '%s\n' "$$parsed" | sed -n 's/^stage\t//p' | LC_ALL=C sort -u); do \
	     s=$$(norm "$$s"); \
	     [ "$$s" = manual ] && continue; \
	     n=$$((n + 1)); \
	     case " $$inst " in *" $$s "*) ;; *) orphan="$$orphan $$s" ;; esac; \
	 done; \
	 if [ -n "$$orphan" ]; then \
	     echo "ERROR: pre-commit hooks are configured at a stage nothing installs:"; \
	     printf '  %s\n' $$orphan; \
	     echo ""; \
	     if [ "$$declared" = 0 ]; then \
	         echo "  $$cfg declares no \`default_install_hook_types\`, so"; \
	         echo "  \`pre-commit install\` writes .git/hooks/pre-commit and nothing"; \
	         echo "  else. \`make lint\` runs the default stage, so CI does not reach"; \
	         echo "  these either. They run NOWHERE — zero findings because they"; \
	         echo "  never looked."; \
	     else \
	         echo "  $$cfg declares default_install_hook_types ($$inst )"; \
	         echo "  but not the stage(s) above, so nothing installs them."; \
	     fi; \
	     echo ""; \
	     echo "  Fix by giving them an execution home, then PROVE IT BY SABOTAGE:"; \
	     echo "    default_install_hook_types: [pre-commit,$$orphan]"; \
	     echo "  or run the stage from a make target CI invokes:"; \
	     echo "    \$$(PRE_COMMIT) run --all-files --hook-stage <stage>"; \
	     echo ""; \
	     echo "  Clearing the tool's findings does NOT fix this. A backlog is why"; \
	     echo "  a gate cannot be switched on; it is not why it does not run."; \
	     exit 1; \
	 fi; \
	 echo "hook-stage-check: $$n non-default stage(s) have an execution home"

# ── Help ─────────────────────────────────────────────────────────────────────
# Generated from the `## description` on each active target's rule line. Never
# hand-maintained: a hand-written list is how `make wheel` stayed advertised
# for as long as it did.
help: ## Show this message
	@if [ -t 1 ]; then \
	     c_title=$$(printf '\033[1;36m'); c_target=$$(printf '\033[32m'); \
	     c_reset=$$(printf '\033[0m'); \
	 else \
	     c_title=''; c_target=''; c_reset=''; \
	 fi; \
	 w=0; for t in $(ALL_TARGETS); do [ $${#t} -gt $$w ] && w=$${#t}; done; \
	 echo ""; \
	 echo "$${c_title}$(notdir $(CURDIR)) — make targets$${c_reset}"; \
	 for s in $(_STD_SECTION_ORDER); do \
	     ts=""; \
	     for t in $(ALL_TARGETS); do \
	         $(_STD_SECTION); \
	         [ "$$tsec" = "$$s" ] && ts="$$ts $$t"; \
	     done; \
	     [ -z "$$ts" ] && continue; \
	     echo ""; \
	     echo "$${c_title}$$s:$${c_reset}"; \
	     for t in $$(printf '%s\n' $$ts | LC_ALL=C sort); do \
	         $(_STD_DESC); \
	         printf "  $${c_target}%-*s$${c_reset}  %s\n" "$$w" "$$t" "$$d"; \
	     done; \
	 done; \
	 echo ""

# ── local.mk ─────────────────────────────────────────────────────────────────
# May only ADD targets. Redefining a standard one makes it the fork this file
# exists to prevent — and make would warn about the override anyway.
-include local.mk

# Repo-local targets are named in LOCAL_TARGETS (in the Makefile or local.mk),
# which puts them in `.PHONY` and in `help` — and so under the same gates as
# the standard ones. Criterion 2 is "help lists EVERY target", not "every
# standard target": a local target that help omits is exactly as invisible.
ALL_TARGETS = $(STD_TARGETS) $(LOCAL_TARGETS)

.PHONY: $(ALL_TARGETS)
