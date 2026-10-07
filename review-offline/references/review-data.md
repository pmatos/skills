# Review data contracts

Maintainer reference: running the skill does not require reading this file.
Every file the launcher, server, page and passes exchange. Scripts validate
against these shapes; change them here first.

## Run layout

```text
<repo>/.reviews/                  # user's repo; created with a `.gitignore` containing `*`
├── <slug>.state.json             # autosaved review state (resumable)
└── <slug>.md                     # written on Finish review

<run-dir>/                        # scratch at $TMPDIR/review-offline/<slug>/ (stable per slug: sessions are keyed by cwd)
├── changeset.json                # resolver output (below)
├── graph.json                    # authored by the invoking agent (graph-schema.md)
├── prefetch/                     # diff.patch, pr.md, pr-comments.md: all headless agents read
└── worktree/                     # detached checkout, only when the target is not the current tree
```

`slug` is `pr-<n>`, the branch name with `/` → `-`, or `head-<short-sha>`.
`.reviews/` always lives in the user's repo, never in the run dir.

## Changeset (`changeset.json`)

```json
{
  "target": "pr:123",
  "title": "…",
  "slug": "pr-123",
  "base": { "sha": "…", "ref": "main" },
  "head": { "sha": "…", "ref": "feat/x" },
  "root": "/path/to/tree/the/agents/read",
  "files": [
    {
      "path": "src/a.py", "old_path": null, "status": "modified",
      "binary": false, "additions": 3, "deletions": 1,
      "collapsed": false, "collapse_reason": null,
      "hunks": [
        { "header": "@@ -1,4 +1,6 @@ def f", "old_start": 1, "new_start": 1,
          "lines": [ { "t": "ctx|add|del", "o": 1, "n": 1, "text": "…" } ] }
      ]
    }
  ]
}
```

`status` is `added|modified|deleted|renamed`. `o`/`n` are the old/new line
numbers (`null` on the side a line does not exist). Lockfiles, generated and
vendored files get `collapsed: true` with a `collapse_reason`.

## Anchor

```json
{ "scope": "line", "path": "src/a.py", "side": "new", "start": 10, "end": 12, "hash": "ab12cd34ef56" }
```

- `scope`: `line` (range), `file` (only `path`), or `pr` (nothing else).
- `side`: `old` or `new`. Removed lines exist only on `old`. Maps to GitHub
  `LEFT`/`RIGHT` for whoever posts later.
- `hash`: first 12 hex of SHA-1 over the anchored lines' text joined by `\n`.
  Stale detection compares this against the current diff, not just the head SHA.

## Comment

```json
{
  "id": "c1", "anchor": { }, "label": "blocking|suggestion|nit|question",
  "body": "text, rendered as plain text", "suggestion": "replacement text or null",
  "origin": "user|agent", "sources": ["correctness"], "verdict": "CONFIRMED|PLAUSIBLE|null",
  "status": "pending|accepted|rejected", "stale": false
}
```

User comments are created `accepted`. Agent comments arrive `pending`.
Rejected comments stay in the state file but never reach the markdown.

## Ask thread

```json
{ "id": "t1", "anchor": { }, "messages": [ { "role": "user|agent", "text": "…" } ], "session": "<id>" }
```

One agent session per thread; asks within a thread are serialized; review passes
get their own sessions. `session` is a hint: if resume fails (new run-dir, deleted
worktree), the runner replays `messages` into a fresh session. A reply can be
promoted to a comment by the user.

## Finding (what a headless pass returns)

The pass's **final message** is a single fenced `json` block holding an array:

```json
[ { "path": "src/a.py", "side": "new", "start": 10, "end": 12,
    "label": "blocking|suggestion|nit|question", "body": "one-sentence defect + concrete failure",
    "suggestion": null, "category": "correctness", "verdict": "CONFIRMED|PLAUSIBLE" } ]
```

The runner validates it strictly, retries once feeding back the exact error,
and downgrades a finding whose lines are not in the diff to `file` scope. A
read-only child cannot spawn subagents, so effort fan-out belongs to the runner:
one call per angle, then verify calls; `passes` is only the aggregate status.
Overlapping findings in the same file merge into one comment with several
`sources` and the stronger label.

## State (`.reviews/<slug>.state.json`)

```json
{ "version": 1, "revision": 7, "target": "pr:123", "base_sha": "…", "head_sha": "…",
  "content_sha": "hash of the diff files", "summary": "", "head_moved": false,
  "previous_head_sha": null, "counters": { "c": 0, "t": 0 },
  "comments": [], "threads": [], "passes": { "correctness": "running|done|failed", "cleanup": "…" },
  "events": 12, "updated_at": "ISO-8601" }
```

**The server is the only writer.** The page sends operations, never the whole
array, so a suggestion landing mid-edit cannot clobber or be clobbered. The server
assigns ids and `revision`, which only increments. On resume, a moved head or changed diff
content sets `head_moved` (the page warns and the agent passes rerun), and any
comment whose anchor `hash` no longer matches is marked `stale`.

## Markdown output (`.reviews/<slug>.md`)

````markdown
# Review: <title>

- Target: <target>
- Base: <sha> → Head: <sha>
- Reviewed: <date>

## Summary

<free text the reviewer wrote, or the agent summary if kept>

## Comments

### src/a.py

- **L10-12 (new) · blocking** — <body>

  ```suggestion
  <replacement>
  ```

### General

- **question** — <PR-scoped comment>
````

Only `accepted` comments appear. Files in path order, comments in line order,
`General` last. Line ranges name their side so `old` anchors survive posting. The writer fences
a suggestion with more backticks than the longest backtick run inside it.

## Local API

Every route checks `Host == 127.0.0.1:<port>`, and any `Origin` present must match it.
Every `/api/*` route also needs `X-Review-Token`; `GET /` alone is exempt, since a
navigation cannot send headers. The token lives in the URL fragment and the page
sends it as a header. The server never logs request lines.

| Route | Purpose |
| --- | --- |
| `GET /` | static shell: inlined CSS/JS only, no review data |
| `GET /api/bootstrap` | changeset, graph, state, pending thread ids, host, effort, notes |
| `GET /api/snapshot` | state plus pending thread ids; the page refetches it on every event |
| `POST /api/comments` | create a user comment; server assigns `id` |
| `PATCH /api/comments/<id>` | edit body/label/suggestion, accept or reject |
| `DELETE /api/comments/<id>` | remove a user comment |
| `PUT /api/summary` | the reviewer's free-text summary |
| `GET /api/events?since=N` | long-poll for suggestions and pass/ask status |
| `POST /api/ask` | `{thread_id?, anchor, text}`; reply arrives as an event |
| `POST /api/finish` | write the markdown, respond with its path, shut down |

Review data is never inlined into the HTML, so nothing in a diff can break out
of a script tag.

## Launcher final line

The background `serve` command ends with exactly one of these, so the invoking
agent never reports completion after a timeout:

```text
REVIEW-COMPLETE <path-to-markdown>
REVIEW-SUSPENDED stopped <path-to-state>
REVIEW-ERROR <message>
```
