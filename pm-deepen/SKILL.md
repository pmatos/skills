---
name: pm-deepen
description: This skill should be used when the user asks to "deepen a module", "find shallow modules", "run an architecture review", "open a refactor PR", "improve the codebase architecture unattended", or wants a hands-off run that scans a codebase for deepening opportunities, picks the highest-leverage one, implements it test-first, and opens a PR. Runs end to end with no questions, so it is safe for cron jobs, routines, and headless firings. Also triggered by the /pm-deepen command.
argument-hint: "[<path|module>] [--report-only] [--no-pr]"
user-invocable: true
---

# pm-deepen — Autonomous Architecture Deepening

Surface architectural friction, pick the highest-leverage **deepening opportunity** — a refactor that turns a shallow module into a deep one — implement it test-first, and open a PR. The aim is testability and AI-navigability.

**This skill never asks a question.** Every decision the upstream skill puts to the user is made here from the evidence and written into the report, so it is auditable after the fact rather than blocking before it. That is the whole point of the fork: it has to complete unattended, from a cron firing or a routine, with nobody watching.

> Forked from Matt Pocock's [`improve-codebase-architecture`](https://github.com/mattpocock/skills) (`mattpocock/skills`), which is interactive by design: it presents an HTML report and then grills the user through whichever candidate they pick. The exploration heuristics, candidate-card fields, and vocabulary discipline are his. This fork replaces the three interactive joints — the candidate pick, the grilling loop, and the GUI deliverable — and adds a terminal step and a backlog memory. Upstream is MIT-licensed, Copyright (c) Matt Pocock.

This skill is *informed* by the project's domain model and built on a shared design vocabulary:

- Call the Skill tool with `codebase-design` for the architecture vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles (the deletion test, "the interface is the test surface", "one adapter = hypothetical seam, two = real"). Use these terms exactly in every suggestion, and don't drift into "component", "service", "API", or "boundary".
- `CONTEXT.md` gives names to good seams; ADRs in `docs/adr/` record decisions this skill must not re-litigate.

## References

Read each one at the step that needs it, not all up front:

- [references/ranking.md](references/ranking.md) — the scoring rubric that replaces the "which one?" question, and the backlog that stops runs repeating themselves. **Read before step 2.** Step 0 needs only the fixed backlog path from it.
- [references/report-format.md](references/report-format.md) — the committed markdown deliverable that replaces the temp-directory HTML. **Read before step 3.**
- [references/autonomy-contract.md](references/autonomy-contract.md) — which side effects are unilateral, when to bail out, what the exit report looks like, and what "done" means. **Read before step 0, and consult on any bail-out.**

## Delegated skills

This skill calls three others. Each is **optional**: if it is not installed, use the stated fallback and note the substitution in the report. None of their interactive steps apply here — this run has no user to present to.

| Skill | Used at | If absent | Interactive steps to override |
|---|---|---|---|
| `codebase-design` | preamble, step 4 | Use the vocabulary as defined in this file | `DESIGN-IT-TWICE.md` steps 1 and 3 say to *show* and *present* to the user. There is no user. Write the problem-space framing and the design comparison into the report as artefacts and continue without pausing. |
| `tdd` | **not called** | Red-green inline at step 5 is the primary path | `tdd` requires the seams under test to be **confirmed with the user** before any test is written, and that gate is not worth loading into an unattended run. If you do call it: the confirmation is already satisfied — the seam under test is the interface the step-4 adjudicator picked, recorded in the report. Treat it as the pre-agreed seam and do not re-confirm. |
| `domain-modeling` | **not called** | Edit `CONTEXT.md` directly at step 6 | Its ADR-recording step would be pre-empted anyway: this run never writes an ADR. |

## Arguments

Parse flags from the invocation. **With no arguments, the run does everything**: scan, pick, implement, and open a PR.

- `<path|module>` — scope the scan to this path or module. Skips the hot-spot inference in step 1.
- `--report-only` — stop after **step 3**. Produces the committed report and the reconciled backlog; no design pass, no implementation, no PR.
- `--no-pr` — implement and commit on a branch, but don't push or open a PR.

## Workflow

### 0. Preflight

Establish that the run can finish before it changes anything. Check in order; on any failure write the exit report ([autonomy-contract.md](references/autonomy-contract.md)) and stop.

**Checks 1 and 2 run before the run has settled its branch, so their bail-outs write nothing.** Print the exit report to stdout, record `**Committed**: nothing`, and commit nothing — the contract's "commit before you stop" rule applies only once check 3 has adopted or created a branch to commit to. Committing here would land `.architecture/` changes on whatever branch the caller happened to have checked out, possibly the default branch, which the side-effect table forbids; and in the dirty-tree case it would commit into the very tree the check exists to protect. Do **not** close this by settling the branch earlier: neither adoption nor a clean cut from `origin/<default-branch>` is safe over a dirty tree without carrying or clobbering the caller's work.

1. **Fetch first.** `git fetch origin` — a cron container's local branches are routinely days stale, and both the base branch and the PR reconciliation below are read against origin.
2. **Working tree is clean**, ignoring paths under `.architecture/`. Never stash: the stash stack is shared across worktrees and sessions. Uncommitted `.architecture/` files are the residue of an interrupted run, not a reason to bail — step 2 reconciles them.
3. **Settle the run's branch** now, before anything is written, so every artefact has somewhere to be committed. Never work on the default branch.

   **Adopt the branch you were started on** when it is not the default branch *and* has zero commits ahead of `origin/<default-branch>` (`git rev-list --count origin/<default-branch>..HEAD` is 0). An empty branch cut from the base is a branch a caller made for this run — a headless harness that prepares a workspace, or a human who branched before invoking — and taking it over is what lets that caller find the resulting PR. If the adopted branch is *behind* the base, fast-forward it with `git merge --ff-only origin/<default-branch>`; there are no commits of the run's own to lose, and `--ff-only` fails loudly instead of rewriting anything. If that fails, the branch has diverged from base: fall back to creating a branch, below.

   **Otherwise create one**: name it `pm-deepen/run-<YYYY-MM-DD>-<HHMM>` and cut it from **`origin/<default-branch>`**, not from the local default branch — a fetch updates remote-tracking refs, so branching off local `main` in a stale container still bases the PR on old code.

   Record which path was taken and the branch name in the report and the exit report. The distinction matters twice later: step 2 does not rename an adopted branch, and an adopted branch is the caller's to delete, never this run's.
4. **The quality gate is discoverable**: read `CLAUDE.md`/`AGENTS.md` and the manifests, and record the exact commands. A repo with no test runner cannot be deepened test-first — bail.
5. **`gh` is available and authenticated**: `gh auth status`. If it is missing or unauthenticated, **degrade to `--report-only`** rather than bailing — a report with no PR is still evidence, and this is the most common cron-container failure. Record it under *Degradations* in the report, and follow the degraded reconciliation rule at step 2.

### 1. Explore

**Scope before you scan: YAGNI.** Deepening pays off by making *future* changes easier, so weight the parts of the codebase that have recently changed. Decide *where* to look before looking:

- If a path or module was given as an argument, take it and skip the inference.
- Otherwise walk back a good stretch of `git log --oneline` to find the codebase's hot spots — the files and areas that keep coming up — and let those paths pull your attention first. If the changes are scattered with no clear hot spot, widen the net.

Read `CONTEXT.md` and any ADRs covering the area first, so candidates are named in the project's own vocabulary and don't re-litigate settled decisions.

Then spawn a sub-agent to walk the codebase. Don't follow rigid heuristics; explore organically and note where you experience friction:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules **shallow**, with an interface nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, while the real bugs hide in how they're called (no **locality**)?
- Where do tightly-coupled modules leak across their seams?
- Which parts are untested, or hard to test through their current interface?

Apply the **deletion test** to anything you suspect is shallow: would deleting it concentrate complexity, or just move it? "Concentrates" is the signal you want.

If no sub-agent tool is available in the current harness, do this pass inline. It is slower, not different.

### 2. Reconcile, score, and pick

Read `.architecture/backlog.md` if it exists and reconcile it against merged and open PRs via `gh` ([ranking.md](references/ranking.md)) — this is also where residue from an interrupted run gets folded in.

**Degraded (no `gh`)**: skip the PR reconciliation entirely and leave every `in-flight` entry exactly as it is. Do not guess at PR state, and do not silently drop the step — an unreconciled backlog means `in-flight` entries keep hard-filtering their candidates, so a degraded routine surfaces steadily less over time. Say so under *Degradations* so a reader knows the ranking was made against possibly-stale state.

**Name the branch after the slug — but only if the branch is this run's to name.** A run that *created* its branch at step 0 and will implement something renames it to `pm-deepen/<slug>` (`git branch -m`); nothing has been pushed yet, so this is free. A `--report-only` or no-candidates run keeps its run-stamped name.

**Never rename an adopted branch.** Its name is the caller's identity for this run — a headless harness derives the branch deterministically and then looks for the resulting PR by that head, so renaming it hides the PR from the very system that asked for the work. Keep the adopted name for the whole run and record the slug in the report and the backlog instead.

Either way, check the slug for collisions: if `pm-deepen/<slug>` already exists locally or on origin, that candidate is already in flight — bail. On an adopted branch this check finds nothing, because no slug-named branch is ever created; there the backlog's `in-flight`-entry-with-an-open-PR check below is the dedup that matters, which is why it is the primary guard and this one the backstop.

Then score every candidate on leverage, locality, blast radius, and heat; apply the hard filters; rank; **take the top one**. The rubric, the filters, and the deterministic tie-break are in [ranking.md](references/ranking.md).

Do not ask which to explore. Do not stop at a shortlist. The pick and its reasoning go into the report, where a reviewer can disagree with it in the PR.

Merge every candidate — picked, dropped, and too-large — into `.architecture/backlog.md` with the status the rubric assigns it, reusing existing slugs so the dedup filter keeps working across runs.

If an `in-flight` entry still has an open PR, **and this run would implement something**, stop: one architecture PR at a time. A `--report-only` run continues — it opens nothing.

### 3. Write the report

Write the report per [report-format.md](references/report-format.md): one card per candidate with files, scores, problem, deletion test, solution, benefits, before/after Mermaid diagrams and recommendation strength, then the dropped list, the too-large list, and the pick.

Never write to a temp directory. Never call `xdg-open`, `open`, or `start` — an unattended run has no display, and a discarded temp file leaves no evidence the run happened.

**Commit the report and the backlog to the run's branch now**, before going further. Artefacts that are written but never committed are lost on the next firing and leave the tree dirty.

If `--report-only`: push the branch unless `--no-pr`, and stop here. This is a complete run — see the per-flag definitions of done in [autonomy-contract.md](references/autonomy-contract.md).

### 4. Design the interface

Now propose interfaces — not before; a candidate is chosen on friction, not on a design you already had in mind.

Call the Skill tool with `codebase-design` and use its **design-it-twice** pattern: spawn 3+ sub-agents in parallel, each briefed to produce a *radically different* interface for the deepened module (minimal surface; maximum flexibility; optimised for the most common caller; ports-and-adapters where dependencies cross a seam). Give each the file paths, coupling details, dependency category, what sits behind the seam, and both vocabularies.

Then **adjudicate instead of grilling.** Upstream hands the winning design to the `grilling` skill, which asks the user a round of questions and waits for answers — no human, no progress. Here, a separate sub-agent that did not author any of the designs picks the winner against fixed criteria, in this order:

1. **Depth** — leverage at the interface: how much behaviour per unit of interface a caller must learn.
2. **Locality** — where change, bugs, and verification concentrate afterwards.
3. **Seam placement** — is the seam where something actually varies? One adapter is a hypothetical seam; two is a real one.
4. **Test surface** — can the behaviour be exercised through the interface, without reaching past it?
5. **Blast radius** — of the two otherwise-equal designs, the smaller diff wins.

Grilling already requires a recommended answer per question, so an adjudicator can settle the same tree from the same evidence. Append the winner, the losing designs, and the reasoning to the report's `## Design` section, and carry the winner and the strongest loser into the PR body.

**Without a sub-agent tool**, produce the designs inline one at a time, writing each into the report's `## Design` section *before* starting the next, then adjudicate against the written designs rather than against memory. The adjudicator's value is that it did not author them; writing them down first is the closest inline equivalent. Note in the report that the designs were produced inline.

If the criteria above cannot separate the designs, that is a bail-out, not a coin flip.

### 5. Implement, test-first

Implement the winning design on the run's branch.

Test-first is not optional: write a test that pins the intended interface, watch it fail, then make it pass. Pin existing behaviour with a test *before* moving it. The seam under test is the adjudicated interface — it is already agreed, so do not stop to confirm it.

Run the project's quality gate, each step as a **separate command**, never `&&`-chained. Fix failures; after 3 attempts still red, bail out with the failing command and its verbatim output. Never weaken, skip, or delete a test to reach green.

Watch the diff against the file-count estimate the candidate was scored on. A change that outgrows its estimate was mis-scored — stop and report rather than pressing on. Do not revert the work: commit it as a `bail:` commit and leave the branch unpushed, per [autonomy-contract.md](references/autonomy-contract.md).

### 6. Land it

Update `CONTEXT.md` if the deepened module is named after a concept the glossary lacks, or if a term the code contradicts needs sharpening. **Do not write an ADR** — propose it under `## Proposed ADR` in the PR body instead.

Commit with a conventional-commit message. Unless `--no-pr`: push the branch and open a PR with `gh pr create`, whose body carries the problem, the before/after in `codebase-design` vocabulary, a link to the report, the winning candidate's score and the runner-up **candidate**, the runner-up **design** and why it lost, any proposed ADR, and any `CONTEXT.md` terms added. Set the backlog entry to `in-flight` with the PR number, commit that update, and **push again** so that commit lands in the PR. Without the second push, the PR — and the default branch after it merges — keeps a `proposed` entry with no PR number, and the next firing reads the backlog from `origin/<default-branch>`: the `in-flight` reconciliation lookup never fires and already-landed work resurfaces. Under `--no-pr` there is no PR number: leave the entry `proposed` and add a note naming the branch, so the next firing can find the work.

The PR is the deliverable. Do not merge it, and do not approve it — see the full side-effect table in [autonomy-contract.md](references/autonomy-contract.md).
