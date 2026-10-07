# Authoring the opening visualization

The page opens on a picture of what the change does, so a reviewer reads the
diff already knowing where they are. You write `graph.json` (schema in
`graph-schema.md`); the page draws it. Spend your effort on **choosing what to
show**, not on formatting.

## Read before drawing

Read `prefetch/diff.patch` and the files it touches, plus enough of the
neighbouring code to know who calls the changed code and what it calls. Never
describe code you have not read. If the PR description exists (`prefetch/pr.md`),
read it for intent, but trust the code over the prose.

## What belongs on the graph

- **Nodes are things a reviewer can name**: a service, module, route, job, queue,
  table, external API, UI surface. Not every file. A 40-file change is usually 6 to
  12 nodes; past 30 group by package.
- **Include `unchanged` neighbours.** The caller that now passes a new argument,
  the table the new query reads: that is the blast radius, and it is what turns the
  picture from a file list into an explanation.
- **Lanes are the tiers the reader already thinks in** (UI, API, workers, storage,
  external). Two to five lanes is typical; order them left to right in the direction
  data flows.
- **Edges are runtime relationships**: calls, requests, events, reads and writes.
  Mark at most two as `hero`: the path the change exists to create or alter.
- **Deltas must be true.** `added`/`modified`/`removed` follow the diff exactly; an
  edge is `added` only when the new code creates that relationship.

## Flows: the animated part

A flow is a short story along edges and nodes. Write one to three:

1. The happy path of the main behavior the change adds or alters.
2. The failure or edge path, when it is the point of the change (retries, rollback,
   permission denied).

Each step names an edge or a node and carries a caption of one or two sentences.

Write captions as explanation, not labels: lead with what happens, then why it
matters, in plain prose. "The sender claims the broadcast row before posting, so a
retry cannot send it twice." Never a verdict ("this is risky") and never a bare
restatement of the label ("calls Postmark"). A reviewer who has not read the diff
should understand the change from the captions alone.

## Panels: the smallest extra view

Add a panel only when the graph draws the point badly:

- `calltree` with `"diff": true` for a control-flow change inside one subsystem.
- `pseudocode` with `"diff": true` for a changed algorithm or state machine.
- `filetree` for a restructuring where the shape of the directories is the story.

Keep them to about a dozen lines, and show only the calls, files and branches that
answer "what changed". Most changes need no panel.

## Summary

`summary` is one paragraph answering "what does this change do?", written for
someone deciding where to spend their review attention. Name the main behavior, the
riskiest seam, and anything that looks unrelated to the stated intent.

## Check before you finish

- `python3 <skill-dir>/scripts/review_offline.py validate-graph <run-dir>/graph.json
  --root <root> --changeset <run-dir>/changeset.json` prints `ok`. Fix every named field; the errors are exact.
- Every node's `files` point at real paths under the root. Line ranges are optional.
- Nothing in the document is a guess about code you did not read.
