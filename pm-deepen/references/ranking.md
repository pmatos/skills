# Ranking and Backlog Memory

Upstream `improve-codebase-architecture` ends step 2 by asking *"Which of these would you like to explore?"*. An unattended run has nobody to answer, so the pick has to be made from the evidence already gathered. This file defines that pick, and the backlog that stops consecutive runs from re-picking the same thing.

Vocabulary is `codebase-design`'s: **module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**. Use it exactly.

## Scoring a candidate

Score every candidate on four axes before ranking. Each axis is 1–5. Write the four numbers and a one-line justification per axis into the scratchpad — a score with no justification is not a score. The picked candidate's four justifications reach the PR body ([deliverables.md](deliverables.md)); every candidate's total reaches the backlog.

**Leverage (1–5)** — how much a caller or test gains per unit of interface, once deepened.

| Score | Signal |
|---|---|
| 5 | Deepening pays back across many call sites *and* removes a whole class of test setup |
| 4 | Several call sites simplify, or one deeply-nested caller stops reaching past the seam |
| 3 | One call site simplifies materially |
| 2 | Mostly cosmetic; the interface shrinks but callers do the same work |
| 1 | Fails the deletion test — complexity would just move, not concentrate |

**Locality (1–5)** — how much change, bugs, and verification would concentrate in one place afterwards. Score 5 when a change that currently forces edits in several files would become a one-file edit.

**Blast radius (1–5, inverted)** — how much code the refactor touches. **Lower is better**, so it enters the total inverted. Judge by files edited and by whether the change crosses a public/published interface.

| Score | Meaning | Files |
|---|---|---|
| 1 | Contained: no published interface changes | 1–3 |
| 2 | A module and its direct callers | 4–8 |
| 3 | Several modules, or one signature used across the repo | 9–20 |
| 4 | Crosses a package/tier seam, or touches a published interface | 21–40 |
| 5 | Repo-wide rename or migration | 41+ |

Where the band description and the file range disagree — a two-file change that still crosses a package seam — **the description wins**; the ranges are a sanity check, not the definition.

Alongside the band, record a **file-count estimate**: the actual number of files you expect to edit. The band gates the pick; the estimate is what step 5 watches the real diff against, and a band alone is too coarse to catch a refactor running away.

**Heat (1–5)** — how recently and how often the involved files changed (`git log`). YAGNI applies: deepening pays off through *future* changes, so cold code scores low no matter how shallow it looks.

### Total

```
score = (leverage x 2) + locality + heat + (6 - blast_radius)
```

Leverage is doubled because it is the axis the whole exercise exists to move. The range is **5 to 25**: worst is `(1x2) + 1 + 1 + (6-5) = 5`, best is `(5x2) + 5 + 5 + (6-1) = 25`. Always render a score as `n/25`.

The inverted blast-radius term is what keeps an unattended run from picking a repo-wide migration it cannot finish or review in one PR.

### Hard filters, applied before ranking

A candidate that trips any of these is **not eligible to be picked**. Record it and its filter in the backlog so the next run does not re-derive it:

- **Leverage is 1.** It failed the deletion test. It is not a deepening candidate.
- **Blast radius is 5.** Too large for one unattended PR. It is recorded `dropped`, with `too large to automate` as its reason, for a human to schedule.
- **It contradicts an ADR.** Never auto-implemented, whatever it scored — reopening a recorded decision is not a unilateral side effect ([autonomy-contract.md](autonomy-contract.md)). When the friction is strong enough to warrant reopening that ADR, its reason carries the conflict callout ([deliverables.md](deliverables.md)) so a human can act on it; when it isn't, drop it quietly.
- **It is already in the backlog** as `landed`, `rejected`, `dropped`, or `in-flight` (see below).
- **It is not covered by tests and cannot be**, i.e. there is no way to pin current behaviour before changing it. Test-first is the terminal step; a candidate that cannot be pinned cannot be implemented unattended.

### Picking

Rank surviving candidates by total, descending. **Take the top one.** Do not ask.

Break a tie by, in order: lower blast radius, then higher heat, then the candidate whose files were touched most recently. Ties are broken deterministically so two runs over an unchanged tree pick the same candidate.

If the top two are within 1 point of each other, say so in the PR body — it tells a reviewer the pick was close and that the runner-up is the natural next firing.

## The backlog

Persist the ranked list at `.architecture/backlog.md`, committed to the repo. Without it, a recurring run re-surfaces the same candidates every firing. This path is fixed, because step 0 has to find it without being told where it is. It is also the only file this skill writes under `.architecture/`, and the only durable record a `--report-only --no-pr` run leaves ([autonomy-contract.md](autonomy-contract.md)).

Every firing reads this file in full before it does anything else, so its length is a running cost paid by every future run. That is what the compaction rule below is for.

Each **active** entry — `proposed` or `in-flight`:

```markdown
## <slug>

- **Status**: proposed | in-flight
- **Score**: 22/25 (leverage 5, locality 4, blast radius 2, heat 4)
- **Files**: ~6 estimated
- **Modules**: `src/audio/mixer.ts`, `src/audio/graph.ts`
- **Summary**: one sentence, in CONTEXT.md domain vocabulary
- **First seen**: 2026-08-27
- **PR**: #580 (`in-flight` only)
```

`<slug>` is a kebab-case identifier derived from the modules and the deepening, e.g. `mixer-graph-single-seam`. Dedup depends on re-deriving the *same* slug for the same candidate rather than inventing a new one, so before adding an entry, read the existing slugs and reuse one that already describes this candidate. Slug derivation is a judgement call, not a hash — the reuse check is what makes it hold.

### Compaction: settled entries are rows, not sections

A `landed`, `dropped`, or `rejected` entry is settled. Nothing will re-read its score, its file estimate, or its first-seen date — only four things ever consult it again, and all four fit on one line:

- the `already in the backlog` hard filter needs the slug and the status;
- slug reuse needs the slug and the one-line summary;
- reconcile step 4 re-checks a `dropped` entry's filter, which needs the reason, the modules, and the score the filter was applied to;
- the definition of done ([autonomy-contract.md](autonomy-contract.md)) requires a score for every candidate seen, settled ones included;
- a human reading the file wants to know what was tried and why it is not being retried.

So **every settled entry is one row of a single table** under a `## Settled` heading, and only `proposed` and `in-flight` keep the full section form above:

```markdown
## Settled

| Slug | Status | Score | Summary | Modules | PR / reason |
|---|---|---|---|---|---|
| `mixer-graph-single-seam` | landed | 21/25 | One seam over the mixer graph | `src/audio/mixer.ts` | #580 |
| `foo-bar-seam` | dropped | 9/25 | Split the Foo intake in two | `src/foo.ts` | Leverage 1 — complexity would move to callers |
```

Compact an entry at the moment it becomes settled, in the same write that changes its status. Apply the rule to the whole file whenever it is written, so a backlog left in the old shape by an earlier version normalises on the next firing — that is a one-time diff, and the information content is unchanged.

Every cell is **one line**. A reason taken from prose — a closing PR comment, say — is reduced to a single clause, and any `|` in it is escaped as `\|`; the full text is on the PR it came from. A table row that wraps or breaks is worse than a shorter reason.

**This is compaction, not pruning: `Never delete entries` still holds.** A settled row is never removed, however old. Dropping rows re-opens blocker 7, and a row costs a line.

An entry moving *back* to `proposed` — reconcile step 4 finding a filter no longer applies — is promoted out of the table and re-expanded to full form, because it is about to be scored again.

### Status transitions

- **proposed** — surfaced, scored, eligible, not yet started. Set on first sighting.
- **in-flight** — a branch and PR exist for it. Set when the PR is opened.
- **landed** — the PR merged.
- **dropped** — a hard filter excluded it. Machine judgement, so it is *reversible*: a later run that scores it differently may move it back to `proposed`, and should say why in the PR body. `Reason` is the filter name.
- **rejected** — a human declined it, or a run bailed out for a reason that will recur. Never re-proposed by a run; only a human moves it back. `Reason` is required.

The distinction matters: `dropped` keeps a machine's call from hardening into a permanent veto, while still excluding the candidate from today's pick so blocker 7 stays closed.

### Reconciling before you rank

At the start of every run, refresh the backlog before scoring anything, so the dedup filter works from truth rather than from whatever the last run left behind:

1. Fold in any uncommitted `.architecture/backlog.md` residue from an interrupted run, then reconcile against `gh`. Anything else uncommitted under `.architecture/` is not this run's: leave it untracked and out of the commit, so residue never lands in an unrelated PR.
2. For each `in-flight` entry with a PR number, `gh pr view <n> --json state,mergedAt`. Merged → `landed`. Closed unmerged → `rejected`, with the closing comment as the `Reason`. Still open → leave `in-flight`; a run that would implement something stops here ([autonomy-contract.md](autonomy-contract.md)), a `--report-only` run carries on.
3. For each `proposed` entry, re-check that the modules still exist and the friction is still present. A candidate whose friction was fixed by unrelated work becomes `landed` with a note that it was resolved incidentally.
4. For each `dropped` entry, re-check the filter that excluded it. If it no longer applies — the code changed, the ADR was superseded, the blast radius shrank — move it back to `proposed` and say why in the PR body. This re-check must happen **here**, before the hard filters run, or a `dropped` entry is excluded before it can ever be reconsidered and the status is a permanent veto in all but name.
5. Only then score fresh candidates and merge them into the list.

Never delete entries. `landed`, `dropped`, and `rejected` rows are the memory; pruning them re-opens blocker 7. Compact them to table rows instead — see *Compaction* above.

### Run log

The same file also carries exit reports ([autonomy-contract.md](autonomy-contract.md)): `### Run <date>` blocks, appended under the affected `## <slug>` entry, or under a trailing `## Run log` heading when no entry applies. When reading existing slugs, read only level-2 headings other than `Run log` and `Settled` — the `### Run` blocks are history, not candidates.

**Keep a block only for a run that bailed out or degraded.** Those are the runs a human needs to see, and the ones a routine diffs successive firings to detect. A clean run already has two records that outlive it — its PR and the status it wrote — so a third, in the file every future firing reads end to end, buys nothing. Drop a retained block once the condition it reports is gone: a `gh`-unavailable degradation is worth reading until `gh` works again, not a year later.
