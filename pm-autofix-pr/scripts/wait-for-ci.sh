#!/usr/bin/env bash
# wait-for-ci.sh — Wait for CI checks to complete on a PR
#
# Usage: wait-for-ci.sh <pr_number> [timeout_minutes]
#
# Exit codes:
#   0 — all checks passed
#   1 — one or more checks failed
#   2 — timeout exceeded
#   3 — error fetching status

set -euo pipefail

PR_NUMBER="$1"
TIMEOUT_MINUTES="${2:-20}"
TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))

# Capture the real exit status of `timeout`. Using `if ...; then exit 0; fi`
# and then reading `$?` would return the `if` compound's status (0 when the
# then-branch did not run), which would mask the 124 timeout signal.
RC=0
timeout "${TIMEOUT_SECONDS}s" gh pr checks "$PR_NUMBER" --watch --fail-fast -i 15 2>&1 || RC=$?

if [[ $RC -eq 0 ]]; then
  exit 0
fi

if [[ $RC -eq 124 ]]; then
  echo "TIMEOUT: CI checks did not complete within ${TIMEOUT_MINUTES} minutes" >&2
  exit 2
fi

# Independently verify status to distinguish a genuine CI failure (exit 1)
# from an infrastructure/auth/rate-limit error (exit 3). `gh pr checks`
# collapses both into non-zero exits, so callers need a separate signal.
if ! status_json=$(gh pr checks "$PR_NUMBER" --json bucket 2>&1); then
  echo "ERROR: Could not fetch CI status after watch failed: $status_json" >&2
  exit 3
fi

if echo "$status_json" | jq -e 'any(.[]; .bucket == "fail")' > /dev/null 2>&1; then
  exit 1
fi

echo "ERROR: gh pr checks --watch exited $RC but no failed bucket found — treating as infrastructure error" >&2
exit 3
