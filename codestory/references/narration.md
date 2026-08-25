# Narration

## The reader

A competent engineer who does not know *this* codebase, reading in order to
review it. They can read the language. They cannot see what is three files away,
and they do not yet know which of the seven things happening on this line is the
one that matters.

## Voice

Plain, concrete, present tense, following the data.

> The handler receives the raw webhook body, verifies the signature against the
> shared secret, and only then parses it as JSON. A failed signature check
> returns 401 before any parsing happens, so malformed bodies from unsigned
> callers never reach the parser.

What makes this a *story* is sequence and causation — this happens, therefore
that becomes possible — not literary decoration. The prompt "turn code into a
story" reliably produces the decorated version. Resist it.

**Not this:**

> Our intrepid little handler stands guard at the gate. A request arrives,
> travel-stained and bearing papers. The handler squints at the seal…

**Also not this** — five parallel reports wearing a story's clothes:

> **Interfaces:** `handle_webhook(request) -> Response`.
> **Dependencies:** uses `hmac` and `json`.
> **IO:** reads `WEBHOOK_SECRET` from the environment.
> **Error handling:** returns 401 on signature failure.

The lenses are how the story was *researched*. They are not its structure.

## Concrete rules

- **Present tense, active voice.** "The parser rejects trailing commas", not
  "trailing commas will be rejected by the parser".
- **Name real things.** Use the actual function, file and variable names, so the
  reader can find them. Never invent a friendlier name for something.
- **One idea per sentence.** The reader is holding unfamiliar code in their head
  already.
- **Explain the why only when the code shows it.** If a comment, a test name, a
  commit message or the structure itself makes the reason visible, say it. If
  not, it is `⟨inference⟩` or it is silence.
- **No summary paragraph that repeats the beat.** End on the last fact.

## What a beat is

**One narrative idea**, not one code unit. A four-line getter is not a beat; a
three-hundred-line function is three or four. A beat may span two files if the
idea does.

Budget: roughly one screen of prose plus one code excerpt. If a beat needs three
excerpts it is two beats.

Every beat has:

1. A short title naming the idea, not the location — "Signature check happens
   before parsing", not "`handle_webhook` lines 40-72".
2. The prose.
3. One excerpt, with its `path:line` anchor.
4. Zero or more markers, inline where they apply.

## Code excerpts

**Verbatim is the default**, and every excerpt carries `path:line` so the reader
can check it in one keystroke. The anchor is not optional — it is what makes
every sentence in the story falsifiable.

Simplification is permitted when it genuinely helps — eliding error paths in a
long function, abridging a body to its shape — and it must be marked
`⟨simplified⟩` with the anchor pointing at the real thing.

Prefer expressing simplification **in prose over editing the code**. "The next
forty lines are six variations of the same validation, one per field" beats
showing a doctored excerpt.

## Usage examples

**Prefer a real one.** A call from a test, a real callsite elsewhere in the
repo, a fixture. Show it with its anchor. The tests-as-specification lens exists
partly to find these.

An invented example is a last resort and is marked `⟨illustrative⟩`. Invented
examples are the most dangerous output this skill can produce: they look like
evidence, they are plausible, and nothing in the repository contradicts them.

## Ordering

Follow the flow, not the file. For a state-shaped target, start where control
enters and follow it. For a change-shaped target, the flow is the change: what
the code did before, what it does now, and what that means for callers.

A change that is a pure addition has no "before" — narrate it in situ instead,
marking what is new.

## Opening and closing

The story opens with the **cast of characters** from the interfaces lens: the
handful of shapes the reader needs before any of the beats make sense. Short —
a paragraph, or a short list, not a beat.

It closes with the appendix: cross-cutting checklists (every external dependency
touched, every path written, every endpoint called) and every marker collected
in one place. The appendix carries only what did not fit a beat. It never
restates the narrative.
