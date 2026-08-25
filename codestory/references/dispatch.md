# Dispatching lens agents

Lens agents do not write the story. They decide **what matters and where to
look**, and write *leads* to disk. The narrator re-reads the source before
saying anything (`SKILL.md`, "The rule that matters most").

Dispatch with the `Agent` tool, `subagent_type: "general-purpose"`. Lens agents
write their own leads file, and `Explore` agents have no `Write` tool — read-only
behaviour here comes from the prompt constraint below, not from the agent type.
Issue all agents for a stage in a single message so they run in parallel.

## Where leads land

```
.stories/.<slug>/leads/<agent-label>.md
```

- **lens-major**: `<agent-label>` is the lens name — `interfaces.md`, `flow.md`,
  `dependencies.md`, `io.md`, `errors.md`, `context.md`, `tests.md`.
- **partition-major**: one agent covers all lenses for one slice, so the label
  is the partition, path-flattened — `src-auth.md`, `packages-api.md`. Each
  lead still names its lens in the record, so the merge pass can group by lens
  across partitions.
- **large tier**: the structural map lands at `.stories/.<slug>/map.md`, and
  lens triage runs over that map rather than over source.

Create the directory before dispatching. Leads go to disk, never back into the
main context: they must outlive the session for resume to work, and a
project-scale lead set would crowd out the narration.

## The lens-agent prompt

Fill the bracketed slots. Keep the rest verbatim — the constraints are what stop
an agent returning confident prose instead of pointers.

```text
You are gathering LEADS for a code narration. You are not writing the story.

Target: [one line: PR #142, the working tree, src/auth/, …]
Read the narrated files at: [the resolver's `source_ref`, or `the working tree`]
Files to be narrated:
[the resolver's file list, one path per line]

Those files are what the story will cover. To understand them you may read
anything else in the repository — callers, tests, configuration — and run
`git log`, `git blame` and `gh`. Only leads that help a reader understand the
files above belong in your output.

When a revision is named above, read the narrated files as
`git show <revision>:<path>` — that revision is not what is checked out, so an
ordinary read shows you different content, or none where the change adds a file.
Surrounding context you consult to understand them may be read normally.

If a narrated path is a symlink, its content is the link value: read it with
`readlink <path>` rather than following it. What it points at may be outside the
repository, and is not this story's subject.

Your lens: [lens name]
[the lens's "what it looks for" and "salient" text from references/lenses.md]

Write your findings to [absolute path to the leads file], one lead per line:

  path:line — <one line: what is here> — <why it is salient> — [beat-hint]

Rules:
- A lead is a pointer plus a reason. Never write prose, never write more than
  one line per lead. If you find yourself explaining, you are doing the
  narrator's job.
- Nothing you write will be quoted as fact. The narrator re-reads the source.
  Your job is to make sure it looks in the right places.
- Every lead must carry a real path and a real line number you have seen.
- If your lens finds nothing in this target, write the single line
  `NO LEADS` and stop. Do not manufacture findings to fill the file.
- Do not modify any file other than your leads file. Nothing you do should
  change the code being narrated.

Return only: the number of leads written, and one sentence on the biggest thing
a reviewer of this target would want to look at.
```

For **partition-major**, replace the single-lens block with the full list of
applicable lenses and add:

```text
Apply every lens above to your partition. Tag each lead with its lens:

  [lens] path:line — <what is here> — <why salient> — [beat-hint]
```

## The structural map agent (large tier only)

```text
Build a STRUCTURAL map of this repository. Describe shape and boundaries only.

Read: the manifests and build config, the declared entry points, the README,
the directory layout, and the import/dependency graph. Where CLAUDE.md,
AGENTS.md, CONTEXT.md or ADRs exist, read them too.

Write to [absolute path to map.md]:
- The subsystems, one short paragraph each: what lives there, what it exports,
  what it depends on.
- The entry points, with paths.
- The dependency direction between subsystems.
- Anything you took from a prose doc rather than from code, marked
  `(from docs)` — docs rot.

You may state that auth lives in src/auth/ and exports these three functions.
You may NOT state how auth validates a token: that is a behavioural claim about
code you have not read, and the narration rule forbids it. Behaviour waits for
the beat that reads it.
```

## The merge pass

After partition-major, one agent reads every partition's leads file and writes
`.stories/.<slug>/leads/cross-cutting.md`:

```text
Read every file in [leads dir]. Produce the cross-cutting checklists the
appendix needs, grouped by lens tag, deduplicated, each entry keeping its
path:line:

  ## External dependencies
  ## IO and side effects
  ## Error paths with no handler

Do not summarise, rank or comment. This is a merge, not an analysis.
```

Skip the merge pass entirely for lens-major — the per-lens files already are
the grouping.

## Concurrency

Cap concurrent agents at **8**. Lens-major on the full roster is 7, which fits.
Partition-major is capped by the partition count, which the partition rule
already bounds at 8.

## Cleanup

Leads are working state, not output. When a story closes and the user chooses to
delete the story file, delete `.stories/.<slug>/` with it. When the story is
kept, keep the leads — a resumed story re-reads them rather than re-dispatching.
