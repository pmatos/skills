#!/usr/bin/env bash
# reply-and-resolve.sh — Post a reply to a review thread and resolve it
#
# Usage: reply-and-resolve.sh <owner> <repo> <pr_number> <comment_database_id> <thread_node_id> <message>
#
# Posts a reply to the review comment (REST API), then resolves the thread (GraphQL).
# Retries once on 403/429 after 60s. Reply failure is non-fatal (code fix is already pushed).
# Exits non-zero if thread resolution fails — caller must not mark the thread as addressed.

set -euo pipefail

OWNER="$1"
REPO="$2"
PR_NUMBER="$3"
COMMENT_DB_ID="$4"
THREAD_NODE_ID="$5"
MESSAGE="$6"

reply_to_comment() {
  gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/comments" \
    -f body="$MESSAGE" \
    -F in_reply_to_id="$COMMENT_DB_ID" \
    --method POST 2>&1
}

resolve_thread() {
  gh api graphql -f query='
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread { isResolved }
      }
    }
  ' -f threadId="$THREAD_NODE_ID" 2>&1
}

retry_on_rate_limit() {
  local fn="$1"
  local result
  local rc=0
  # Guard command substitutions with `|| rc=$?` so `set -e` does not abort
  # the function before we inspect the exit code and trigger the retry branch.
  result=$($fn 2>&1) || rc=$?

  if [[ $rc -ne 0 ]] && echo "$result" | grep -qE '(403|429|rate limit)'; then
    echo "Rate limited, retrying in 60s..." >&2
    sleep 60
    rc=0
    result=$($fn 2>&1) || rc=$?
  fi

  if [[ $rc -ne 0 ]]; then
    echo "WARNING: $fn failed (non-fatal): $result" >&2
    return 1
  fi
  echo "$result"
}

# Post reply (non-fatal — the code fix is already pushed)
retry_on_rate_limit reply_to_comment || true

# Resolve thread (fatal — caller depends on this to track addressed state)
retry_on_rate_limit resolve_thread
