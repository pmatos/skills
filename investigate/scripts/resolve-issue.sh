#!/usr/bin/env bash
#
# resolve-issue.sh — Phase 1 of the investigate skill.
#
# Resolve a GitHub issue number from an explicit argument or the current branch
# name, then verify it exists. Deterministic: the interactive-vs-non-interactive
# decision stays with the caller.
#
# Usage:
#   resolve-issue.sh [raw-argument]
#
# Exit codes:
#   0  Resolved. The issue number is printed to stdout.
#   2  Unresolved. The caller must ask the user (interactive) or emit the
#      "no issue number" failure (non-interactive). The current branch name is
#      printed to stdout (may be empty) so the caller can compose that message.
#   1  Hard failure. Either an explicit issue does not exist, or `gh` could not
#      reach GitHub (auth/network/API error). A specific message is already on
#      stderr; the caller aborts and relays it.
#
# See ../references/issue-number-resolution.md for the rules and rationale.

arg="${1-}"
arg="${arg#\#}" # accept "#123" as well as "123"
issue=""
issue_source="" # "argument" | "branch" | ""

if [[ "$arg" =~ ^[0-9]+$ ]]; then
  issue="$arg"
  issue_source="argument"
fi

branch="$(git branch --show-current 2>/dev/null)"

if [[ -z "$issue" ]]; then
  lbranch="$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]')"
  # Rule 1: a named issue keyword anchored to a path boundary, followed by an
  # integer. The leading (^|[-/_]) stops names like `hotfix-1.2.3` matching the
  # `fix` alternative inside the word `hotfix` and extracting a version digit.
  if [[ "$lbranch" =~ (^|[-/_])(issue|gh|fix|bugfix|bug|feature|feat)[-/_]?([0-9]+) ]]; then
    issue="${BASH_REMATCH[3]}"
    issue_source="branch"
  else
    # Rule 2: fall back only when the branch contains exactly one integer AND
    # that integer sits on a path-segment boundary. The boundary check rejects
    # names like `pr2024` (digits glued to letters) and any multi-number branch.
    nums="$(printf '%s' "$branch" | grep -oE '[0-9]+')"
    if [[ "$(printf '%s\n' "$nums" | grep -c .)" == "1" ]] &&
      [[ "$branch" =~ (^|[-/_])"$nums"([-/_]|$) ]]; then
      issue="$nums"
      issue_source="branch"
    fi
  fi
fi

if [[ -n "$issue" ]]; then
  # `gh issue view` exits nonzero for two very different reasons — "issue does
  # not exist" and "could not reach GitHub". Capture stderr (JSON goes to
  # /dev/null) and distinguish them.
  gh_err="$(gh issue view "$issue" --json number 2>&1 >/dev/null)"
  gh_exit=$?
  if ((gh_exit != 0)); then
    if printf '%s' "$gh_err" | grep -qE 'Could not resolve|Not Found|HTTP 404'; then
      # Truly does not exist.
      if [[ "$issue_source" == "argument" ]]; then
        printf 'investigate: issue #%s does not exist in this repo.\n' "$issue" >&2
        exit 1
      fi
      issue="" # only ever silently clear a branch-inferred guess
    else
      # Auth / network / API failure — surface and abort regardless of source.
      printf "investigate: 'gh issue view %s' failed: %s\n" "$issue" "$gh_err" >&2
      exit 1
    fi
  fi
fi

if [[ -z "$issue" ]]; then
  printf '%s\n' "$branch" # branch context for the caller's message
  exit 2
fi

printf '%s\n' "$issue"
exit 0
