---
name: wigo
description: This skill should be used when the user asks "what's going on", "wigo", "status", "where was I", "what were we doing", "catch me up", "tree status", "branch status", or wants a comprehensive situational briefing on the current git tree, session history, and associated PR. Also triggered by the /wigo command.
user-invocable: true
---

# WIGO — What Is Going On?

Produce a comprehensive situational briefing on the current git worktree. Gather signals from git state, Claude session logs, and GitHub to reconstruct context and suggest actionable next steps.

## Workflow

Run Steps 1, 2, and 3 **in parallel** (they are independent). Then run Steps 4-6 sequentially.

### Step 1: Git Tree State

Run the following commands via Bash and record the output:

```bash
git rev-parse --show-toplevel
git branch --show-current
git status --short
git stash list
git diff --stat
git diff --cached --stat
git log --oneline -1
```

From the results, determine:
- The **repo root** and **current branch** name.
- Whether the tree is **dirty**: count modified (unstaged), staged, and untracked files separately.
- Whether there are any **stashes**.

### Step 2: Recent Activity from Git Log

```bash
git log --oneline -10
```

Determine the default branch (`main` or `master`):

```bash
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=main
echo "$DEFAULT_BRANCH"
```

Then show commits ahead of it:

```bash
git log --oneline <default-branch>..HEAD
```

From the results, summarize:
- What the recent commits describe (the narrative arc of the work).
- How many commits this branch is ahead of the default branch.

### Step 3: Session Log Mining

Reconstruct what we've been working on from Claude's session logs.

1. Get the repo root from Step 1 (or run `git rev-parse --show-toplevel` again).
2. Compute the project session directory. The path encoding replaces `/` with `-`. For example, `/home/user/myproject` becomes `~/.claude/projects/-home-user-myproject/`.
3. List all `.jsonl` files in that directory, sorted by modification time (most recent first):

```bash
ls -t ~/.claude/projects/<encoded-path>/*.jsonl 2>/dev/null
```

4. For **up to the 5 most recent** session logs, extract user messages and assistant text responses. Use a Python one-liner to pull content snippets:

```bash
python3 -c "
import json, sys, os

log_dir = sys.argv[1]
files = sorted(
    [f for f in os.listdir(log_dir) if f.endswith('.jsonl')],
    key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
    reverse=True
)[:5]

for fname in files:
    path = os.path.join(log_dir, fname)
    session_id = fname.replace('.jsonl', '')
    print(f'\n=== Session: {session_id} ===')
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get('message', {})
            role = msg.get('role')
            if role not in ('user', 'assistant'):
                continue
            content = msg.get('content', '')
            # Handle content that is a list of blocks
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get('type') == 'text':
                            texts.append(block['text'][:300])
                        elif block.get('type') == 'tool_result':
                            pass  # skip tool results
                        elif block.get('type') == 'tool_use':
                            texts.append(f'[tool: {block.get(\"name\", \"?\")}]')
                    elif isinstance(block, str):
                        texts.append(block[:300])
                content = ' | '.join(texts)
            elif isinstance(content, str):
                content = content[:300]
            else:
                continue
            if not content.strip():
                continue
            # Skip system reminders
            if '<system-reminder>' in content:
                continue
            print(f'  [{role}] {content[:200]}')
" "$HOME/.claude/projects/<encoded-path>/"
```

5. Also check for session metadata files to get timestamps:

```bash
ls -t ~/.claude/sessions/*.json 2>/dev/null | head -5
```

For each, read the file and extract `startedAt`, `cwd`, and `kind`.

6. **Synthesize** a narrative from the extracted messages: "In recent sessions, you were working on X. The last session focused on Y."

### Step 4: Find Associated PR

Using the branch name from Step 1, search for an associated pull request:

```bash
gh pr list --head <branch-name> --state all --json number,title,state,url,statusCheckRollup,reviews,mergeable,isDraft,createdAt,updatedAt --limit 1
```

If the result is empty, also try a broader search:

```bash
gh pr list --state open --json number,title,headRefName,url --limit 50
```

and filter the output for the current branch name.

If no PR is found, record "No PR associated with this branch" and skip Step 5.

### Step 5: PR Status Deep-Dive

If a PR was found in Step 4, gather detailed status:

**CI checks:**

```bash
gh pr checks <number> --json name,state,bucket,description,workflow
```

Report each check's name and pass/fail/pending status.

**Reviews:**

From the PR JSON's `reviews` field (already fetched in Step 4), report:
- How many approvals, changes-requested, and pending reviews.
- Who reviewed and their verdict.

If review data wasn't in the Step 4 response, fetch it:

```bash
gh pr view <number> --json reviews --jq '.reviews[] | "\(.author.login): \(.state)"'
```

**Merge status:**

Report the `mergeable` state (`MERGEABLE`, `CONFLICTING`, or `UNKNOWN`) and whether the PR is a draft.

**Recent activity:**

```bash
gh pr view <number> --json comments --jq '{ total: (.comments | length), recent: [.comments[-3:] | .[] | "\(.author.login) (\(.createdAt)): \(.body[0:150])"] }'
```

Report the total comment count. If there are recent comments (last 24 hours), display them.

### Step 6: Synthesize & Present

Combine all findings into a structured report. Use this template:

```
## WIGO: <branch-name>

### Working Tree
- **Status**: Clean / Dirty
  - N files modified (unstaged)
  - M files staged
  - K untracked files
- **Stashes**: none / list them

### What We've Been Doing
<Narrative synthesized from session logs and git history — what was the goal,
what has been accomplished so far, what was the last thing worked on>

### Branch Progress
- **N commits** ahead of <default-branch>
- Recent commits:
  - `abc1234` — commit message
  - `def5678` — commit message
  - ...

### Pull Request
- **PR #N**: <title> (<state>)
  - URL: <url>
  - CI: all passing / N of M checks failing / pending
  - Reviews: N approvals / changes requested by @user / no reviews yet
  - Mergeable: yes / conflicting / unknown
  - Draft: yes / no
  - Comments: N total

### Suggested Next Steps
<contextual suggestions — see below>
```

#### Contextual Suggestions

Analyze the combined state and offer **specific, actionable** suggestions. Choose from the following based on the situation:

- **Clean tree + PR merged**: "Branch work is complete. Consider deleting the branch (`git branch -d <branch>`) and switching to the default branch."
- **Clean tree + PR open + CI green + approved**: "PR is ready to merge. Want me to merge it?"
- **Clean tree + PR open + CI failing**: "CI is failing on these checks: [list]. Want me to investigate the failures?"
- **Clean tree + PR open + changes requested**: "Reviews request changes. Here's what reviewers said: [summary]. Want me to address the review feedback?"
- **Clean tree + PR open + no reviews**: "PR is open but has no reviews yet. Consider requesting a review, or wait for CI to complete."
- **Clean tree + PR open + CI pending**: "CI checks are still running. Wait for results, or investigate if they've been pending too long."
- **Clean tree + no PR + commits ahead**: "You have commits ready but no PR. Want me to create a pull request?"
- **Dirty tree + PR open**: "You have uncommitted changes. Want me to commit and push (`/cp`) to update the PR?"
- **Dirty tree + no PR**: "You have uncommitted work and no PR. Want me to commit (`/cp`) first, then create a PR?"
- **On default branch + clean**: "You're on the default branch with a clean tree. Ready to start something new — create a feature branch?"
- **No commits ahead of default branch**: "This branch has no new commits compared to the default branch. It may be a fresh branch or already merged."

Always present 2-3 of the most relevant suggestions as a numbered list, phrased as questions so the user can pick one.
