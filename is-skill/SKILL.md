---
name: is-skill
description: This skill should be used when the user asks "is this a skill", "can we extract a skill", "skill extraction", "is there a reusable pattern here", "should this be a skill", "extract skill", or wants to analyze the current session for reusable patterns that could become a Claude Code skill. Also triggered by the /is-skill command.
user-invocable: true
---

# Is-Skill — Skill Extraction Analyzer

Analyze the current session's conversation, context, and work patterns to determine whether the knowledge, workflow, or problem-solving approach used could be extracted into a reusable Claude Code skill. If a skill is worth extracting, classify it as user-level (general, cross-project) or project-specific, then create a GitHub issue in the appropriate repository.

## Workflow

Run Steps 1 and 2 **in parallel** (they are independent). Then run Steps 3-7 sequentially.

### Step 1: Gather Session Context

Mine the current session's conversation to reconstruct what has been happening. Review:

1. The full conversation history available in this session — summarize the key interactions, decisions, and workflows that took place.
2. What tools were used, in what patterns, and how frequently.
3. What domain knowledge was applied (e.g., specific API patterns, debugging strategies, architectural decisions, code generation templates).
4. Whether multi-step workflows were followed that required specific ordering or coordination.
5. Whether the user had to explain the same concept or process multiple times across sessions (check session logs if available).

To check for recurring patterns across sessions, mine session logs:

1. Get the repo root:
```bash
git rev-parse --show-toplevel
```

2. Compute the project session directory. The path encoding replaces `/` with `-`. For example, `/home/user/myproject` becomes `~/.claude/projects/-home-user-myproject/`.

3. For **up to the 5 most recent** session logs, extract user messages and assistant text responses to look for recurring patterns:

```bash
python3 -c "
import json, sys, os

log_dir = sys.argv[1]
if not os.path.isdir(log_dir):
    print('No Claude session history found for this project.')
    sys.exit(0)
files = sorted(
    [f for f in os.listdir(log_dir) if f.endswith('.jsonl')],
    key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
    reverse=True
)[:5]
if not files:
    print('No Claude session logs found.')
    sys.exit(0)

for fname in files:
    path = os.path.join(log_dir, fname)
    session_id = fname.replace('.jsonl', '')
    print(f'\n=== Session: {session_id} ===')
    with open(path, encoding='utf-8') as fh:
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
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get('type') == 'text':
                            texts.append(block['text'][:300])
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
            if '<system-reminder>' in content:
                continue
            print(f'  [{role}] {content[:200]}')
" "$HOME/.claude/projects/<encoded-path>/"
```

### Step 2: Gather Project Context

Determine what project is being worked on and collect metadata needed for issue routing:

1. Identify the current project:
```bash
git rev-parse --show-toplevel
git remote get-url origin 2>/dev/null
```

2. Extract the GitHub **owner/repo** from the remote URL (supports both `https://` and `git@` formats).

3. Read the project's `CLAUDE.md` or `AGENTS.md` if present — understand what conventions and workflows are already codified.

4. Check if this is the `pmatos/skills` repository itself (if so, a "user-level" skill means adding it directly rather than filing an issue).

### Step 3: Analyze for Skill Extraction Potential

With the session context and project metadata in hand, evaluate whether a reusable skill can be extracted. Consider each of these **skill indicators**:

#### Strong Indicators (any one is enough to suggest a skill)
- **Repeated workflow**: The same multi-step process was followed more than once in this session, or appears across multiple sessions.
- **Complex coordination**: A task required orchestrating multiple tools or steps in a specific order that would be hard to remember.
- **Domain knowledge bottleneck**: Specialized knowledge was needed that wouldn't be obvious without experience (API quirks, framework conventions, debugging techniques).
- **User teaching**: The user had to explain a process step-by-step — that explanation IS the skill.

#### Moderate Indicators (two or more suggest a skill)
- **Reusable across projects**: The pattern isn't tied to one specific codebase.
- **Error-prone without guidance**: The workflow has subtle gotchas or ordering constraints.
- **Time-consuming discovery**: Significant exploration was needed before the actual work could begin.
- **Boilerplate generation**: A template or scaffold was created that could be parameterized.

#### Weak Indicators (context-dependent)
- **One-off but educational**: A novel approach was used that could help in future similar situations.
- **Project-specific convention**: A pattern that only matters in this project but would help new contributors.

If **no indicators** are present, report that no skill extraction is warranted and explain why. Stop here.

### Step 4: Classify the Skill

Determine whether the extracted skill should be **user-level** or **project-specific**:

| Criterion | User-Level Skill | Project-Specific Skill |
|-----------|-----------------|----------------------|
| **Scope** | Works across any project | Tied to this project's architecture, APIs, or conventions |
| **Dependencies** | General tools (git, GitHub, language runtimes) | Project-specific frameworks, configs, or domain models |
| **Knowledge** | General engineering patterns | Project-internal knowledge (custom CLI, internal APIs, deployment) |
| **Audience** | Any developer using Claude Code | Contributors to this specific project |
| **Issue target** | `pmatos/skills` | Current project's repository |

### Step 5: Draft the Skill Proposal

Compose a structured skill proposal with:

1. **Skill Name**: Short, descriptive, kebab-case (e.g., `debug-flaky-tests`, `generate-api-client`).
2. **Type**: User-level or Project-specific.
3. **Description**: One paragraph explaining what the skill does and when to trigger it.
4. **Trigger Phrases**: 5-8 natural language phrases a user might say to invoke it.
5. **Workflow Outline**: Numbered steps the skill would follow (3-8 steps).
6. **Extracted Knowledge**: The key insights, patterns, or domain knowledge that make this skill valuable — what would be lost if the session ended without capturing it.
7. **Complexity Estimate**: Simple (< 50 lines SKILL.md), Medium (50-150 lines), or Complex (150+ lines, may need reference files).

Present this proposal to the user and ask:
- Does this look right?
- Any adjustments to the name, scope, or workflow?
- Should I proceed with creating the GitHub issue?

**Do NOT proceed to Step 6 until the user approves.**

### Step 6: Create GitHub Issue

After user approval, create a GitHub issue with the skill proposal.

#### Issue Title
`New skill: <skill-name> — <one-line summary>`

#### Issue Body

Use this template:

```markdown
## Skill Proposal: `<skill-name>`

**Type:** User-level / Project-specific
**Complexity:** Simple / Medium / Complex
**Extracted from:** Session on <today's date>, working on <brief description of what was being done>

### Description

<description from Step 5>

### Trigger Phrases

- "<phrase 1>"
- "<phrase 2>"
- ...

### Proposed Workflow

1. <step 1>
2. <step 2>
3. ...

### Key Knowledge to Capture

<extracted knowledge from Step 5 — the insights that make this skill valuable>

### Example Session Excerpt

<Brief, anonymized excerpt showing the pattern in action — 3-5 lines max>

### Notes

- <any caveats, dependencies, or design considerations>
```

#### Issue Creation

Try the following methods in order to create the issue:

1. **GitHub MCP tools**: Look for `mcp__github__create_issue` or similar tools via ToolSearch. If available, use them.
2. **`gh` CLI**: If available, use a heredoc to avoid shell escaping issues with multi-line markdown:
   ```bash
   gh issue create --repo <owner/repo> --title "<title>" --body "$(cat <<'EOF'
   <body>
   EOF
   )"
   ```
3. **Fallback**: If neither is available, present the full issue title and body to the user and ask them to create it manually. Provide the target repository URL.

For **user-level skills**, the target repo is `pmatos/skills` — unless the current repo IS `pmatos/skills`, in which case skip issue creation and instead add the skill directly (create the `<skill-name>/SKILL.md` file and update `CLAUDE.md` and `README.md`).
For **project-specific skills**, the target repo is the current project's `owner/repo` (from Step 2).

### Step 7: Report

Present a summary to the user:

```
## Skill Extraction Summary

**Skill:** `<name>`
**Type:** <user-level / project-specific>
**Issue:** <link to created issue, or "manual creation needed">
**Repository:** <target repo>

### What Was Captured
<1-2 sentence summary of the key knowledge extracted>

### Next Steps
- [ ] Implement the skill (create `<skill-name>/SKILL.md`)
- [ ] Add to CLAUDE.md and README.md
- [ ] Test with a real session
```
