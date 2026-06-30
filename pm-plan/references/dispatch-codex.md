# Dispatch Mechanics — Shell path (`claude -p`)

This is the concrete binding of pm-plan's abstract dispatch verb — **"dispatch a read-only subagent with mission M"** — for orchestrators whose only way to run another model/process is the shell (e.g. OpenAI Codex CLI, which has no native subagent tool).

If you have a native `Agent`/`Task` tool, **do not use this file** — use `dispatch-claude.md` instead. Shelling out to `claude -p` from a harness that already has a native subagent tool spawns redundant nested processes with no shared context.

## Sandbox requirement

Because the workflow writes plan output to `.ultraplan/<plan-name>.md` and stages temp files in `/tmp`, the orchestrator must be invoked with `--sandbox workspace-write` (or higher). `--sandbox read-only` fails at the first write.

This workflow runs **under** the shell harness — never invoke a nested `codex exec` from within it. The orchestrator is the orchestrator; `claude -p` provides the subagents.

## The invocation

Every subagent is a `claude -p` (Claude Code headless print mode) process with an explicit, comma-separated read-only tool allowlist:

```bash
claude -p --allowed-tools "Read,Grep,Glob" --verbose \
       < "$PLAN_TMP/<role>.prompt" \
       > "$PLAN_TMP/<role>.out" 2>&1
```

**Read-only is enforced by the allowlist, not by trust.** Anything not on the list — `Edit`, `Write`, `Bash`, `NotebookEdit`, etc. — is denied by the harness, so pm-plan's "no source-tree mutations outside `.ultraplan/` and `$PLAN_TMP`" guarantee holds regardless of what a subagent's prompt asks for. Do **not** swap the allowlist for any of:

- `--dangerously-skip-permissions` / `bypassPermissions` — defeats the contract entirely.
- `--permission-mode plan` — too restrictive for headless `-p`: plan mode disables Bash and most tools, so the run aborts when a subagent needs a tool that wasn't pre-approved.
- `--permission-mode auto` — *not* read-only despite the name: per Claude's permission-mode docs, auto runs "everything, with background safety checks," auto-approves working-directory writes (so Edit/Write/NotebookEdit inside the source tree go through), and is gated on plan tier (Max/Team/Enterprise/API only — not Pro), CLI ≥ 2.1.83, and supported model (no Haiku support, which would break the plan-namer dispatch).

Treat each `claude -p` call as a self-contained subagent: it has zero conversation context, so the prompt file you pipe into it must be fully self-contained — (1) the task description, (2) the agent's specific mission and scope boundary, (3) what to return (file paths with line numbers, patterns, risks, etc.), (4) any project conventions extracted from CLAUDE.md/AGENTS.md.

## Stage temp files

Create a working directory for prompts and outputs once, up front:

```bash
PLAN_TMP=$(mktemp -d /tmp/pm-plan-XXXXXX)
echo "$PLAN_TMP"
```

Reuse `$PLAN_TMP` for every `claude -p` dispatch in the session. Clean it up only at the end (the final step):

```bash
rm -rf "$PLAN_TMP"
```

## Parallelism — background and `wait`

To run multiple subagents concurrently, background each call (`&`) and `wait` in a **single** Bash command so the orchestrator blocks until all finish:

```bash
claude -p --allowed-tools "Read,Grep,Glob" --verbose < "$PLAN_TMP/arch.prompt"    > "$PLAN_TMP/arch.out"    2>&1 &
claude -p --allowed-tools "Read,Grep,Glob" --verbose < "$PLAN_TMP/surface.prompt" > "$PLAN_TMP/surface.out" 2>&1 &
claude -p --allowed-tools "Read,Grep,Glob" --verbose < "$PLAN_TMP/risks.prompt"   > "$PLAN_TMP/risks.out"   2>&1 &
wait
```

After `wait` returns, read each `*.out` file and synthesize the findings.

## Plan namer (cheap/fast model)

Pin the one-shot name generator to Haiku via `--model`:

```bash
cat > "$PLAN_TMP/name.prompt" <<'EOF'
Generate a short kebab-case name (2-3 words) that summarizes this task:
<paste task description here>

Reply with ONLY the name, nothing else. Example: auth-token-refresh
EOF

claude -p --model claude-haiku-4-5-20251001 \
       --allowed-tools "Read,Grep,Glob" \
       < "$PLAN_TMP/name.prompt" \
       > "$PLAN_TMP/name.out" 2>&1
```

Read the name from `$PLAN_TMP/name.out`, then sanitize it as described in SKILL.md Step 3.

## Adversarial reviewer

A single `claude -p` reviewer, same allowlist, prompt staged under `$PLAN_TMP`:

```bash
cat > "$PLAN_TMP/review.prompt" <<EOF
You are a critical plan reviewer. Read the plan at \`.ultraplan/<plan-name>.md\`
(absolute path: $(pwd)/.ultraplan/<plan-name>.md) and the source files it
references.

Find:
  (1) file references that don't exist,
  (2) steps that depend on undeclared changes,
  (3) missing edge cases,
  (4) steps that could be simplified or merged,
  (5) scope creep beyond the stated goal.

Report issues only — don't rewrite the plan.
EOF

claude -p --allowed-tools "Read,Grep,Glob" --verbose \
       < "$PLAN_TMP/review.prompt" \
       > "$PLAN_TMP/review.out" 2>&1
```

Read `$PLAN_TMP/review.out` and incorporate valid criticisms.

## Prerequisites for this path

- The orchestrator CLI (e.g. `codex`) invoked with `--sandbox workspace-write` or higher.
- `claude` CLI on `$PATH`, authenticated. Subagent dispatch fails immediately without it.
- Standard POSIX shell utilities: `git`, `find`, `grep` (or `rg`), `sed`, `mktemp`, `wait`.
