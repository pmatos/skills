---
name: codex-2nd-opinion
description: This skill should be used when the user asks to "get a second opinion", "ask codex", "what does GPT think", "compare with codex", "run codex", "2nd opinion", "second opinion on this code", or wants an independent analysis from OpenAI Codex CLI. Also triggered by the /codex-2nd-opinion command.
user-invocable: true
---

# Codex Second Opinion

Invoke OpenAI Codex CLI to get an independent analysis on any discussion, plan, code, or thought. Present both perspectives fairly with a structured comparison.

The model and reasoning effort are NOT hardcoded — they come from the user's Codex configuration (`~/.codex/config.toml`, project-level `.codex/config.toml`, or Codex defaults). This matches the philosophy used by OpenAI's own `codex-plugin-cc`: pass through only when the user explicitly asks for a specific model or effort, otherwise let Codex's own config decide.

## Workflow

### Step 1: Gather Context

Collect everything needed for a self-contained prompt to Codex (which has ZERO conversation context):

- The user's question or issue.
- Claude's current analysis or position on the topic.
- The actual code or content under discussion — read the relevant files using the Read tool. Do NOT summarize; include the real content.
- Any constraints, requirements, or prior decisions from the conversation.

### Step 1.5: Create Temp File

Run `mktemp /tmp/codex-2op-XXXXXX` via Bash. Remember the returned path (e.g. `/tmp/codex-2op-a8Kx3m`) — you will substitute it into later steps.

### Step 2: Compose Codex Prompt

Write a fully self-contained prompt to the temp file created above. This file must include:

1. The actual code/file contents (not summaries or references).
2. Claude's current analysis of the situation.
3. The specific question being asked.
4. Any constraints or context the user has mentioned.

Structure the prompt clearly with markdown headings. End the prompt with:

```
Please provide your independent analysis. Be specific and reference the code directly.
```

### Step 3: Run Codex

Execute the following command. Codex writes its response to stdout, which the Bash tool captures directly. **Use a 600000ms (10 minute) timeout on the Bash tool call** — high-reasoning runs can take several minutes.

```bash
codex exec \
  --full-auto --sandbox read-only --ephemeral \
  - < /tmp/codex-2op-XXXXXX  # substitute the actual mktemp path here
```

**Do NOT pass `-m` / `--model` or `-c model_reasoning_effort=...` by default.** Codex reads its model and reasoning effort from `~/.codex/config.toml` (and any project-level `.codex/config.toml`). Letting it resolve its own config means the skill works unmodified for any user.

Only add model/effort flags when the user explicitly asks for a specific one in the triggering message. Accepted effort values: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`. Examples:
- User says "get a second opinion with high reasoning" → add `-c model_reasoning_effort=high`.
- User says "ask GPT-5.5 what it thinks" → add `-m gpt-5.5`.
- User just says "2nd opinion" → no extra flags.

### Step 4: Handle Errors

If the command fails (non-zero exit code or empty stdout):

- Report the error clearly to the user.
- Suggest checking:
  - `codex` is installed and on `$PATH` (install with `npm install -g @openai/codex`).
  - The user is authenticated — `codex login` (ChatGPT account) or `OPENAI_API_KEY` is set for API-key auth.
  - Network connectivity.
  - The configured model is valid — check `~/.codex/config.toml`.
- Skip to Step 6 (Cleanup).

### Step 5: Present and Compare

Present the Bash tool output (Codex's response) under a clear heading:

```
## Codex's Analysis
```

If Codex's response mentions the model it ran under (it usually does in its header lines), include that in parentheses, e.g. `## Codex's Analysis (gpt-5.5, high reasoning)`. Otherwise keep the heading generic — don't guess.

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
rm -f /tmp/codex-2op-XXXXXX  # substitute the actual mktemp path here
```
