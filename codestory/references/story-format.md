# Story file format

The story accumulates at `.stories/<slug>.md` **as it is told**, beat by beat —
not written in one pass at the end. If the session dies at beat 19, beats 1–18
are on disk.

## Slug

`<kind>-<ref>`, lowercased, non-alphanumerics collapsed to `-`:

- `pr-142`
- `branch-feat-webhook-retry`
- `working-tree`
- `path-src-auth`
- `project`

A story for the same slug already on disk triggers the resume flow.

## Layout

````markdown
---
target: pr-142
kind: pr
ref: "142"
shape: change
base_sha: 3f9a1c4e8b2d5a7f0c1e6b9d4a2f8c3e5b7d9a1f
head_sha: 8c2e5b7d9a1f3f9a1c4e8b2d5a7f0c1e6b9d4a2f
content_fingerprint: ""
default_branch: main
tier: small
lenses: [interfaces, flow, dependencies, io, errors, context, tests]
intent_source: pr-description
created: 2026-08-25T14:02:11Z
outline:
  - { n: 1, title: "Signature check moves ahead of parsing", status: done }
  - { n: 2, title: "The retry loop and its bound", status: done }
  - { n: 3, title: "What callers see when every retry fails", status: pending }
---

# codestory — PR #142: Verify webhook signatures before parsing

**Target** PR #142 · `feat/webhook-retry` → `main` · base `3f9a1c4` head `8c2e5b7`
**Told against** the PR description
**Skipped** 2 files — `uv.lock` (lockfile), `src/api.pb.go` (generated)
**Removed** `src/webhook/legacy_client.py`
**Formatting only** `src/webhook/client.js`

## Cast

`handle_webhook(request) -> Response` is the only entry point. It leans on
`verify_signature(body, secret)` and `WebhookClient.deliver()`, both in
`src/webhook/client.py`.

## Contents

1. [Signature check moves ahead of parsing](#1-signature-check-moves-ahead-of-parsing)
2. [The retry loop and its bound](#2-the-retry-loop-and-its-bound)
3. [What callers see when every retry fails](#3-what-callers-see-when-every-retry-fails)

## 1. Signature check moves ahead of parsing

Before this change the handler parsed the body and then verified it. Now the
verification happens first, so an unsigned caller's malformed JSON never reaches
the parser.

```python
# src/webhook/handler.py:41
def handle_webhook(request: Request) -> Response:
    if not verify_signature(request.body, SECRET):
        return Response(401)
    payload = json.loads(request.body)
```

`⟨not in description⟩` The same commit changes `SECRET` from a module constant
to an environment read at call time, so rotating the secret no longer needs a
restart.

## 2. The retry loop and its bound

…

### Expansion — asked at beat 2

> Where does `max_attempts` come from?

It is a constructor argument on `WebhookClient` defaulting to 3
(`src/webhook/client.py:22`), and no caller in the repository overrides it.

## Appendix

### External dependencies touched

- `hmac` (stdlib) — `src/webhook/handler.py:12`
- `httpx` — `src/webhook/client.py:8`, the only use in this change

### IO and side effects

- reads env `WEBHOOK_SECRET` — `src/webhook/handler.py:39`
- POSTs to the configured delivery URL — `src/webhook/client.py:57`

### Markers in this story

- `⟨not in description⟩` beat 1 — secret becomes an environment read
- `⟨easy to miss⟩` beat 2 — the retry loop sleeps before the first attempt
- `⟨inference⟩` beat 3 — the new error type looks aimed at #131
````

## Rules

- **Frontmatter is written before beat 1** and its `outline` entries flip to
  `done` as each beat completes. That is what resume reads.
- **The skipped-files line is mandatory** and appears near the top, before the
  first beat. A reviewer must never believe they were walked through the whole
  change when they were not.
- **Deletions get a `Removed` line** beside it, and a beat of their own when
  something depended on the removed code. A deleted file has nothing to excerpt,
  which is exactly why it is easy to let it vanish from the story.
- **Files the resolver flags `formatting_only` get a line, not a beat** — but
  they are still narratable. Git cannot distinguish whitespace churn from a
  line re-indented into an enclosing block, so the flag is a hint; narrate one
  on request.
- **Expansions are written back.** When the user asks *go deeper* and gets an
  answer, it lands under its beat as an `### Expansion` block with the question
  quoted. This is often the most valuable prose in the session; do not let it
  live only in the terminal.
- **The appendix carries leftovers only.** Cross-cutting checklists and the
  collected markers. It never restates the narrative.
- `intent_source` records what the story was told against: `pr-description`,
  `commit-messages`, `issue-<n>`, `tests`, or `none`.

## Resume

When `.stories/<slug>.md` exists, compare it against the target resolved now.
**Which field decides is not a detail** — it depends on where the story's source
came from:

| Story's source | Compare | Why |
| --- | --- | --- |
| a commit — `pr`, `branch`, and any target with a non-empty `source_ref` | `head_sha` and `base_sha` | the SHAs name the content exactly |
| the working tree — `working-tree`, `path`, `project` | `content_fingerprint` | **no SHA moves when an uncommitted edit does**, so comparing SHAs here reports every edited target as unchanged |

Comparing SHAs for a working-tree story is the failure this section exists to
prevent: `head_sha` stays at the checkout commit through any number of
uncommitted edits, so the story silently appends new beats onto beats
describing content that has since changed. `content_fingerprint` covers the
resolved inventory and the current bytes of every file in it, and is
deliberately conservative — it may report a change that does not matter, and
the *resume anyway* choice below exists for exactly that.

**Unchanged** — offer to resume from the first outline entry that is not `done`.

**Changed** — say so explicitly, naming both SHAs (or, for a working-tree
story, saying the content has changed since the story was written), and offer
three choices:

- *resume anyway* — continue from where it stopped, with a note recorded in the
  file that beats before it describe an older revision
- *restart* — new story, previous file moved aside. Name the archive for
  what it described: `.stories/<slug>.<sha>.md` for a commit-sourced story,
  `.stories/<slug>.<fingerprint-prefix>.md` for a working-tree one, taking the
  **outgoing** story's own recorded value, not the target resolved now. Then
  **never clobber**: if that name exists, append `.2`, `.3`, and so on until
  one is free. A working-tree story's SHA does not move when its content does,
  so a second restart used to overwrite the first archive and silently destroy
  narration the user had asked to keep; content can also cycle A → B → A, so
  even the fingerprint repeats. The numeric suffix applies to SHA-named
  archives too — restarting twice at one commit collides the same way.
- *re-outline* — keep the file, rebuild the outline from the current state

Never resume silently onto moved code. A story confidently describing lines that
no longer exist is the worst output this skill can produce.

## Housekeeping

`.stories/` is not committed — a snapshot narration rots the moment the code
moves. At the end of a story, offer to add `.stories/` to `.gitignore` if it is
not already there; suggest the edit, never make it unasked.
