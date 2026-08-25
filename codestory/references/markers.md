# Markers and the never-evaluate rule

## Why a fixed vocabulary

codestory exists to help a reviewer judge. If it judges for them it becomes a
worse duplicate of a code-review tool, and — more importantly — a reviewer who
trusts a fluent narration stops reading the code.

Two disciplines keep that from happening: a closed set of markers, and a hard
prohibition on evaluative language. The markers are closed so that they can be
checked. An unmarked inference is not a stylistic slip; it is a defect in the
output.

## The vocabulary

Exactly five markers. Do not invent others; do not paraphrase these.

| Marker | Means | Use when |
| --- | --- | --- |
| `⟨not in description⟩` | The code does this, and the stated intent never mentions it | Narrating a change against a PR description, commit message or linked issue |
| `⟨easy to miss⟩` | A fact about the code a careful reader could still overlook | A branch, an early return, an implicit ordering, a side effect in a place that reads as pure |
| `⟨inference⟩` | Not read from the code — reasoned from it | Anything about intent, direction, or why something was done |
| `⟨simplified⟩` | The excerpt shown is not exactly what is in the file | Error paths elided, a long body abridged, names shortened for readability |
| `⟨illustrative⟩` | This example was invented, not taken from the codebase | No real callsite or test exists to show usage |

Markers appear **inline, at the point they apply**, and every marked item is
**collected again in the closing appendix**. Inline is where the reader is
looking; the appendix is what they scan before approving.

## The never-evaluate rule

State what the code does. Never state whether it is good.

The line is not "avoid negative words" — it is **fact versus verdict**. Pointing
out something a reader might miss is comprehension. Telling them what to
conclude about it is not.

Allowed — these are facts about the code:

- "`⟨easy to miss⟩` This early return happens before the `finally` block is
  installed, so the lock acquired on line 88 is not released on this path."
- "The retry loop has no upper bound; it exits only when the call succeeds."
- "This error is caught and logged at debug level; the caller receives `None`
  and cannot distinguish it from an empty result."
- "`⟨not in description⟩` The PR description covers the new endpoint. This also
  changes the default timeout for every existing caller, from 30s to 5s."

Not allowed — these are verdicts:

- "This is a bug." / "This is wrong." / "This will break."
- "This should be refactored." / "Consider extracting this."
- "Good separation of concerns here." / "This is clean."
- "This is dangerous / risky / poorly named / over-engineered."
- "You'll want to fix this before merging."

Note that the allowed and forbidden versions often describe the same line of
code. The difference is that the reviewer draws the conclusion.

Two phrasings that look like facts and are not:

- **Smuggled verdicts.** "Interestingly, the error is swallowed here" —
  *interestingly*, *unfortunately*, *note that surprisingly* are judgment
  wearing a fact's clothes. Say what happens; the `⟨easy to miss⟩` marker is
  the only emphasis available.
- **Rhetorical questions.** "Is this intentional?" is a verdict with a question
  mark. If the stated intent does not cover it, that is `⟨not in description⟩`,
  which says the same thing without the nudge.

## Where this rule does not apply

The user may ask a direct question at a checkpoint — "is that a bug?" Answer it.
The prohibition is on the *story* volunteering verdicts, not on refusing to
engage when asked.
