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
# A pre-publish job in_progress this long is treated as a hung runner -- unless
# release.yml allows it longer: then its own `timeout-minutes`, plus a margin,
# is the limit (see `hang_limit` below).
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

# ── Each job's hang limit: the time its own workflow allows it ──────────────
# A job is hung only once it has run longer than it is ALLOWED to. HANG_MIN
# alone said 25 minutes for every job, while a release's verify job polls
# main's CI by design for up to an hour (just-makeit's: `timeout-minutes: 75`).
# It cancelled that healthy job as "hung" on v0.93.0, v0.104.0, v0.105.0,
# v0.106.0 and v0.106.1, spending the one recovery each time
# (just-buildit.github.io#70, #140). Two declarations of one number had
# contradicted each other; now the workflow's is the only one.
#
# So the limit for a job is read from release.yml AT THE TAG -- the file the
# watched run is executing, not whatever this checkout holds:
#   - no `timeout-minutes` (or an expression): HANG_MIN, as before;
#   - `timeout-minutes` within HANG_MIN: HANG_MIN, as before;
#   - `timeout-minutes` above it: that, plus HANG_MARGIN_MIN.
# Past its own timeout GitHub ends the job and the run fails, and the
# failed-job rerun path above recovers it. This path stays only as the
# backstop for a job GitHub did NOT end -- exempting such jobs instead would
# leave the watch below, which has no deadline of its own, waiting forever.
HANG_MARGIN_MIN=5
WF_NAMES=() WF_TIMEOUTS=()
WF_PATH=".github/workflows/release.yml"
WF=$(gh api -H "Accept: application/vnd.github.raw" \
     "repos/$REPO/contents/$WF_PATH?ref=${TAG_SHA:-$TAG}" 2>/dev/null)
# Each job's run-time name (its `name:`, else its id) and its job-level
# `timeout-minutes`, read by indentation: a step's own `timeout-minutes` sits
# deeper and is not the job's.
while IFS=$'\t' read -r t n; do
  WF_TIMEOUTS+=("$t") WF_NAMES+=("$n")
done < <(printf '%s\n' "$WF" | awk '
  function flush() {
    if (id != "" && to ~ /^[0-9]+$/)
      printf "%s\t%s\n", to, (nm != "" ? nm : id)
    id = ""
  }
  function value(s) {
    sub(/^[^:]*:[ \t]*/, "", s); sub(/[ \t]+#.*$/, "", s)
    sub(/[ \t]+$/, "", s)
    if (s ~ /^".*"$/ || s ~ /^\047.*\047$/) s = substr(s, 2, length(s) - 2)
    return s
  }
  /^jobs:[ \t]*(#.*)?$/ { injobs = 1; ji = -1; next }
  injobs && /^[^ \t#]/  { flush(); injobs = 0 }
  !injobs || /^[ \t]*(#.*)?$/ { next }
  {
    match($0, /^ */); ind = RLENGTH
    if (ji < 0) ji = ind
    if (ind == ji) {
      flush(); id = $0; sub(/^ */, "", id); sub(/:.*/, "", id)
      nm = ""; to = ""; pi = -1; next
    }
    if (pi < 0) pi = ind
    if (ind != pi) next
    if ($0 ~ /^ *name:/) nm = value($0)
    else if ($0 ~ /^ *timeout-minutes:/) to = value($0)
  }
  END { flush() }')
if [ "${#WF_NAMES[@]}" -eq 0 ]; then
  echo "  note: no job timeouts read from release.yml at $TAG;" \
       "every job is hung past ${HANG_MIN}m"
fi

# A workflow name as a bash pattern for the names its jobs run under: glob
# characters are literal, and each `${{ … }}` expression matches anything.
job_glob() {
  local n="$1" out=""
  n=${n//\\/\\\\}; n=${n//\*/\\*}; n=${n//\?/\\?}; n=${n//\[/\\[}
  # The single-quoted `${{` / `}}` are the LITERAL GitHub expression
  # delimiters being matched, not a shell expansion (SC2016 says otherwise).
  # shellcheck disable=SC2016
  while [[ $n == *'${{'*'}}'* ]]; do
    out+="${n%%'${{'*}*"; n="${n#*'}}'}"
  done
  printf '%s' "$out$n"
}

job_timeout() {  # <job name as the run shows it> -> its timeout-minutes, or ""
  local name="$1" g i t=""
  # The whole name first; then a matrix leg ("name (a, b)") or a reusable
  # workflow's job ("name / job"), so `build` cannot claim `build (x)`'s row.
  for i in "${!WF_NAMES[@]}"; do
    g=$(job_glob "${WF_NAMES[$i]}")
    # shellcheck disable=SC2053  # $g is a pattern on purpose
    [[ $name == $g ]] && { t=${WF_TIMEOUTS[$i]}; break; }
  done
  if [ -z "$t" ]; then
    for i in "${!WF_NAMES[@]}"; do
      g=$(job_glob "${WF_NAMES[$i]}")
      [[ $name == $g" ("* || $name == $g" / "* ]] \
        && { t=${WF_TIMEOUTS[$i]}; break; }
    done
  fi
  printf '%s' "$t"
}

hang_limit() {  # <job name as the run shows it> -> minutes before it is hung
  local t
  t=$(job_timeout "$1")
  if [ -n "$t" ] && [ "$t" -gt "$HANG_MIN" ]; then
    echo $((t + HANG_MARGIN_MIN))
  else
    echo "$HANG_MIN"
  fi
}

# ── The CI-on-the-tagged-commit repair ──────────────────────────────────────
# release.yml's verify job (`make release-verify-ci`) refuses to publish
# unless main's CI certified the tag's commit. When THAT is what failed,
# rerunning the RELEASE run is useless until CI's answer changes: the verify
# job re-reads the same red and fails again in under a second, burning the
# one recovery on something that could never have worked (doppler v0.42.0:
# a `setup-uv` fetch timed out in one of six Python jobs).
#
# So the watch asks CI first, through the SAME script the verify job runs,
# `verify-ci.py` beside this one -- one answer to "did main's CI certify this
# commit?", not a second copy of the lookup. A second copy here read a failed
# API call as "CI finished" and spent the recovery on a CI still queued
# (just-buildit.github.io#226, just-makeit v0.128.0). Its verdicts:
#
#   green       rerun the release: the verify job gave up early, or flaked.
#   red         rerun CI's failed jobs, wait for that attempt, and only if it
#               goes green rerun the release -- unless a NEWER main CI run
#               is still alive (newer_url): main's pushes share one
#               concurrency group holding one pending run, so a rerun on
#               this older commit could cancel the head's. Then, and when
#               GitHub refuses the rerun, STOP as below.
#   alive       CI is still running past the verify job's own allowance;
#   no-check    it was cancelled/superseded before certifying anything;
#   no-run      main never ran CI on the commit;
#   unreadable  GitHub would not answer (or the script could not run):
#               STOP, with the recovery unspent, saying what to do. No rerun
#               of the release can change any of these, and an unknown answer
#               is never read as a finished CI.
#
# How long to wait on a live CI is the verify job's OWN timeout-minutes, read
# from release.yml at the tag like every hang limit above -- the time the
# release already decided CI may take -- else GitHub's 360-minute job maximum,
# which is what a job without one gets. Never a second number here.
GITHUB_JOB_MAX_MIN=360
# The verify job, when it did not succeed. NOT only `failure`: a job that
# reaches its own timeout-minutes is reported `cancelled` (measured:
# just-makeit run 43071316806, `test (ubuntu-latest, 3.9)` ran 55.3 min
# against `timeout-minutes: 55` and concluded `cancelled`, annotated "The
# job has exceeded the maximum execution time of 55m0s"). Matching
# `failure` alone let exactly the #226 case -- a verify job that waited out
# its timeout on a live CI -- fall through to the generic release rerun.
# `timed_out` is listed for completeness; GitHub's docs name it.
VERIFY_JOB_JQ='[.jobs[]
  | select(.conclusion=="failure" or .conclusion=="cancelled"
           or .conclusion=="timed_out")
  | select(.name|test("verify ci";"i")) | .name][0] // empty'
VERIFY_CI="$(dirname "${BASH_SOURCE[0]}")/verify-ci.py"

ci_verdict() {  # <sha> <max-minutes> [min-attempt] -> sets CI_VERDICT CI_RUN_ID CI_ATTEMPT CI_URL CI_NEWER
  local out
  out=$(mktemp)
  CI_VERDICT="" CI_RUN_ID="" CI_ATTEMPT="" CI_URL="" CI_NEWER=""
  REPO="$REPO" SHA="$1" python3 -u "$VERIFY_CI" --max-minutes "$2" \
      --min-attempt "${3:-1}" --out "$out" 2>&1 | sed 's/^/    /'
  while IFS='=' read -r k v; do
    case "$k" in
      verdict) CI_VERDICT=$v ;; run_id) CI_RUN_ID=$v ;;
      run_attempt) CI_ATTEMPT=$v ;; run_url) CI_URL=$v ;;
      newer_url) CI_NEWER=$v ;;
    esac
  done <"$out"
  rm -f "$out"
  # No verdict at all (the script crashed, python3 missing) is unreadable,
  # never a finished CI.
  CI_VERDICT=${CI_VERDICT:-unreadable}
}

ci_stop() {     # <sha> -> exit 1 naming the verdict, the recovery unspent
  local why
  case "$CI_VERDICT" in
    alive)      why="main's CI for it is still running past the verify job's allowance" ;;
    no-check)   why="main's CI for it ended without certifying it (cancelled or superseded): rerun that CI run${CI_NEWER:+ once the newer main run $CI_NEWER has finished -- rerunning it while that one is pending could cancel it}" ;;
    red)        why="it is red, and a newer main CI run ($CI_NEWER) is still alive: rerunning this commit's CI could cancel that one's pending run, so let it finish, then rerun $CI_URL" ;;
    rerun-refused) why="GitHub refused to rerun its failed jobs: $CI_RERUN_ERR" ;;
    no-run)     why="main never ran CI on it: a release must tag a commit main's CI ran" ;;
    *)          why="GitHub did not answer whether main's CI certified it" ;;
  esac
  echo "::error:: CI for $1 is '$CI_VERDICT': $why${CI_URL:+ ($CI_URL)}."
  echo "  The one recovery is NOT spent: no rerun of the release can change"
  echo "  this. Once CI is green on it, run \`make release-watch VERSION=$VERSION\`"
  echo "  again; it reruns the release then."
  exit 1
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
      VJOB=$(echo "$J" | jq -r "$VERIFY_JOB_JQ" 2>/dev/null)
      if [ -n "$VJOB" ]; then
        SHA=$(gh run view "$RUN" -R "$REPO" --json headSha --jq .headSha 2>/dev/null)
        SHA=${SHA:-$TAG_SHA}
        CI_MAX=$(job_timeout "$VJOB")
        CI_MAX=${CI_MAX:-$GITHUB_JOB_MAX_MIN}
        echo "  '$VJOB' did not pass — asking main's CI for ${SHA:0:8} (waiting" \
             "up to ${CI_MAX}m while it is alive) before spending the" \
             "one recovery…"
        ci_verdict "$SHA" "$CI_MAX"
        case "$CI_VERDICT" in
          green) ;;
          red)
            [ -n "$CI_NEWER" ] && ci_stop "$SHA"
            echo "  CI is red on ${SHA:0:8} — rerunning ITS failed jobs first…"
            # A refused rerun (past GitHub's 30-day window, no permission,
            # no failed job to rerun) leaves nothing to wait for: waiting
            # would end hours later as a false 'alive'.
            if ! CI_RERUN_ERR=$(gh run rerun "$CI_RUN_ID" -R "$REPO" --failed \
                                2>&1 >/dev/null); then
              CI_VERDICT=rerun-refused
              ci_stop "$SHA"
            fi
            ci_verdict "$SHA" "$CI_MAX" $(( ${CI_ATTEMPT:-1} + 1 ))
            case "$CI_VERDICT" in
              green) ;;
              red) echo "::error:: CI still red on $SHA after rerunning its" \
                        "failed jobs — a real failure, not a flake" \
                        "${CI_URL:+($CI_URL)}"
                   exit 1 ;;
              *) ci_stop "$SHA" ;;
            esac ;;
          *) ci_stop "$SHA" ;;
        esac
        echo "  CI is green — rerunning the release run…"
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
          | select(.conclusion=="failure" or .conclusion=="cancelled"
                   or .conclusion=="timed_out")
          | "\(.name) (\(.conclusion))"] | join(", ")' \
          2>/dev/null)
      echo "  run failed before publish — rerunning once (one recovery," \
           "then it stops)."
      echo "  failed: ${FAILED_JOBS:-<could not read job list>}"
      gh run rerun "$RUN" -R "$REPO" --failed >/dev/null 2>&1 || true
      RETRIED=1; sleep 20; continue
    fi
    echo "::error:: release run concluded '$CONCL' (no safe auto-recovery left)"; exit 1
  fi

  # Hang: a pre-publish job stuck in_progress past its own limit.
  if [ "$RETRIED" = 0 ] && ! published; then
    STUCK="" LIM=""
    while IFS=$'\t' read -r name secs; do
      [ -z "$name" ] && continue
      lim=$(hang_limit "$name")
      if [ "$secs" -gt $((lim * 60)) ]; then STUCK=$name LIM=$lim; break; fi
    done < <(echo "$J" | jq -r --arg post "$RW_POST_JOBS" '
      now as $n | .jobs[]
      | select(.status=="in_progress")
      | select((.name|test($post;"i"))|not)
      | select(.startedAt!=null)
      | "\(.name)\t\(($n - (.startedAt|fromdate)) | floor)"' 2>/dev/null)
    if [ -n "$STUCK" ]; then
      echo "  '$STUCK' stuck >${LIM}m (hung runner) — cancel + rerun once…"
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
