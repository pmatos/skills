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

if timeout "${TIMEOUT_SECONDS}s" gh pr checks "$PR_NUMBER" --watch --fail-fast -i 15 2>&1; then
  exit 0
else
  RC=$?
  if [[ $RC -eq 124 ]]; then
    echo "TIMEOUT: CI checks did not complete within ${TIMEOUT_MINUTES} minutes" >&2
    exit 2
  fi
  exit $RC
fi
