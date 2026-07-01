# Dispatch Mechanics — Native path (`Agent` tool)

This is the concrete binding of pm-plan's abstract dispatch verb — **"dispatch a read-only subagent with mission M"** — for orchestrators that have a native subagent tool (e.g. Claude Code, with the `Agent`/`Task` tool).

If your only way to run another model/process is the shell, **do not use this file** — use `dispatch-codex.md` instead.

## Use the native tool, not `claude -p`

Spawn subagents directly with the `Agent` tool. Do **not** shell out to `claude -p` from this path: that would have a Claude instance launch more Claude instances as separate OS processes — extra startup latency, no shared context, separate auth/rate limits, and harder to observe. The native tool runs subagents in-process and returns their results to you directly.

No temp-file staging is required. There is no `$PLAN_TMP`, no prompt/output files, and no sandbox flag to set — subagent prompts and results are passed in-process. The only thing you write to disk is the plan itself at `.ultraplan/<plan-name>.md`.

## Read-only enforcement (and its asymmetry)

Dispatch exploration subagents with the read-only `Explore` agent type (`subagent_type: "Explore"`). Explore agents cannot `Edit`, `Write`, or `NotebookEdit`, which preserves pm-plan's "no source-tree mutations" contract for the substantive operations.

**Be aware of the asymmetry vs. the shell path.** The shell path enforces read-only with a hard `--allowed-tools "Read,Grep,Glob"` allowlist that also denies `Bash`. The `Explore` agent type has no such allowlist — it *can* run `Bash` — so its read-only property is by agent semantics and intent, not a hard tool denial. In practice Explore agents read, search, and report; they don't mutate the tree. If you need the stricter guarantee, instruct each subagent prompt to remain read-only and avoid state-changing shell commands.

The orchestrator itself still writes the plan file (`.ultraplan/<plan-name>.md`) and may run read-only recon shell commands directly — that is expected and outside the subagent contract.

## Parallelism — multiple Agent calls in one message

To run subagents concurrently, issue **multiple `Agent` tool calls in a single message**. They execute in parallel and you receive all results together. For the Large-task Three-Concern Decomposition, that means three `Agent` calls (architecture / change-surface / risks) in one message.

Give each subagent a self-contained prompt: (1) the task description, (2) its specific mission and scope boundary, (3) what to return (file paths with line numbers, patterns, risks), (4) any project conventions from CLAUDE.md/AGENTS.md. Subagents do not inherit your conversation, so don't rely on shared context.

When all results return, synthesize them directly — no `*.out` files to read.

## Plan namer (cheap/fast model)

Dispatch a one-shot `Agent` call pinned to a fast model with `model: "haiku"`:

> Mission: "Generate a short kebab-case name (2-3 words) that summarizes this task: <task description>. Reply with ONLY the name, nothing else. Example: auth-token-refresh"

Take the returned text as the raw name, then sanitize it as described in SKILL.md Step 3. (You may instead pick the name inline yourself — the Haiku dispatch exists mainly to keep naming cheap on the shell path; on the native path the cost difference is negligible.)

## Adversarial reviewer

Dispatch a single read-only `Explore` subagent as the reviewer:

> Mission: "You are a critical plan reviewer. Read the plan at `.ultraplan/<plan-name>.md` and the source files it references. Find: (1) file references that don't exist, (2) steps that depend on undeclared changes, (3) missing edge cases, (4) steps that could be simplified or merged, (5) scope creep beyond the stated goal. Report issues only — don't rewrite the plan."

Incorporate valid criticisms into the plan; for phantom references or critical issues, fix and re-validate.

## Prerequisites for this path

- A harness with a native subagent tool (the `Agent`/`Task` tool) and the read-only `Explore` agent type.
- Standard read-only recon utilities available to the orchestrator: `git`, `find`, `grep`/`rg`. No `claude` CLI, `codex`, `mktemp`, or sandbox flag needed.
