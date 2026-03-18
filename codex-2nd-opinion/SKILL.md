---
name: codex-2nd-opinion
description: This skill should be used when the user asks to "get a second opinion", "ask codex", "what does GPT think", "compare with codex", "run codex", "2nd opinion", "second opinion on this code", or wants an independent analysis from OpenAI Codex CLI (GPT-5.4). Also triggered by the /codex-2nd-opinion command.
user-invocable: true
---

# Codex Second Opinion

Invoke OpenAI Codex CLI (GPT-5.4 with xhigh reasoning) to get an independent analysis on any discussion, plan, code, or thought. Present both perspectives fairly with a structured comparison.

## Workflow

### Step 1: Gather Context

Collect everything needed for a self-contained prompt to Codex (which has ZERO conversation context):

- The user's question or issue.
- Claude's current analysis or position on the topic.
- The actual code or content under discussion — read the relevant files using the Read tool. Do NOT summarize; include the real content.
- Any constraints, requirements, or prior decisions from the conversation.

### Step 2: Compose Codex Prompt

Write a fully self-contained prompt to `/tmp/codex-2op-input-$$.txt` (using the shell PID for uniqueness). This file must include:

1. The actual code/file contents (not summaries or references).
2. Claude's current analysis of the situation.
3. The specific question being asked.
4. Any constraints or context the user has mentioned.

Structure the prompt clearly with markdown headings. End the prompt with:

```
Please provide your independent analysis. Be specific and reference the code directly.
```

### Step 3: Run Codex

Execute the following command. The `timeout` wrapper enforces a 5-minute limit. Codex writes its response to stdout, which the Bash tool captures directly.

```bash
CODEX=$(command -v codex || echo "$HOME/node_modules/.bin/codex") && \
timeout 300 "$CODEX" exec \
  --full-auto --sandbox read-only --ephemeral \
  - < /tmp/codex-2op-input-$$.txt
```

No `-m` or `-c` flags — the user's `~/.codex/config.toml` already configures `model=gpt-5.4` and `model_reasoning_effort=xhigh`.

### Step 4: Handle Errors

If the command fails (non-zero exit code, timeout, or empty stdout):

- Report the error clearly to the user.
- Suggest checking:
  - `OPENAI_API_KEY` is set and valid
  - `codex` is installed and in `$PATH` (or at `~/node_modules/.bin/codex`)
  - Network connectivity
- Skip to Step 6 (Cleanup).

### Step 5: Present and Compare

Present the Bash tool output (Codex's response) under a clear heading:

```
## Codex's Analysis (GPT-5.4, xhigh reasoning)
```

Present the full response without editorializing. Then provide a structured, honest comparison. Follow these rules strictly:

- **Not dismiss Codex's points** just because they differ from Claude's.
- **Acknowledge when Codex may be right** and Claude may be wrong.
- **Present both perspectives fairly** without bias toward Claude's own analysis.

Use this structure:

```
## Comparison

### Points of Agreement
[Where both analyses align]

### Points of Disagreement
[Present BOTH sides fairly — do not editorialize in Claude's favor]

### Honest Assessment
[Where is Codex stronger? Where is Claude stronger? Be genuinely honest.]

### Recommended Path Forward
[Best synthesis of both analyses]
```

Then ask the user: **"How would you like to proceed? I can follow either analysis, combine specific parts, or take a different direction entirely."**

### Step 6: Cleanup

Remove the temporary input file:

```bash
rm -f /tmp/codex-2op-input-$$.txt
```
