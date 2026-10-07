# Graph document (`graph.json`)

The invoking agent authors one JSON document; `<skill-dir>/scripts/review_offline.py validate-graph`
rejects anything off-shape and names the exact field. The page renders it as an
animated, lane-based diagram with a before/after toggle and a flow stepper.
Unknown keys are rejections. Ids match `^[a-z0-9][a-z0-9._-]*$`, ≤ 64 chars, unique
per collection; write readable kebab-case (`broadcast-sender`, not `n1`).

```json
{
  "schemaVersion": "1",
  "title": "Batch broadcast sending",
  "summary": "One paragraph: what does this change do?",
  "lanes": [], "nodes": [], "edges": [], "flows": [], "panels": []
}
```

Caps: 8 lanes, 30 nodes, 64 edges, 6 flows (each with at least one step), 12 steps
per flow, 4 panels. Past 30 nodes, group by package or folder instead of drawing every
file. Length limits: labels, titles, subtitles and group names 80 characters; summaries
and captions 600; panel text 4000; at most 6 badges of 40 characters each. At most two
`hero` edges.

A worked example is `example-graph.json` next to this file.

## Deltas

Every node, edge, flow and step declares `delta`: `added|modified|removed|unchanged`.
`unchanged` is not padding: it is the neighbouring code the change touches, which
turns the diagram into a blast radius. A document where everything is `added`
describes a change nobody can place. The validator enforces it: a document whose
deltas are all `added` and which has no `unchanged` node is rejected, so a greenfield
change still needs an unchanged neighbour such as the caller or an external service.

## Lanes

```json
{ "id": "functions", "label": "Cloud Functions", "subtitle": "Node 20", "order": 1 }
```

`order` (0-64) places lanes left to right. Every node belongs to exactly one lane.

## Nodes

```json
{ "id": "send-bulk", "label": "sendBulk", "kind": "function", "delta": "added",
  "lane": "functions", "group": "broadcast-lib", "subtitle": "(id) => Promise<void>",
  "summary": "Claims the broadcast, builds one payload and posts it.",
  "files": [ { "path": "functions/src/send.ts", "start": 1, "end": 142 } ],
  "badges": ["retry"] }
```

`kind`: `service app module function route job queue datastore cache external ui config test package other`
(drives icon and shape only). `files` may name any path under the changeset `root`, so `unchanged` neighbours
work; the page links into the diff only when the path is in it. A node with no
files is an external service. When `validate-graph` is given `--changeset`, a path
that only exists in the diff (a deleted file) is accepted too, so `removed` nodes can
cite what they removed. The delta badge is drawn for
you; do not restate it in `badges`.

## Edges

```json
{ "id": "bulk-to-postmark", "from": "send-bulk", "to": "postmark", "kind": "http",
  "delta": "added", "label": "POST /email/bulk", "emphasis": "hero" }
```

`kind`: `call http rpc event queue data dependency render other`.
`emphasis`: `normal` (default), `hero`, `muted`; one or two heroes at most.
`from`/`to` must be declared node ids: the most common failure.

## Flows (the animated part)

```json
{ "id": "happy-path", "title": "A broadcast is sent", "summary": "…", "delta": "added",
  "steps": [ { "id": "s1", "edge": "ui-to-sender", "caption": "The UI enqueues the broadcast.", "delta": "added" },
             { "id": "s2", "node": "send-bulk", "caption": "The sender claims it before any network call.", "delta": "added" } ] }
```

A step names exactly one of `edge` or `node`. Captions are plain prose, one or two
sentences, written for a reviewer who has not read the diff: what happens, and
why it matters, never a verdict.

## Panels (optional, from `show-me`)

For what a graph draws badly. `kind`: `calltree`, `pseudocode`, `filetree`.
`text` is monospace; with `"diff": true`, lines starting `+`/`-`/space are
coloured as a diff.

```json
{ "id": "control-flow", "title": "submit path", "kind": "calltree", "diff": true,
  "text": " submitForm\n   createSession\n+    expandSkillMention\n     launchAgent" }
```

Pick the smallest view that makes the point. Most changes need a graph and zero
or one panel.
