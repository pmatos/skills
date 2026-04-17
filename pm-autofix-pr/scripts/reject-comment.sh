#!/usr/bin/env bash
# reject-comment.sh — Post a rejection reply to a review thread (does NOT resolve)
#
# Usage: reject-comment.sh <owner> <repo> <pr_number> <comment_database_id> <category> <reason>
#
# Categories: "not-an-issue", "scope-creep", "unrelated", "not-relevant", "style-preference"
#
# Posts a reply explaining why the comment is not being addressed.
# Does NOT resolve the thread — the reviewer can respond if they disagree.

set -euo pipefail

OWNER="$1"
REPO="$2"
PR_NUMBER="$3"
COMMENT_DB_ID="$4"
CATEGORY="$5"
REASON="$6"

case "$CATEGORY" in
  not-an-issue)
    PREFIX="**Not an issue** —" ;;
  scope-creep)
    PREFIX="**Out of scope for this PR** —" ;;
  unrelated)
    PREFIX="**Unrelated to this PR** —" ;;
  not-relevant)
    PREFIX="**Not applicable** —" ;;
  style-preference)
    PREFIX="**Style preference (no change)** —" ;;
  *)
    PREFIX="**No action taken** —" ;;
esac

BODY="${PREFIX} ${REASON}

_This assessment was made by two independent AI reviewers (Claude Opus 4.6 and GPT-5.4). If you disagree, please reply and we'll re-evaluate._"

if ! gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/comments/${COMMENT_DB_ID}/replies" \
    -f body="$BODY" \
    --method POST; then
  echo "ERROR: Failed to post rejection reply for comment ${COMMENT_DB_ID}" >&2
  exit 1
fi
