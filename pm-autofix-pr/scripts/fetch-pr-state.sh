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
HEAD_SHA=$(gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}" --jq '.head.sha')

# --- CI check runs ---
if ! gh api "repos/${OWNER}/${REPO}/commits/${HEAD_SHA}/check-runs" --paginate \
  --jq '.check_runs[] | {id, name, status, conclusion, app_slug: .app.slug}' \
  > "$TMPDIR/checks_raw.jsonl" 2>"$TMPDIR/err_ci.txt"; then
  ERRORS=$(echo "$ERRORS" | jq --arg e "ci_check_runs: $(cat "$TMPDIR/err_ci.txt")" '. + [$e]')
  : > "$TMPDIR/checks_raw.jsonl"
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
    # Best-effort: log fetching can fail for many reasons (expired, permissions, etc.)
    run_id=$(gh api "repos/${OWNER}/${REPO}/actions/runs" \
      --jq ".workflow_runs[] | select(.head_sha==\"${HEAD_SHA}\") | .id" 2>/dev/null | head -1 || true)
    if [[ -n "$run_id" ]]; then
      log_excerpt=$(gh run view "$run_id" --log-failed 2>&1 | tail -"$LOG_TAIL_LINES" || true)
    fi
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

# --- Unresolved review threads (GraphQL) ---
if ! THREADS_JSON=$(gh api graphql -f query='
  query($owner: String!, $repo: String!, $number: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $number) {
        reviewThreads(first: 100) {
          pageInfo { hasNextPage }
          nodes {
            id
            isResolved
            isOutdated
            path
            line
            comments(first: 50) {
              pageInfo { hasNextPage }
              nodes {
                id
                databaseId
                body
                author { login }
                createdAt
              }
            }
          }
        }
      }
    }
  }
' -f owner="$OWNER" -f repo="$REPO" -F number="$PR_NUMBER" 2>"$TMPDIR/err_threads.txt"); then
  ERRORS=$(echo "$ERRORS" | jq --arg e "review_threads: $(cat "$TMPDIR/err_threads.txt")" '. + [$e]')
  THREADS_JSON='{}'
fi

UNRESOLVED_THREADS=$(echo "$THREADS_JSON" | jq '
  [.data.repository.pullRequest.reviewThreads.nodes[]
   | select(.isResolved == false)]' 2>/dev/null || echo '[]')

RESOLVED_THREAD_IDS=$(echo "$THREADS_JSON" | jq '
  [.data.repository.pullRequest.reviewThreads.nodes[]
   | select(.isResolved == true) | .id]' 2>/dev/null || echo '[]')

# Check for truncation (fail closed — prevents false convergence on large PRs)
THREADS_TRUNCATED=$(echo "$THREADS_JSON" | jq '
  .data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage // false' 2>/dev/null || echo 'false')
COMMENTS_TRUNCATED=$(echo "$THREADS_JSON" | jq '
  [.data.repository.pullRequest.reviewThreads.nodes[]
   | .comments.pageInfo.hasNextPage] | any' 2>/dev/null || echo 'false')

if [[ "$THREADS_TRUNCATED" == "true" ]]; then
  ERRORS=$(echo "$ERRORS" | jq --arg e "review_threads: truncated — PR has >100 review threads" '. + [$e]')
fi
if [[ "$COMMENTS_TRUNCATED" == "true" ]]; then
  ERRORS=$(echo "$ERRORS" | jq --arg e "review_thread_comments: truncated — a thread has >50 comments" '. + [$e]')
fi

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
if ! PR_COMMENTS=$(gh api "repos/${OWNER}/${REPO}/issues/${PR_NUMBER}/comments" --paginate \
  --jq '[.[] | {id, body, user: .user.login, created_at} | select(.user != "'"$GH_USER"'")]' \
  2>"$TMPDIR/err_comments.txt"); then
  ERRORS=$(echo "$ERRORS" | jq --arg e "pr_comments: $(cat "$TMPDIR/err_comments.txt")" '. + [$e]')
  PR_COMMENTS="[]"
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
