---
name: pm-deepen
description: This skill should be used when the user asks to "deepen a module", "find shallow modules", "run an architecture review", "open a refactor PR", "improve the codebase architecture unattended", or wants a hands-off run that scans a codebase for deepening opportunities, picks the highest-leverage one, implements it test-first, and opens a PR. Runs end to end with no questions, so it is safe for cron jobs, routines, and headless firings. Also triggered by the /pm-deepen command.
argument-hint: "[<path|module>] [--scan-only] [--no-pr]"
user-invocable: true
---

# pm-deepen — Autonomous Architecture Deepening

Surface architectural friction, pick the highest-leverage **deepening opportunity** — a refactor that turns a shallow module into a deep one — implement it test-first, and open a PR. The aim is testability and AI-navigability.

**This skill never asks a question**, and **it writes nothing to the repository but the refactor itself.** Every decision the upstream skill puts to the user is made here from the evidence and stated in the PR body, so it is auditable in review rather than blocking before it. The PR is the deliverable, the report, and the memory. A run that finds nothing worth doing says so and exits — that is a good outcome, not a failure.

> Forked from Matt Pocock's [`improve-codebase-architecture`](https://github.com/mattpocock/skills) (`mattpocock/skills`), which is interactive by design: it presents an HTML report and then grills the user through whichever candidate they pick. The exploration heuristics, candidate fields, and vocabulary discipline are his. This fork replaces the three interactive joints — the candidate pick, the grilling loop, and the GUI deliverable — and adds a terminal step. Upstream is MIT-licensed, Copyright (c) Matt Pocock.

This skill is *informed* by the project's domain model and built on a shared design vocabulary:

- Call the Skill tool with `codebase-design` for the architecture vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles (the deletion test, "the interface is the test surface", "one adapter = hypothetical seam, two = real"). Use these terms exactly, and don't drift into "component", "service", "API", or "boundary".
- `CONTEXT.md` gives names to good seams; ADRs in `docs/adr/` record decisions this skill must not re-litigate.

## Delegated skills

Each is **optional**: if it is not installed, use the stated fallback and note the substitution in the PR body. None of their interactive steps apply — this run has no user to present to.

| Skill | Used at | If absent | Interactive steps to override |
|---|---|---|---|
| `codebase-design` | preamble, step 3 | Use the vocabulary as defined above | `DESIGN-IT-TWICE.md` steps 1 and 3 say to *show* and *present* to the user. There is no user. Carry the problem-space framing and the design comparison into the PR body and continue without pausing. |
| `tdd` | **not called** | Red-green inline at step 4 is the primary path | `tdd` requires the seams under test to be **confirmed with the user** first, and that gate is not worth loading into an unattended run. If you do call it: the seam under test is the interface step 3 adjudicated. Treat it as pre-agreed and do not re-confirm. |
| `domain-modeling` | **not called** | Edit `CONTEXT.md` directly at step 5 | Its ADR-recording step would be pre-empted anyway: this run never writes an ADR. |

## Arguments

**With no arguments, the run does everything**: scan, pick, implement, and open a PR.

- `<path|module>` — scope the scan to this path or module. Skips the hot-spot inference in step 1.
- `--scan-only` — stop after **step 2**. Print the ranked candidates and the pick to stdout; no design pass, no implementation, no PR, no commit. Nothing persists, which is the point: it is for a human watching the output, and for the degraded mode below. **`--report-only` is accepted as an alias**, because existing cron invocations use it; there is no report any more, but silently rejecting the flag a routine already passes would turn every one of its firings into a no-op.
- `--no-pr` — implement and commit on a branch, but don't push or open a PR. The only mode that can leave finished work nowhere a later run will find it, which is acceptable because a human typed it.

## State

**There is no state file.** No backlog, no report, no `.architecture/` directory — earlier versions wrote all three, and nothing ever read them back. Two things already hold everything a later run needs:

- **The tree** remembers landed work. A refactor that merged no longer shows the friction that surfaced it, so the next scan doesn't re-derive it.
- **GitHub** remembers decisions. This skill labels every PR it opens `pm-deepen`, and `gh pr list --label pm-deepen --state all` recovers what past runs did, including the ones that failed.

Where the tree is *not* sufficient — a refactor that landed only half, so the friction is still visible — the label query is what catches it, and re-picking the missing half is usually correct anyway.

## Workflow

### 0. Preflight

Establish that the run can finish before it changes anything. Check in order; on any failure print the exit report and stop.

**Checks 1 and 2 run before the run has settled its branch, so their bail-outs write nothing** — which is now true of every bail-out that has no code to show, since there is no artefact to commit.

1. **Fetch first.** `git fetch origin` — a cron container's local branches are routinely days stale, and both the base branch and the PR query below are read against origin.
2. **Working tree is clean.** Never stash: the stash stack is shared across worktrees and sessions.
3. **Settle the run's branch** now. Never work on the default branch.

   **Adopt the branch you were started on** only when it is demonstrably a branch made *for* this run. Taking it over is what lets a caller find the resulting PR — a harness that prepares a workspace derives the branch name deterministically and then looks for the PR by that head — but adopting the wrong branch means committing to and pushing something shared. All four must hold:

   1. It is **not the default branch**.
   2. It has **no unique history**: `git rev-list --count origin/<default-branch>..HEAD` is 0.
   3. It has **no upstream**: `git rev-parse --abbrev-ref --symbolic-full-name @{u}` fails.
   4. It is **unpublished**: `refs/remotes/origin/<branch>` does not exist after check 1's fetch.

   Conditions 3 and 4 are the ones that matter, and (2) alone is not a substitute. Zero commits ahead proves only that a branch has no history of its own — equally true of a long-lived `release/*` branch that is an ancestor of the default branch, or a topic branch someone left checked out after it merged. Both are shared, both are published, neither was made for this run. Ownership, not emptiness, is the evidence.

   Otherwise cut `pm-deepen/run-<date>-<time>` from `origin/<default-branch>`, to be renamed at step 2. **Never rename an adopted branch**: its name is the caller's identity for this run, and renaming hides the PR from the system that asked for the work.

   Record which path was taken, and when adoption was refused, which condition refused it.
4. **The quality gate is discoverable**: read `CLAUDE.md`/`AGENTS.md` and the manifests, and record the exact commands. A repo with no test runner cannot be deepened test-first — bail.
5. **`gh` is available and authenticated**: `gh auth status`. If it is missing or unauthenticated, **degrade to `--scan-only`**: with no `gh` there is no dedup, so the run cannot safely pick anything to implement and can only print. This is the most common cron-container failure. Say so in the output.
6. **The `pm-deepen` label exists**, or create it: `gh label create pm-deepen --description "Automated architecture deepening" --force`. If the token cannot write labels, fall back to the marker comment `<!-- pm-deepen -->`, which every PR body carries either way, and query with `gh pr list --search "pm-deepen in:body" --state all`. Do **not** fall back to a title prefix: a repo that lints PR titles as conventional commits will reject it, and this skill's own does. Say which mechanism is in use, in the output and the PR body — it is the only dedup key, so a reader has to know which one a future run will trust.

### 1. Scan for candidates

Read `CONTEXT.md` and any ADRs covering the area first, so candidates are named in the project's own vocabulary and don't re-litigate settled decisions.

Without a `<path|module>` argument, infer hot spots from the last 30–90 days of `git log` — the files that change most are where depth pays. Then look for shallowness: an interface nearly as complex as its implementation, callers reaching past a seam, one concept that forces a reader to bounce between modules, the same policy restated at several sites.

Fan out with parallel sub-agents where the tool is available; otherwise scan inline.

### 2. Check prior runs, score, and pick

**Query what past runs did** before scoring anything:

```bash
gh pr list --label pm-deepen --state all --json number,title,state,headRefName,body
```

(or the `in:body` marker search, when preflight check 6 fell back to it)

- **An open PR** — stop. One architecture PR at a time; a second concurrent one is unreviewable. A `--scan-only` run continues, since it opens nothing.
- **A closed, unmerged PR** — a human declined that refactor, or a run bailed there and the draft was closed. Either way, **do not re-pick it**: both mean a human looked and chose not to take it. Read the closing comment where there is one, but a bail draft closed without comment is still a no — absent evidence, the conservative reading is the correct one.
- **A merged PR** — already landed. The tree normally reflects it, but check the PR when a candidate looks like a twin of one: a refactor applied to only one of two parallel implementations leaves real friction, and finishing it is legitimate work.

**Score every surviving candidate** on four axes, 1–5, each with a one-line justification:

- **Leverage** — how much a caller or test gains per unit of interface. 5: pays back across many call sites *and* removes a class of test setup. 4: several call sites simplify, or a deeply-nested caller stops reaching past the seam. 3: one call site simplifies materially. 2: cosmetic; the interface shrinks but callers do the same work. 1: fails the deletion test — complexity moves rather than concentrates.
- **Locality** — how much change, bugs, and verification concentrate in one place afterwards. 5 when a change that currently forces edits in several files becomes a one-file edit.
- **Blast radius** (inverted — lower is better) — 1: contained, no published interface changes, 1–3 files. 2: a module and its direct callers, 4–8. 3: several modules or one signature used repo-wide, 9–20. 4: crosses a package/tier seam or touches a published interface, 21–40. 5: repo-wide rename or migration, 41+. Where the description and the file range disagree, **the description wins**. Record a **file-count estimate** alongside the band — step 4 watches the real diff against it.
- **Heat** — how recently and often the files changed. YAGNI: deepening pays off through *future* changes, so cold code scores low however shallow it looks.

```
score = (leverage x 2) + locality + heat + (6 - blast_radius)
```

Leverage is doubled because it is the axis the exercise exists to move. Range is **5 to 25**; always render as `n/25`.

**Hard filters, applied before ranking.** A candidate tripping any of these cannot be picked:

- **Leverage is 1.** It failed the deletion test.
- **Blast radius is 5.** Too large for one unattended PR; a human schedules it.
- **It contradicts an ADR.** Reopening a recorded decision is not a unilateral side effect. Say so in the output when the friction is strong enough to warrant reopening that ADR, so a human can act on it.
- **It cannot be pinned by a test.** Test-first is the terminal step.

Rank by total, descending, and **take the top one**. Do not ask. Do not stop at a shortlist. Break a tie by, in order: lower blast radius, then higher heat, then most recently touched — deterministically, so two runs over an unchanged tree pick the same candidate.

Rename a *created* branch to `pm-deepen/<slug>` now (`git branch -m`); nothing is pushed yet, so it is free. Never rename an adopted one.

If nothing survives the filters, print the exit report with outcome `no-candidates` and stop. **A tree with nothing automatable to deepen is a good tree**, and on a healthily-deepened repo this becomes the *usual* outcome rather than an exceptional one.

**`no-candidates` opens no PR and pushes nothing** — deliberately. It is the one outcome with no diff to show, and a nightly draft PR saying "nothing to do" is noise that trains a reader to ignore the label, which costs more than it buys. Its record is stdout, which is what a cron captures. Delete the branch on the way out if this run *created* it and never committed to it; an empty branch nobody references is litter, and earlier versions accumulated exactly that. Leave an adopted branch alone — it is the caller's.

If `--scan-only`: print the ranked candidates, their scores and justifications, and the pick, and stop here.

### 3. Design the interface

Now propose interfaces — not before; a candidate is chosen on friction, not on a design you already had in mind.

Call the Skill tool with `codebase-design` and use its **design-it-twice** pattern: spawn 3+ sub-agents in parallel, each briefed to produce a *radically different* interface for the deepened module (minimal surface; maximum flexibility; optimised for the most common caller; ports-and-adapters where dependencies cross a seam). Give each the file paths, coupling details, dependency category, what sits behind the seam, and both vocabularies. Without a sub-agent tool, produce them inline, one fully written out before the next is started.

Then **adjudicate instead of grilling.** Upstream hands the winner to the `grilling` skill, which asks the user a round of questions and waits — no human, no progress. Adjudication picks the winner against fixed criteria, in this order:

1. **Depth** — how much behaviour per unit of interface a caller must learn.
2. **Locality** — where change, bugs, and verification concentrate afterwards.
3. **Seam placement** — is the seam where something actually varies? One adapter is a hypothetical seam; two is a real one.
4. **Test surface** — can the behaviour be exercised through the interface, without reaching past it?
5. **Blast radius** — of two otherwise-equal designs, the smaller diff wins.

Grilling already requires a recommended answer per question, so an adjudicator can settle the same tree from the same evidence. State the criteria and the designs in-transcript — neutrally, without editorializing toward a favourite, since the advisor reads whatever bias is on the record — then consult the advisor to pick. The advisor takes no separate prompt; it reviews the conversation as it stands, so state the criteria immediately before calling it. **If no advisor is available**, adjudicate yourself against the criteria and say so in the PR body.

Carry the winner and the strongest loser into the PR body. If the criteria cannot separate the designs, that is a bail-out, not a coin flip.

### 4. Implement, test-first

Write a test that pins the intended interface, watch it fail, then make it pass. Pin existing behaviour with a test *before* moving it. The seam under test is the adjudicated interface — already agreed, so do not stop to confirm it.

Run the project's quality gate, each step as a **separate command**, never `&&`-chained. Fix failures; after 3 attempts still red, bail out with the failing command and its verbatim output. Never weaken, skip, or delete a test to reach green.

Watch the diff against the file-count estimate. A change that outgrows it was mis-scored — stop and bail rather than pressing on. Do not revert the work: the diff is the most useful thing a human gets from a failed run.

### 5. Land it

Update `CONTEXT.md` if the deepened module is named after a concept the glossary lacks, or if a term the code contradicts needs sharpening. **Do not write an ADR** — propose it in the PR body instead.

Commit with a conventional-commit message. Unless `--no-pr`: push and `gh pr create --label pm-deepen`. The PR body is the entire deliverable, so it carries:

- **Problem** — why the current architecture causes friction. Name the shallowness concretely: the interface is nearly as complex as the implementation, or a caller reaches past the seam, or understanding one concept requires bouncing between modules.
- **Deletion test** — if the module were deleted, does complexity concentrate or just move?
- **Solution** — plain English, what changed.
- **Benefits** — in **leverage** and **locality** terms, and specifically how the test surface improves.
- **Before / After** — two Mermaid diagrams, in that order, each fenced separately and labelled. A dozen nodes at most: convey the deepening, not the whole subsystem. Solid edges are the interface a caller must learn; dashed edges are inside the implementation. State that legend in the body.
- **Score** — the total out of 25 and the four axes with their justifications.
- **Runner-up candidate** — what scored second and why it lost. Say so if the top two were within 1 point: it tells a reviewer the pick was close.
- **Runner-up design** — the interface that lost adjudication, and why.
- **Proposed ADR** — under a `## Proposed ADR` heading, with title and decision in full, so a human can accept it with a copy-paste. Unattended, the PR body *is* the offer.
- **`CONTEXT.md` terms** added or sharpened, and any **degradations** — flags forced, skills absent, sub-agents or advisor unavailable, label fallback in use.
- **`<!-- pm-deepen -->`** — a marker comment, always, so the prior-run query still finds this PR if the label is ever lost or was never writable.

"Runner-up" is used in two senses and both appear: the runner-up **candidate** scored second in the ranking; the runner-up **design** lost adjudication. Always qualify which — never write a bare "runner-up".

Use `CONTEXT.md` vocabulary for the domain and `codebase-design` vocabulary for the architecture. If `CONTEXT.md` defines "Order", write "the Order intake module" — not "the FooBarHandler", and not "the Order service".

**Do not merge the PR, and do not approve it.**

## Autonomy contract

**May do unilaterally:** add a term to `CONTEXT.md`, or sharpen one the code contradicts (create it lazily if absent; it lands in the PR diff where it is reviewed with everything else). Adopt or create a branch, commit, push, open a PR, create the `pm-deepen` label. Write tests, including tests pinning existing behaviour before it moves.

**May not do without a human:** write a new ADR (propose it in the PR body). Edit, supersede, or contradict an existing one. Merge or approve the PR. Force-push, rebase a shared branch, or touch any branch but its own. Change public/published interfaces beyond what the picked candidate strictly requires — a blast-radius-4 candidate is implementable; expanding one mid-flight is not.

### Bail-outs

Every bail-out **reports and stops**. Silent no-ops are indistinguishable from a crashed run, which is how an unattended routine rots unnoticed. Print this to stdout:

```markdown
### pm-deepen <YYYY-MM-DD> — <outcome>

- **Outcome**: complete | bailed-preflight | bailed-design | bailed-mid-flight | no-candidates
- **Stopped at**: step <n> — <one-line reason>
- **Branch**: <name, and `adopted` or `created`>
- **Evidence**: <failing command and verbatim output, dirty paths, open PR number>
- **Next**: <what a human or the next firing should do>
```

**A bail-out that produced real work opens a draft PR** — `gh pr create --draft --label pm-deepen` — with the exit report as its body. This is what keeps a failure as visible as a success, and what stops tomorrow's firing re-picking the same candidate and failing the same way. Commit the work as `bail: <slug> — <reason>` first. Do not `git checkout` it away.

Under `--no-pr` there is no draft PR either, so a bail-out leaves its work on an unpushed local branch that nothing records — the same invisibility the flag accepts on the success path. That is the trade a human makes by typing the flag; an unattended routine should never pass it.

**Stop before making any change when:** the working tree is dirty (report the dirty paths; never stash). No branch can be settled. An open `pm-deepen` PR exists *and this run would implement something*. The repo has no test runner, or the picked candidate cannot be pinned by a test. No candidate survives the hard filters — outcome `no-candidates`, which is an outcome, not a failure.

**Stop during design (step 3) when:** the adjudication criteria cannot separate the designs. Or the refactor requires a decision the design pass did not settle — a genuine fork with no evidence favouring either side; record both options and leave it for a human. Neither has code yet, so both print and stop.

**Stop mid-implementation (step 4) when:** the quality gate is still red after 3 fix attempts, or the diff exceeds twice the file-count estimate or reaches a public interface the score did not account for. Both have work, so both open a draft PR.

### Definitions of done

Anything short of the matching list is a bail-out with an exit report, not a completion.

**Every run**: it worked on its own branch — adopted or created — never the default branch, and the working tree is clean.

**Default run** adds: the picked candidate is implemented **test-first**, a test pinning the adjudicated interface having been seen to fail and then pass; the project's quality gate passes, each step run as a separate command; and a PR is open, labelled `pm-deepen`, whose body carries everything in step 5. The PR body is the run's only narrative artefact, so a thin one is a shortfall even when the code is right.

**`--no-pr`**: as the default run, minus the PR — the branch is committed and left unpushed.

**`--scan-only`**: the candidates, their scores and the pick are printed to stdout. No implementation and no PR is the *correct* outcome, not a shortfall.

There is no branch of this skill that asks the user anything. Not to pick a candidate, not to confirm a design, not to confirm a seam under test, not to offer an ADR, not to approve a commit. Where upstream asks, this one decides from the evidence and states the reasoning in the PR, so the decision is auditable in review instead of blocking before it.
