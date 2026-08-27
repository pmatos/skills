# Autonomy Contract

What an unattended run may do without being asked, when it must stop instead, and what "done" means. Upstream `improve-codebase-architecture` gates its side effects on conversational turns — an ADR offer, `CONTEXT.md` updates "as decisions crystallize" — and never defines a terminal step. Both are answered here.

## Side effects

The rule: **an unattended run may sharpen the vocabulary, but it may not record or reverse a decision.** Vocabulary is recoverable and reviewable in the PR diff. A decision record read by every future run is not something to write without a human.

**May do unilaterally:**

- **Add a term to `CONTEXT.md`** when the deepened module is named after a concept the domain glossary does not yet carry. Create `CONTEXT.md` lazily if absent. This lands in the PR diff, where it is reviewed with everything else.
- **Sharpen a fuzzy `CONTEXT.md` term** whose current wording is contradicted by the code being deepened. Say so in the PR body.
- **Create or update `.architecture/backlog.md`** and `.architecture/reviews/<date>-<slug>.md`, and commit them.
- **Adopt the branch it was started on, or create one**, then commit, push, and open a PR — see *Definitions of done*. Adoption is bounded to a branch that is demonstrably this run's: non-default, no unique history, **no upstream, and unpublished on origin**. Emptiness alone is not evidence of ownership — a merged topic branch or an ancestor `release/*` branch is also empty, and both are shared. Every condition fails closed to creating a branch.
- **Write tests**, including tests that pin existing behaviour before it moves.

**May not do without a human:**

- **Write a new ADR.** Propose it in the PR body under a `## Proposed ADR` heading, with the title and the decision in full, so a human can accept it with a copy-paste. Upstream offers this in conversation; unattended, the PR body *is* the offer.
- **Edit, supersede, or contradict an existing ADR.** A candidate that contradicts an ADR is reported, never implemented ([ranking.md](ranking.md)).
- **Merge the PR**, or approve it.
- **Force-push, rebase a shared branch, or touch any branch but its own.**
- **Change public/published interfaces** — an exported package surface, a wire format, a CLI contract — beyond what the picked candidate strictly requires. Blast radius 4 candidates are implementable; expanding one mid-flight is not.
- **Delete a backlog entry**, or move a `rejected` entry back to `proposed`. Statuses change; rows stay ([ranking.md](ranking.md)).

## Bail-outs

Every bail-out **writes an exit report and stops**. Silent no-ops are indistinguishable from a crashed run, which is how an unattended routine rots unnoticed.

**Commit before you stop — once the run's branch is settled.** Any artefact already written — report, backlog, work in progress — is committed to the run's branch first. Before check 3 settles that branch (preflight checks 1 and 2, fetch and clean-tree), there is nothing to commit to and nothing has been written: print the exit report to stdout, record `**Committed**: nothing`, and never commit to a branch this run has not yet taken over. A bail-out that leaves the tree dirty makes the *next* firing bail at preflight too, and the one after that, until a human intervenes. That is the failure this contract exists to prevent, so it must not be the contract's own exit path.

### The exit report

One markdown block, printed to stdout and — once the run's branch is settled — appended to `.architecture/backlog.md` under the affected entry (or under a `## Run log` heading when no entry applies). A pre-branch bail (preflight checks 1 and 2) prints it and stops there, writing no file. Fixed fields, so a routine can diff successive runs:

```markdown
### Run <YYYY-MM-DD> — <outcome>

- **Outcome**: complete | bailed-preflight | bailed-design | bailed-mid-flight | no-candidates
- **Stopped at**: step <n> — <one-line reason>
- **Branch**: <branch name, and `adopted` or `created` — a created branch is `pm-deepen/run-<date>-<time>`, or `pm-deepen/<slug>` once renamed at step 2; an adopted branch keeps the caller's name throughout>
- **Committed**: <what was committed, or "nothing">
- **Evidence**: <failing command and verbatim output, dirty paths, open PR number — whatever a human needs>
- **Next**: <what a human or the next firing should do>
```

`no-candidates` is an **outcome, not a failure**: a tree with nothing automatable to deepen is a good tree. Write the report, commit it, say so.

### Stop before making any change when

- **The working tree is dirty**, ignoring `.architecture/`. Report the dirty paths. Never stash — the stash stack is shared with other worktrees and sessions.
- **No branch can be settled** — the branch you were started on is not adoptable *and* none can be cut from `origin/<default-branch>`. The slug-collision check (an existing `pm-deepen/<slug>` branch) happens at step 2 instead, because no slug exists until a candidate is picked, and it never fires on an adopted branch.
- **An `in-flight` backlog entry still has an open PR** *and this run would implement something*. One PR at a time; a second concurrent architecture PR is unreviewable. Report the open PR number. A `--report-only` run is not blocked by this — it opens nothing.
- **The repo has no test runner**, or the picked candidate's behaviour cannot be pinned by a test. Test-first is not optional here.
- **No candidate survives the hard filters.** Write the report, commit it, **push the branch** unless `--no-pr`, and exit with outcome `no-candidates`. Committing to an unpushed local branch in a cron container is the same invisibility the temp-file HTML had.

`gh` missing or unauthenticated is **not** a bail: degrade to `--report-only` and record it under *Degradations* in the report.

### Stop during design (step 4) when

The report and backlog are already committed at this point, so commit any partial design notes too, leave the branch unpushed, and exit with outcome `bailed-design`.

- **The adjudication criteria cannot separate the designs.** That is a bail-out, not a coin flip.
- **The refactor requires a decision the report did not settle** — a genuine fork with no evidence favouring either side. Record both options in the exit report and leave it for a human.

### Stop mid-implementation when

Commit what exists to the run's branch as a `bail: <slug> — <reason>` commit and leave the branch unpushed for inspection. Do not `git checkout` the work away: the diff is the most useful thing a human gets from a failed run.

- **The quality gate is still red after 3 fix attempts.** Report the failing command and its output verbatim. Do not weaken, skip, or delete a test to get green.
- **The diff exceeds the file-count estimate the candidate was scored on** — more than 2x the estimate, or it reaches a public interface the score did not account for. The score gated the pick; a change that outgrows it was mis-scored. Move the entry to `proposed` with a note, and report.

## Definitions of done

Done depends on the flags. Anything short of the matching list is a bail-out with an exit report, not a completion.

**Common to every run:**

1. The run worked on its own branch — adopted or created — never the default branch.
2. `.architecture/reviews/<date>-<slug>.md` exists **and is committed**, with every candidate scored out of 25.
3. `.architecture/backlog.md` is reconciled and committed, with a status for every candidate seen.
4. The working tree is clean.

**Default run (no flags)** adds:

5. The picked candidate is implemented **test-first**: a test pinning the adjudicated interface was written and seen to fail, then made to pass.
6. The project's quality gate passes. Discover it from `CLAUDE.md`/`AGENTS.md` and the manifests, and run each step as a **separate command** — never `&&`-chained, so a flaky step cannot silently skip the ones after it.
7. A PR is open, whose body carries the problem, the before/after in `codebase-design` vocabulary, a link to the report, the score and the runner-up candidate, the runner-up design and why it lost, any `## Proposed ADR`, and any `CONTEXT.md` terms added.
8. The backlog entry is `in-flight` with its PR number, committed **and pushed**, so the PR itself contains it — a commit that stays local defeats the next run's reconciliation.

**`--no-pr`** — as the default run through condition 6, then: the branch is committed and left unpushed, and the backlog entry stays `proposed` with a note naming the branch. No PR, so no PR number.

**`--report-only`** — the common four, plus the report's `## Design` section explicitly noting that no design pass ran, and the branch pushed unless `--no-pr` is also set. No implementation and no PR is the *correct* outcome, not a shortfall.

**Pruning.** `--report-only` and `no-candidates` runs that *created* their branch push a `pm-deepen/run-*` branch that no PR references, so a recurring routine accumulates them. They carry only `.architecture/` commits: once their content is on the default branch, they are safe to delete. Deleting them is a human's call — this run never removes a branch it did not create in this firing, and an **adopted** branch is never a prune candidate at all: it belongs to whoever prepared it, who may well have their own retention rules for it.

For the default run the PR is the deliverable. A run that produces a beautiful report and no PR has not finished — that is the failure mode this fork exists to close.

## No questions

There is no branch of this skill that asks the user anything. Not to pick a candidate, not to confirm a design, not to confirm a seam under test, not to offer an ADR, not to approve a commit. Where the upstream skill asks, this one decides from the evidence and writes the reasoning into the report, so the decision is auditable after the fact instead of blocking before it.

This extends to skills it calls. `tdd`'s "confirm the seams with the user", and `DESIGN-IT-TWICE.md`'s "show this to the user" and "present designs sequentially", are all pre-empted — see the delegated-skills table in [../SKILL.md](../SKILL.md). Before delegating to any skill not listed there, check it for a step that waits on a human, and override it explicitly or don't delegate.

If a decision genuinely cannot be made from the evidence, that is a bail-out with an exit report — not a question.
