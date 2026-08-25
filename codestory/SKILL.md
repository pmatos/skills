---
name: codestory
description: This skill should be used when the user asks to "walk me through this code", "tell me the story of this PR", "explain this branch", "explain this diff", "help me review this", "what does this code actually do", "narrate this codebase", "codestory", or wants code explained as a running narrative alongside the code itself so they can review it. Turns a PR, branch, working-tree diff, file, path or whole project into a flow-ordered story told beat by beat, pausing after each beat, with every claim anchored to path:line. Also triggered by the /codestory command.
argument-hint: "[pr-number | branch | file | path | --diff]"
user-invocable: true
---

# codestory — code as a running narrative

Turns a target into a story a reviewer reads: flow-ordered prose alongside the
actual code, told in beats, pausing after each one.

**This is a comprehension aid for code review. It explains so the human can
judge; it never judges.** Stating *"this early return skips the cleanup below"*
is the job. Stating *"this is a bug"* or *"this should be refactored"* is not —
that is `/code-review`'s lane, and blurring the two makes this skill a worse
version of it. See `references/markers.md`.

Interactive only. There is no headless mode: without someone to checkpoint with,
this is a document generator, which is a different tool.

Treat "Can I reach the user right now?" as the deciding factor — running inside
a subagent, under `claude -p`, or anywhere `AskUserQuestion` is unavailable
means the answer is no. Surface that and exit rather than narrating into the
void.

## The rule that matters most

**Never describe code you have not read in this session.**

Lens agents produce *leads* — pointers to where something interesting lives.
Leads are never quoted as fact. Before narrating a beat, read the actual source
for that beat and write only from what was just read. Every excerpt carries a
`path:line` anchor, so every sentence in the story is falsifiable in one
keystroke.

A fluent, wrong story is worse for a reviewer than no story at all.

## Bundled resources

The deterministic shell logic lives in `scripts/`; the craft lives in
`references/`. Invoke the script by its absolute path. When loaded as a plugin
that path is `${CLAUDE_PLUGIN_ROOT}/codestory/scripts/<name>`; if
`${CLAUDE_PLUGIN_ROOT}` is unset (skill loaded standalone), resolve `scripts/`
relative to this SKILL.md. The examples below abbreviate the prefix as
`scripts/`.

- **`scripts/resolve-target.sh`** — step 1 target resolution, exclusions and
  size tiering. Contract below.
- **`references/lenses.md`** — the lens roster, triage rules, the lead record
  format. Read before step 3.
- **`references/dispatch.md`** — how lens agents are spawned, their prompt
  templates, where leads land. Read before step 3.
- **`references/narration.md`** — voice, beat definition, excerpt and example
  rules. Read before step 4.
- **`references/markers.md`** — the five markers and the never-evaluate rule.
  Read before step 5.
- **`references/story-format.md`** — the story file template, resume and
  staleness. Read before step 2.

## Workflow

### 1. Resolve the target

With an explicit argument, the argument wins:

| Argument | `--kind` |
| --- | --- |
| `--diff`, `diff`, `working`, or a dirty tree the user pointed at | `working-tree` |
| all digits (`142`), `#142`, or a PR URL | `pr` |
| a git ref that is not a path (`feat/retry`, `origin/main`) | `branch` |
| an existing file or directory (`src/auth`, `main.py`) | `path` |
| `.`, `--project`, or the repo root | `project` |

When an argument is ambiguous — a branch and a directory share a name — ask
which was meant rather than guessing. Invoked bare, ask via `AskUserQuestion`:

| Option | Means | `--kind` | Shape |
| --- | --- | --- | --- |
| working tree | staged, unstaged and untracked changes | `working-tree` | change |
| PR | a pull request, or the current branch's | `pr` | change |
| branch | **diff against its merge-base with the default branch** | `branch` | change |
| file or path | a file or directory as it stands | `path` | state |
| whole project | the repository as it stands | `project` | state |

Spell out in the option label that *branch* means the branch's diff, not all the
code on it — a reviewer naming a branch means "what did this branch do".

Then run the resolver, passing one of the five literal `--kind` values above:

```bash
scripts/resolve-target.sh --kind <working-tree|pr|branch|path|project> [--ref <ref>]
```

`--ref` is the PR number, branch name or path. For `--kind path` a relative
`--ref` resolves against the invocation directory.

**The resolver is the single source of truth** for target resolution,
exclusions and tiering. Do not re-derive any of it.

**Exit 1** — the target could not be resolved: not a git repository, no such
PR or branch, `gh` missing or unauthenticated for a `pr` target, bash older
than 4. The message is on stderr and stdout is empty. Report it and offer the
nearest alternative — for a missing `gh`, that is `--kind branch`, which gives
the same diff against the merge-base without the network.

**Exit 0** — resolved. Read these fields:

| Field | Meaning |
| --- | --- |
| `narratable` | `false` when nothing survives; report the warnings and stop |
| `target.shape` | `change` or `state` — selects the narration shape (step 6) |
| `source_ref` | the revision the story describes; when set, read every file **at it** |
| `tier` | `small` / `medium` / `large` — selects the fan-out (step 3) |
| `loc` | size of what will be narrated: **diff churn** for change targets — added and removed lines, deletions included — file lines for state targets |
| `files` | the narratable set, each with its own `loc` |
| `excluded` | dropped, with a reason each |
| `deleted` | paths the change removes |
| `formatting_only` | probably whitespace churn — still narratable |
| `warnings` | surface every one of these verbatim |

Warnings are never decorative. In particular, **a dirty working tree while
narrating a branch or PR is a mandatory callout** — the story describes a SHA
that is not what is on disk, and the reviewer's editor is showing something
else.

**`source_ref` decides where every read comes from.** A branch or PR target can
name a commit that is not the one checked out, and then reading a path the
ordinary way returns the wrong revision — or, for a file the change adds,
nothing at all. Whenever `source_ref` is non-empty and differs from `git
rev-parse HEAD`, read source as `git show <source_ref>:<path>`, and say so in
every lens-agent prompt. The resolver already reads blobs; the agents and the
narrator are the ones that have to be told.

**Report the exclusions.** Near the top of the story, before the first beat:
`Skipped 3 files — uv.lock (lockfile), src/api.pb.go (generated),
.stories/pr-99.md (codestory-output)`. Silent omission is the one thing that
would make this skill dangerous for review.

**Deletions are not exclusions.** They have no current content to excerpt, but
the change removes them and the reviewer must be told. Give a removal its own
beat when something depended on it, and a stated line otherwise: `Removed:
src/legacy_client.py`.

**`formatting_only` is a hint, not a verdict.** Git cannot tell whitespace
churn from a line re-indented into an enclosing block, so these files stay in
`files` and stay narratable. Summarise them in a line — `Formatting only:
src/util.c` — rather than giving them beats, and narrate one anyway if the user
asks.

### 2. Check for an existing story, then find the intent

If `.stories/<slug>.md` exists, follow the resume flow in
`references/story-format.md` before dispatching any agent — it may make the
whole gathering step unnecessary. Never resume silently onto code that has
moved.

A reviewer reviews against something. In order of preference:

1. **PR description and title** (`gh pr view`), plus the linked issue
2. **Commit messages** on the range
3. **The tests** covering the target
4. **Nothing** — narrate the code alone

Record which in the story's `intent_source`. Where an intent exists, the story
is told against it and flags what the code does that the intent never mentioned,
with `⟨not in description⟩`. Where none exists, this degrades quietly to
narrating the code on its own; do not manufacture an intent to compare against.

### 3. Triage the lenses and gather leads

Read `references/lenses.md` and pick which of the lenses it defines apply to
this target — the roster lives there, not here. Interfaces is always on. A lens
that would find nothing is not dispatched.

Then read `references/dispatch.md` for the agent prompts and the leads layout.

#### Fan-out by tier

The resolver's `tier` and `shape` decide the shape of the fan-out. No separate
judgement call at runtime.

| Tier / shape | Fan-out | Map |
| --- | --- | --- |
| any change-shaped target, or `small` state (<10k LOC) | **lens-major** — one agent per applicable lens, sweeping the whole target | grounded in read code |
| `medium` state (<50k LOC) | **partition-major** — one agent per subsystem, applying all applicable lenses to its slice, then a cheap merge pass assembling the cross-cutting lists | grounded in read code |
| `large` state (≥50k LOC) | **structural map first**, lens triage over the map, source read lazily at the beat that needs it | structural only |

Partition rule for `medium`: split on **package or workspace boundaries** taken
from the manifests (cargo workspaces, go modules, pnpm/npm workspaces, python
packages). Where there are none, walk the source tree to whatever depth yields
no more than **8 partitions**. Never split a file across agents.

Tell the user the tier and what it costs before spending it, and let them
override: *"62k lines of narratable source, so I'll map this structurally rather
than read all of it — say `read it all` to override."* For a change-shaped
target `loc` is churn, so the number quoted is the size of the change, not of
the files it touches.

Every agent writes leads under `.stories/.<slug>/leads/` — **on disk, not
returned into context**. `references/dispatch.md` gives the file naming per
tier, the prompt templates, and the merge pass that builds the cross-cutting
lists. Leads must outlive the session for resume to work, and a project-scale
lead set would otherwise crowd out the narration.

**The structural map may describe shape and boundaries only.** "Auth lives in
`src/auth/` and exports these three functions" is allowed. "Auth validates
tokens by checking the signature against the JWKS cache" is not — that is a
behavioural claim about unread code. Behaviour waits for the beat that reads it.
Where the repo has `CLAUDE.md`, `AGENTS.md`, `CONTEXT.md` or ADRs, use them as
map input and label anything sourced from prose docs; docs rot.

### 4. Outline, and prune once

Build the beat outline from the leads: one narrative idea per beat, not one code
unit (`references/narration.md`).

For a whole-project target **the map is the outline** — regions with their
proposed beats nested underneath — pruned in a single pass. Do not ask the user
to pick regions and then ask again which beats within them.

Show the outline with its beat count and let the user cut it before any
narration happens: *"34 beats. Which do you want?"* Seeing the cost up front is
what stops a reviewer abandoning at beat 9.

Write the frontmatter, the cast of characters, the skipped-files line and the
pruned outline as a table of contents into `.stories/<slug>.md` before beat 1.

### 5. Narrate, beat by beat

For each beat in the pruned outline:

1. **Read the source** for this beat — at `source_ref` when the resolver set
   one. Not the leads: the source.
2. Write the beat: title naming the idea, prose, one anchored excerpt, markers
   inline where they apply.
3. Append it to `.stories/<slug>.md` and flip its outline entry to `done`.
4. Show it, and checkpoint.

Checkpoint via `AskUserQuestion`:

- **Continue** — next beat
- **Go deeper here** — expand this beat
- **Show the verbatim code** — the excerpt unabridged, in full context
- **Skip this area** — jump past the remaining beats in this region

plus free text for anything else ("jump to the auth module", "is that a bug?").
Answer direct questions directly — the never-evaluate rule constrains what the
*story* volunteers, not whether you engage when asked.

**Go deeper: re-read first, dispatch only on a miss.** Re-read the source around
that spot and expand from it. Spawn a focused agent only when the answer lies
outside what has already been gathered — making every "tell me more" cost thirty
seconds is how the tool stops being used. Write expansions back into the file
under their beat, marked as expansions.

### 6. Close

Write the appendix: the cross-cutting checklists (every external dependency
touched, every path written, every endpoint called) and every marker used,
collected in one place. Leftovers only — never a restatement of the narrative.

Print the story's path, then offer:

- **post as a PR comment** — `gh pr comment <n> --body-file .stories/<slug>.md`.
  Only for a PR target, only on explicit confirmation each time, naming what
  will be posted and where. Never automatic: a PR comment is visible to the
  whole team, and a 30-beat narration dumped onto someone else's PR is a bad
  surprise. A long story may exceed what is reasonable in one comment — offer
  to post the outline plus the appendix instead, with the full story left on
  disk.
- **delete the story file** — and `.stories/.<slug>/` with it; leads are
  working state, not output
- **add `.stories/` to `.gitignore`** — suggest the edit, do not make it unasked

## Anti-patterns

The two that no reference file can catch, because they happen before one is
opened:

- **Quoting a lead as fact.** Leads say where to look. Source says what is true.
  Re-read before every beat.
- **Judging.** Verdicts, smuggled verdicts ("interestingly, the error is
  swallowed"), and rhetorical questions ("is this intentional?").

The rest are spelled out where they belong: literary conceit and lens-shaped
structure in `references/narration.md`, invented examples in
`references/narration.md` and `references/markers.md`.
