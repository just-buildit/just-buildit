#!/usr/bin/env bash
#
# ci-tree-tested.sh — has the pushed tree already passed CI, as a PR?
#
# A PR is tested on its merge commit: the base branch at that moment, plus
# the PR. Merge it by rebase or squash and the base branch's `push` run then
# tests the same code a second time, on every merge -- the full matrix,
# for nothing. This answers when that second run has nothing left to prove,
# so a workflow's `changes` job can treat it like a version bump alone
# (`src=false`) and `CI passed` skips the matrix.
#
# The pushed HEAD's tree was already tested exactly when some merged PR
# associated with HEAD has a head commit H such that:
#
#   1. H's tree is HEAD's tree;
#   2. H contains BEFORE, the branch tip this push replaced. Every merge
#      commit the PR was tested on was BEFORE-or-older plus H, and H already
#      contains all of that, so each one's tree is H's tree. Without this a
#      branch that had moved underneath the PR would be skipped, and that
#      composition is exactly what the push run exists to test;
#   3. the newest `CI_CHECK_NAME` check-run on H, reported by GitHub
#      Actions (not any app that names a check the same), succeeded.
#
# So a branch rebased onto the tip before merging lands at zero CI cost, and
# a stale one gets its full run. That is the incentive, on purpose.
#
# Fail-safe in every direction, like ci-changes: no BEFORE, no repository,
# an API error, no merged PR, any condition unmet -- each answers
# tested=false, and the worst outcome is a matrix that was not needed.
#
# Usage:  ci-tree-tested.sh BEFORE
# Env:    GITHUB_REPOSITORY   owner/repo (Actions sets it)
#         CI_CHECK_NAME       the required check's name (default `CI passed`;
#                             standard.mk passes its own, verify-ci's)
#         GH                  the gh binary (default `gh`; tests fake it)
#         GITHUB_OUTPUT       when set, `tested=...` is appended to it
# Prints `tested=true|false` on stdout; the reason goes to stderr.
set -uo pipefail

say() {
    echo "tested=$1"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "tested=$1" >> "$GITHUB_OUTPUT"; fi
    echo "ci-tree-tested: $2" >&2
    exit 0
}

before="${1:-}"
repo="${GITHUB_REPOSITORY:-}"
check="${CI_CHECK_NAME:-CI passed}"
gh="${GH:-gh}"

case "$before" in
    ''|0000000000000000000000000000000000000000)
        say false "no BEFORE (a new branch, or not a push)" ;;
esac
[ -n "$repo" ] || say false "no GITHUB_REPOSITORY"
head="$(git rev-parse HEAD 2>/dev/null)" || say false "not a git checkout"
tree="$(git rev-parse 'HEAD^{tree}')"

prs="$("$gh" api "repos/$repo/commits/$head/pulls" \
         --jq '.[] | select(.merged_at != null) | .head.sha')" \
    || say false "cannot list the PRs for $head"
[ -n "$prs" ] || say false "no merged PR is associated with $head"

for h in $prs; do
    htree="$("$gh" api "repos/$repo/git/commits/$h" --jq .tree.sha)" \
        || { echo "ci-tree-tested: cannot read $h" >&2; continue; }
    if [ "$htree" != "$tree" ]; then
        echo "ci-tree-tested: PR head $h has another tree" >&2; continue
    fi
    rel="$("$gh" api "repos/$repo/compare/$before...$h" --jq .status)" \
        || { echo "ci-tree-tested: cannot compare $before...$h" >&2; continue; }
    case "$rel" in
        ahead|identical) ;;
        *) echo "ci-tree-tested: $h does not contain $before ($rel)" >&2
           continue ;;
    esac
    # -f on a GET is a query parameter, so gh does the URL-encoding and no
    # standalone jq is needed (a C-only repo has none).
    verdict="$("$gh" api -X GET "repos/$repo/commits/$h/check-runs" \
        -f check_name="$check" --jq '[.check_runs[] | select(.app.slug == "github-actions")]
              | sort_by(.started_at) | last | .conclusion // ""')" \
        || { echo "ci-tree-tested: cannot read the checks on $h" >&2; continue; }
    if [ "$verdict" = success ]; then
        say true "$head is PR head $h's tree, which contains $before and passed '$check'"
    fi
    echo "ci-tree-tested: '$check' on $h is '${verdict:-absent}'" >&2
done
say false "no merged PR head both contains $before and passed '$check' on this tree"
