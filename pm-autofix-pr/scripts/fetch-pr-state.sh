#!/usr/bin/env bash
# fetch-pr-state.sh — Fetch comprehensive PR state (CI, reviews, comments)
#
# Usage: fetch-pr-state.sh <owner> <repo> <pr_number> <gh_user> [log_tail_lines]
#
# Outputs JSON to stdout with keys:
#   ci_failures      — array of {name, conclusion, app_slug, fixable, run_id, log_excerpt}
#   review_threads   — array of unresolved threads with full comment chains
#   review_summaries — array of actionable review summaries (supersession applied)
#   pr_comments      — array of PR conversation comments (self-comments filtered)
#   head_sha         — current PR head SHA
#   errors           — array of strings; non-empty means some feeds failed to fetch

set -euo pipefail

OWNER="$1"
REPO="$2"
PR_NUMBER="$3"
GH_USER="$4"
LOG_TAIL_LINES="${5:-500}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

ERRORS="[]"

# --- Fetch head SHA ---
# Guarded so transient API failures surface in the structured `errors` output
# instead of aborting the whole script under `set -euo pipefail`.
if ! HEAD_SHA=$(gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}" --jq '.head.sha' 2>"$TMPDIR/err_sha.txt"); then
  ERRORS=$(echo "$ERRORS" | jq --arg e "head_sha: $(cat "$TMPDIR/err_sha.txt")" '. + [$e]')
  HEAD_SHA=""
fi

# --- CI check runs ---
: > "$TMPDIR/checks_raw.jsonl"
if [[ -n "$HEAD_SHA" ]]; then
  if ! gh api "repos/${OWNER}/${REPO}/commits/${HEAD_SHA}/check-runs" --paginate \
    --jq '.check_runs[] | {id, name, status, conclusion, app_slug: .app.slug}' \
    > "$TMPDIR/checks_raw.jsonl" 2>"$TMPDIR/err_ci.txt"; then
    ERRORS=$(echo "$ERRORS" | jq --arg e "ci_check_runs: $(cat "$TMPDIR/err_ci.txt")" '. + [$e]')
    : > "$TMPDIR/checks_raw.jsonl"
  fi
fi

# Filter for terminal non-success conclusions
CI_FAILURES="[]"
while IFS= read -r check; do
  conclusion=$(echo "$check" | jq -r '.conclusion // empty')
  case "$conclusion" in
    failure|timed_out|cancelled|startup_failure|action_required) ;;
    *) continue ;;
  esac

  app_slug=$(echo "$check" | jq -r '.app_slug // empty')
  check_name=$(echo "$check" | jq -r '.name')
  check_id=$(echo "$check" | jq -r '.id')
  fixable=false
  log_excerpt=""

  if [[ "$conclusion" == "failure" && "$app_slug" == "github-actions" ]]; then
    fixable=true
    # For GitHub Actions, the check-run `id` equals the jobs.id, so `gh run view
    # --job` fetches logs for exactly this job — avoiding the prior bug where
    # every failing check on the SHA got logs from the first workflow run.
    # Best-effort: log fetching can fail for many reasons (expired, permissions, etc.)
    log_excerpt=$(gh run view --job "$check_id" --log-failed 2>&1 | tail -"$LOG_TAIL_LINES" || true)
  fi

  entry=$(jq -n \
    --arg name "$check_name" \
    --arg conclusion "$conclusion" \
    --arg app_slug "$app_slug" \
    --argjson fixable "$fixable" \
    --arg check_id "$check_id" \
    --arg log_excerpt "$log_excerpt" \
    '{name: $name, conclusion: $conclusion, app_slug: $app_slug, fixable: $fixable, check_id: $check_id, log_excerpt: $log_excerpt}')
  CI_FAILURES=$(echo "$CI_FAILURES" | jq --argjson e "$entry" '. + [$e]')
done < "$TMPDIR/checks_raw.jsonl"

# --- Unresolved review threads (GraphQL, paginated) ---
# Paginate review threads so large PRs (>100 threads) do not hard-fail
# convergence. Each thread includes the first 100 comments plus a
# `latestComment` alias for reliable rejection-tracking of long threads.
: > "$TMPDIR/thread_pages.jsonl"
THREADS_CURSOR=""
THREADS_FETCH_OK=true
while :; do
  if [[ -z "$THREADS_CURSOR" ]]; then
    cursor_args=()
  else
    cursor_args=(-f cursor="$THREADS_CURSOR")
  fi
  if ! page=$(gh api graphql -f query='
    query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $number) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id
              isResolved
              isOutdated
              path
              line
              comments(first: 100) {
                pageInfo { hasNextPage }
                nodes {
                  id
                  databaseId
                  body
                  author { login }
                  createdAt
                }
              }
              latestComment: comments(last: 1) {
                nodes { id databaseId author { login } createdAt }
              }
            }
          }
        }
      }
    }
  ' -f owner="$OWNER" -f repo="$REPO" -F number="$PR_NUMBER" "${cursor_args[@]}" 2>"$TMPDIR/err_threads.txt"); then
    ERRORS=$(echo "$ERRORS" | jq --arg e "review_threads: $(cat "$TMPDIR/err_threads.txt")" '. + [$e]')
    THREADS_FETCH_OK=false
    break
  fi
  echo "$page" | jq -c '.data.repository.pullRequest.reviewThreads.nodes[]' >> "$TMPDIR/thread_pages.jsonl"
  has_next=$(echo "$page" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage')
  [[ "$has_next" == "true" ]] || break
  THREADS_CURSOR=$(echo "$page" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor')
done

if [[ "$THREADS_FETCH_OK" == "true" ]]; then
  THREAD_NODES=$(jq -s '.' "$TMPDIR/thread_pages.jsonl")
else
  THREAD_NODES='[]'
fi

UNRESOLVED_THREADS=$(echo "$THREAD_NODES" | jq '[.[] | select(.isResolved == false)]' 2>/dev/null || echo '[]')
RESOLVED_THREAD_IDS=$(echo "$THREAD_NODES" | jq '[.[] | select(.isResolved == true) | .id]' 2>/dev/null || echo '[]')

# --- Review summaries with supersession logic ---
if ! REVIEWS_RAW=$(gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/reviews" --paginate \
  --jq '.[] | select(.body != "" and .body != null) | {id, body, state, user: .user.login, submitted_at: .submitted_at}' \
  2>"$TMPDIR/err_reviews.txt"); then
  ERRORS=$(echo "$ERRORS" | jq --arg e "review_summaries: $(cat "$TMPDIR/err_reviews.txt")" '. + [$e]')
  REVIEWS_RAW=""
fi

# Apply supersession: group by reviewer, discard reviews before a later APPROVED/DISMISSED
REVIEW_SUMMARIES="[]"
if [[ -n "$REVIEWS_RAW" ]]; then
  REVIEW_SUMMARIES=$(echo "$REVIEWS_RAW" | jq -s '
    [group_by(.user)[] |
      sort_by(.submitted_at) |
      (to_entries
       | map(select(.value.state == "APPROVED" or .value.state == "DISMISSED"))
       | last // {key: -1}
      ).key as $cutoff |
      .[$cutoff + 1:][] |
      select(.state == "CHANGES_REQUESTED" or .state == "COMMENTED") |
      select(.user != "'"$GH_USER"'")
    ]')
fi

# --- PR conversation comments ---
# `gh api --paginate --jq` applies the filter per page and concatenates outputs,
# so wrapping with `[...]` would emit one array per page (invalid JSON when
# there are multiple pages). Emit a stream of objects and slurp them after.
if ! PR_COMMENTS_RAW=$(gh api "repos/${OWNER}/${REPO}/issues/${PR_NUMBER}/comments" --paginate \
  --jq '.[] | {id, body, user: .user.login, created_at} | select(.user != "'"$GH_USER"'")' \
  2>"$TMPDIR/err_comments.txt"); then
  ERRORS=$(echo "$ERRORS" | jq --arg e "pr_comments: $(cat "$TMPDIR/err_comments.txt")" '. + [$e]')
  PR_COMMENTS_RAW=""
fi

PR_COMMENTS="[]"
if [[ -n "$PR_COMMENTS_RAW" ]]; then
  PR_COMMENTS=$(echo "$PR_COMMENTS_RAW" | jq -s '.')
fi

# --- Output ---
jq -n \
  --arg head_sha "$HEAD_SHA" \
  --argjson ci_failures "$CI_FAILURES" \
  --argjson review_threads "$UNRESOLVED_THREADS" \
  --argjson resolved_thread_ids "$RESOLVED_THREAD_IDS" \
  --argjson review_summaries "$REVIEW_SUMMARIES" \
  --argjson pr_comments "$PR_COMMENTS" \
  --argjson errors "$ERRORS" \
  '{
    head_sha: $head_sha,
    ci_failures: $ci_failures,
    review_threads: $review_threads,
    resolved_thread_ids: $resolved_thread_ids,
    review_summaries: $review_summaries,
    pr_comments: $pr_comments,
    errors: $errors
  }'
