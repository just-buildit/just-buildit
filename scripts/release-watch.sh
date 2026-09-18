#!/usr/bin/env bash
#
# release-watch.sh — autonomously see a tagged release through to verified.
#
# CANONICAL. Vendored verbatim by adopters and gated by `make standard-check`;
# per-repo variation is configuration below, never an edit to this file.
#
# Given a version, finds its release.yml run, streams job outcomes, recovers
# from ONE pre-publish flake (rerun a failed job, or cancel+rerun a hung one),
# and verifies the artifacts a consumer actually touches: PyPI (per-version
# endpoint, then `latest`, which lags 30-60s), the GitHub Release (published,
# not a draft, has notes), and optionally release assets.
#
# The recovery is SAFE because release.yml gates the PyPI publish behind the
# wheel smoke test: while the publish has not succeeded, nothing has reached
# PyPI, so a rerun cannot double-publish. Once it succeeds we never rerun — a
# later failure is a real problem for a human, and re-uploading an existing
# version would fail.
#
# Usage:  REPO=owner/name RW_PKG=dist-name scripts/release-watch.sh <x.y.z>
# See:    skills://release-process
set -uo pipefail

VERSION="${1:?usage: REPO=owner/name RW_PKG=dist release-watch.sh <x.y.z>}"
REPO="${REPO:?set REPO=owner/name}"
PKG="${RW_PKG:?set RW_PKG=<PyPI distribution name>}"
TAG="v$VERSION"

# ── Configuration ────────────────────────────────────────────────────────────
# A pre-publish job in_progress this long is treated as a hung runner.
HANG_MIN="${HANG_MIN:-25}"

# The job that publishes to PyPI, as a jq regex. ANCHORED BY DEFAULT, and that
# is the whole point: an unanchored `publish` also matches "Artifact smoke
# (pre-publish) / …" and "Publish multi-arch manifest". Measured on
# just-makeit's v0.57.0 run, the loose form matched 14 jobs, 12 of them
# pre-publish smoke tests that succeed BEFORE PyPI is touched — so `published`
# went true early and every recovery path below was unreachable. The recovery
# had never been able to run.
#
# Direction of danger is asymmetric, which is why this is validated rather than
# merely documented: a matcher that is too BROAD only forfeits recovery, while
# one that matches NOTHING would let a rerun fire after a successful publish.
RW_PUBLISH_JOB="${RW_PUBLISH_JOB:-^publish$}"

# Jobs ineligible for a pre-publish cancel+rerun: the publish jobs themselves
# and everything downstream. Deliberately a union covering both spellings in
# use across the org (`github-release` and `Create GitHub release`), because
# over-excluding only declines a recovery, while under-excluding could cancel
# something that has already shipped.
RW_POST_JOBS="${RW_POST_JOBS:-publish|post-release|github.release|create github|container|docker|manifest}"

# Release assets to require, for projects that attach build products. 0 = skip.
RW_MIN_ASSETS="${RW_MIN_ASSETS:-0}"
RW_ASSET_PATTERN="${RW_ASSET_PATTERN:-\\.tar\\.gz$}"

RETRIED=0

echo "release-watch: $REPO $TAG"

# The PyPI publish already succeeded? Recovery is only safe while this is false.
published() {
  gh run view "$RUN" -R "$REPO" --json jobs --jq \
    "[.jobs[] | select(.name|test(\"$RW_PUBLISH_JOB\";\"i\"))
              | select(.conclusion==\"success\")] | length" \
    2>/dev/null | grep -q '^[1-9]'
}

# How many jobs the publish matcher sees at all, whatever their conclusion.
# Zero on a COMPLETED run means the matcher is wrong for this repo, and we must
# not guess: that is the one direction in which a rerun could double-publish.
publish_job_count() {
  gh run view "$RUN" -R "$REPO" --json jobs --jq \
    "[.jobs[] | select(.name|test(\"$RW_PUBLISH_JOB\";\"i\"))] | length" \
    2>/dev/null
}

# ── 1. Find the release run for the tag (it may lag the push by a few seconds).
#
# Matched on the tag's COMMIT as well as its name. Selecting on the name alone
# is not enough once a tag has been deleted and re-pushed: a run for the
# PREVIOUS push still carries that `headBranch`, so the "wait for the run to
# appear" loop below is satisfied on its first iteration by a run that finished
# hours ago -- and a tag push returns before GitHub has created the new run, so
# the stale one is all there is to find at that moment.
#
# Measured on just-makeit v0.74.0 (2026-09-01): the first attempt failed its
# pre-publish smoke, the tag was deleted, the defect fixed and the tag
# re-pushed. `release-watch` then attached to the FIRST run and reported its
# failure -- twelve red smoke jobs, `publish: skipped` -- while the real run
# was still in progress and went on to publish cleanly. The ordering was never
# wrong; `[0]` is the newest. The existence check was.
#
# That is the failure mode this script's own header already warns about: a
# watcher that can report the wrong run is worse than no watcher, because the
# failure it invents is indistinguishable from a real one and the first
# instinct is to go fix a release that is already fine.
#
# Resolving the SHA from the REMOTE, not a local ref: `release-watch` is a
# separate target from `tag-release` and may be run from a checkout that never
# had the tag, or has a stale one. `^{}` dereferences the annotated tag object
# to the commit it points at -- without it this compares against the tag
# object's own SHA and never matches.
TAG_SHA=$(git ls-remote "https://github.com/$REPO" "refs/tags/$TAG^{}" 2>/dev/null | cut -f1)
if [ -z "$TAG_SHA" ]; then
  # An unannotated tag has no peeled ref; fall back to the tag ref itself.
  TAG_SHA=$(git ls-remote "https://github.com/$REPO" "refs/tags/$TAG" 2>/dev/null | cut -f1)
fi
if [ -n "$TAG_SHA" ]; then
  echo "  tag $TAG -> ${TAG_SHA%"${TAG_SHA#???????}"}"
else
  echo "  warning: could not resolve $TAG to a commit; matching on tag name alone"
fi

RUN=""
for i in $(seq 1 12); do
  if [ -n "$TAG_SHA" ]; then
    RUN=$(gh run list --workflow=release.yml -R "$REPO" -L 15 \
          --json databaseId,headBranch,headSha \
          --jq "[.[] | select(.headBranch==\"$TAG\" and .headSha==\"$TAG_SHA\")][0].databaseId" \
          2>/dev/null)
  else
    RUN=$(gh run list --workflow=release.yml -R "$REPO" -L 15 \
          --json databaseId,headBranch \
          --jq "[.[] | select(.headBranch==\"$TAG\")][0].databaseId" 2>/dev/null)
  fi
  [ -n "$RUN" ] && [ "$RUN" != "null" ] && break
  echo "  waiting for release run to appear ($i/12)…"; sleep 10
  RUN=""
done
if [ -z "$RUN" ]; then echo "::error:: no release.yml run found for $TAG"; exit 1; fi
echo "  run: $RUN  (https://github.com/$REPO/actions/runs/$RUN)"

# ── The CI-on-the-tagged-commit repair ──────────────────────────────────────
# release.yml's "Verify CI passed on the tagged commit" job polls for the
# `CI passed` check on the tag's SHA and refuses to publish unless it is green.
# When THAT is what failed, rerunning the RELEASE run is useless: the verify job
# simply re-reads the same completed failure and fails again in under a second,
# burning the one recovery on something that could never have worked. That is
# exactly what happened to doppler v0.42.0 — a `setup-uv` manifest fetch timed
# out in one of six Python jobs, long after every wheel had already built.
#
# The repair has to start one run earlier, on CI itself. `wait_ci` tolerates the
# check-run being ABSENT (jq -> null): rerunning a run withdraws its check until
# it re-completes, so "absent" means in-flight, not failed.
ci_run_id() {   # <sha> -> the databaseId of the run that owns `CI passed`
  gh api "repos/$REPO/commits/$1/check-runs" --paginate \
    --jq '[.check_runs[] | select(.name=="CI passed")][0].details_url' 2>/dev/null \
    | sed -n 's#.*/actions/runs/\([0-9]\{1,\}\)/.*#\1#p'
}

wait_ci() {     # <sha> -> 0 when `CI passed` concludes success, 1 otherwise
  local sha="$1" line
  for _ in $(seq 1 80); do   # 80 x 30s = 40 min, above a full CI run
    line=$(gh api "repos/$REPO/commits/$sha/check-runs" --paginate \
           --jq '[.check_runs[] | select(.name=="CI passed")][0]
                 | "\(.status) \(.conclusion // "")"' 2>/dev/null)
    case "$line" in
      "completed success") return 0 ;;
      "completed "*)       return 1 ;;
    esac
    sleep 30
  done
  return 1
}

# ── 2. Watch, recovering from one pre-publish flake or hang.
declare -A SEEN
while true; do
  J=$(gh run view "$RUN" -R "$REPO" --json status,conclusion,jobs 2>/dev/null)
  [ -z "$J" ] && { sleep 15; continue; }

  # Report newly-completed jobs (docker manifest jobs are noise here).
  while IFS=$'\t' read -r name concl; do
    [ -z "$name" ] && continue
    if [ -z "${SEEN[$name]:-}" ]; then echo "  - $name: $concl"; SEEN[$name]=1; fi
  done < <(echo "$J" | jq -r '.jobs[]
            | select(.status=="completed")
            | select((.name|test("docker|manifest";"i"))|not)
            | "\(.name)\t\(.conclusion)"')

  STATUS=$(echo "$J" | jq -r '.status')
  CONCL=$(echo "$J" | jq -r '.conclusion // ""')

  if [ "$STATUS" = "completed" ]; then
    [ "$CONCL" = "success" ] && break

    # Every job exists now, so the matcher can be held to account. Matching
    # nothing means we cannot tell whether PyPI already has this version.
    if [ "$(publish_job_count)" = "0" ]; then
      echo "::error:: RW_PUBLISH_JOB (/$RW_PUBLISH_JOB/) matched no job in this run."
      echo "  Refusing to auto-recover: without it, a rerun could re-publish."
      echo "  Jobs in this run:"
      echo "$J" | jq -r '.jobs[] | "    " + .name'
      exit 1
    fi

    if [ "$RETRIED" = 0 ] && ! published; then
      # Did the CI-verify gate fail? Then CI is what needs rerunning, not us.
      if echo "$J" | jq -e '[.jobs[] | select(.conclusion=="failure")
              | select(.name|test("verify ci";"i"))] | length > 0' \
              >/dev/null 2>&1; then
        SHA=$(gh run view "$RUN" -R "$REPO" --json headSha --jq .headSha 2>/dev/null)
        CIRUN=$(ci_run_id "$SHA")
        if [ -n "$CIRUN" ]; then
          echo "  CI is red on ${SHA:0:8} — rerunning ITS failed jobs first…"
          gh run rerun "$CIRUN" -R "$REPO" --failed >/dev/null 2>&1 || true
          if ! wait_ci "$SHA"; then
            echo "::error:: CI still red on $SHA — a real failure, not a flake"
            exit 1
          fi
          echo "  CI is green — rerunning the release run…"
        fi
      fi
      # NAME the jobs instead of guessing at a cause. This printed
      # "likely a flake" unconditionally — including for the verify-ci case
      # diagnosed immediately above, which is deterministic and was the
      # cause every time it appeared (just-makeit#1327: the verify job's
      # poll window was shorter than main's CI, so the first attempt timed
      # out on every release cut straight after a merge).
      #
      # A diagnosis we already have beats a guess we print, and "flake" is
      # the one word that stops the next reader looking — it is also what
      # made a deterministic, reproducible failure read as noise for three
      # releases.
      FAILED_JOBS=$(echo "$J" | jq -r '[.jobs[]
          | select(.conclusion=="failure") | .name] | join(", ")' \
          2>/dev/null)
      echo "  run failed before publish — rerunning once (one recovery," \
           "then it stops)."
      echo "  failed: ${FAILED_JOBS:-<could not read job list>}"
      gh run rerun "$RUN" -R "$REPO" --failed >/dev/null 2>&1 || true
      RETRIED=1; sleep 20; continue
    fi
    echo "::error:: release run concluded '$CONCL' (no safe auto-recovery left)"; exit 1
  fi

  # Hang: a pre-publish job stuck in_progress past the threshold.
  if [ "$RETRIED" = 0 ] && ! published; then
    STUCK=$(echo "$J" | jq -r --argjson lim $((HANG_MIN * 60)) --arg post "$RW_POST_JOBS" '
      now as $n | .jobs[]
      | select(.status=="in_progress")
      | select((.name|test($post;"i"))|not)
      | select(.startedAt!=null)
      | select(($n - (.startedAt|fromdate)) > $lim)
      | .name' 2>/dev/null | head -1)
    if [ -n "$STUCK" ]; then
      echo "  '$STUCK' stuck >${HANG_MIN}m (hung runner) — cancel + rerun once…"
      gh run cancel "$RUN" -R "$REPO" >/dev/null 2>&1 || true
      for _ in $(seq 1 20); do
        [ "$(gh run view "$RUN" -R "$REPO" --json status --jq .status 2>/dev/null)" = "completed" ] && break
        sleep 10
      done
      gh run rerun "$RUN" -R "$REPO" >/dev/null 2>&1 || true
      RETRIED=1; sleep 20; continue
    fi
  fi
  sleep 25
done

echo "  release run is green — verifying published artifacts…"

# ── 3. PyPI: per-version endpoint first (updates first), then `latest` (lags).
ok=0
for i in $(seq 1 12); do
  v=$(curl -s "https://pypi.org/pypi/$PKG/$VERSION/json" | jq -r '.info.version // "absent"' 2>/dev/null)
  [ "$v" = "$VERSION" ] && { ok=1; break; }
  sleep 15
done
[ "$ok" = 1 ] || { echo "::error:: PyPI $PKG $VERSION not present after publish"; exit 1; }
echo "  - PyPI $VERSION present"
for i in $(seq 1 8); do
  l=$(curl -s "https://pypi.org/pypi/$PKG/json" | jq -r '.info.version' 2>/dev/null)
  [ "$l" = "$VERSION" ] && { echo "  - PyPI latest = $VERSION"; break; }
  sleep 15
done

# ── 4. GitHub Release: published, not a draft, has notes (awk extraction ran),
#      and carries however many build assets this project attaches.
rel=$(gh release view "$TAG" -R "$REPO" --json isDraft,body,assets 2>/dev/null)
draft=$(echo "$rel" | jq -r '.isDraft')
notes=$(echo "$rel" | jq -r '.body | length')
if [ "$draft" = "false" ] && [ "${notes:-0}" -gt 0 ]; then
  echo "  - GitHub Release $TAG published (notes: ${notes} chars)"
else
  echo "::error:: GitHub Release $TAG not clean (draft=$draft, notes=${notes:-0})"; exit 1
fi

if [ "$RW_MIN_ASSETS" -gt 0 ]; then
  assets=$(echo "$rel" | jq -r --arg pat "$RW_ASSET_PATTERN" \
           '[.assets[] | select(.name|test($pat))] | length')
  if [ "${assets:-0}" -ge "$RW_MIN_ASSETS" ]; then
    echo "  - release assets matching /$RW_ASSET_PATTERN/: ${assets}"
  else
    echo "::error:: expected >=$RW_MIN_ASSETS assets matching /$RW_ASSET_PATTERN/ on $TAG, found ${assets:-0}"
    exit 1
  fi
fi

echo "release-watch: $TAG SHIPPED + VERIFIED"
