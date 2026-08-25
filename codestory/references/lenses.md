# Lenses

A **lens** is a way of looking at the target. Lens agents do not write the story
— they decide **what matters and where to look**. Their output is a set of
*leads*: pointers the narrator follows and reads for itself.

This roster is a starting set, not a closed one. Add a lens by adding a section
here; the workflow reads this file rather than hard-coding the list.

## The lead record

Every lens emits leads in the same shape, one per line, appended to its file
under `.stories/.<slug>/leads/<lens>.md`:

```
path:line — <one line: what is here> — <why it is salient> — [beat-hint]
```

Rules for lead records:

- **Never prose.** A lead is a pointer plus a reason. If a lens finds itself
  writing three sentences, it is doing the narrator's job.
- **Never a claim the narrator will repeat verbatim.** Leads are leads. The
  narrator re-reads the source before saying anything about it.
- `beat-hint` is optional and advisory — a suggestion about where in the flow
  this belongs, which the outline step may ignore.

## Triage

Before dispatch, check which lenses apply to this target. A lens that would
produce nothing is not dispatched and contributes no leads.

A lens is a way of *researching* the story, never a section in it. There is no
"IO" heading in the output — what the IO lens found surfaces in the beat where
the code touches the disk. See `narration.md`.

- **Interfaces is always on.** It supplies the story's cast of characters.
- Skip **IO & side effects** when nothing in the target touches the filesystem,
  network, process state, environment or a database.
- Skip **External dependencies** when the target imports nothing outside the
  repository.
- Skip **Tests as specification** when no test covers the target — and say so in
  the story, because "this change has no test" is a fact a reviewer wants.
- Skip **Situating context** for `path` and `project` targets unless the user
  asks; it earns its cost on change-shaped targets.

## 1. Interfaces and contracts — *always on*

The shapes other code sees. Public functions, types, classes, exported
constants, route handlers, CLI arguments, config schemas, protocol messages.
For each: its signature, what it promises, what it requires of callers, and any
invariant stated or enforced.

Salient: an interface that changed shape; an argument whose meaning is not
obvious from its name; a type that permits a state the code assumes impossible;
a contract documented in one place and enforced in another.

## 2. Control and data flow

The spine the narrative follows. Entry points, the path a value takes through
the system, branch points, loops, recursion, state machines, ordering
constraints, and anything concurrent.

Salient: a branch that is easy to miss; an early return that skips work below
it; a loop whose exit condition is non-obvious; ordering that matters and is not
enforced; a value that is transformed in more places than a reader would expect.

## 3. External dependencies

Anything not in this repository: libraries, services, APIs, subprocesses,
system tools. For each, where it enters and what the code relies on it for.

Salient: a newly added dependency; a dependency used in one place only; a call
whose failure mode the caller does not appear to expect; a version constraint
that matters. This lens also produces the appendix checklist of every external
thing the target touches.

## 4. IO and side effects

Every point where the code reaches outside itself: filesystem reads and writes,
network calls, database access, environment variables, process spawning, global
or module-level mutable state, logging that carries data.

Salient: a write whose path is computed rather than literal; an effect inside a
code path that reads as pure; anything that happens before a validation step.
Also produces an appendix checklist of paths written, endpoints called and
environment variables read.

## 5. Error handling and failure modes

What happens when things go wrong: raised and caught exceptions, error returns,
retries, timeouts, fallbacks, cleanup, and the paths that have none.

Salient: an error swallowed without being surfaced; a fallback that changes
behaviour rather than reporting failure; a resource acquired on a path that can
exit without releasing it; a retry with no bound; an error type callers must
distinguish but cannot.

## 6. Situating context

Where this code sits in the repository's history and its stated direction.

Facts, from `git log`, `git blame` and `gh` when available: when these lines
were last changed and by which commit or PR; what that change did; whether this
area is churning; issues or PRs that reference these files.

**This lens is allowed to infer, and every inference must wear its marker.**
"`⟨inference⟩` this looks like groundwork for #52" is permitted. "This is
clearly heading towards a plugin architecture" without the marker is a bug in
the output.

**Degrade, do not fail.** `git log` is free and offline. `gh` may be absent,
unauthenticated or rate-limited — when it is, the lens reports history only and
the story says that issue context was unavailable.

## 7. Tests as specification

What the test suite claims this code does. Test names, the cases asserted, the
fixtures and their shape, and — most usefully — the edge cases someone thought
worth pinning down.

This is often the fastest route to *intended* behaviour, and it is the fallback
when a target has no PR description to narrate against.

Salient: an assertion that contradicts what the implementation appears to do; a
behaviour tested nowhere; a test that asserts only that nothing threw; fixtures
that reveal an expected data shape the types do not express. This lens also
supplies the real usage examples the story prefers over invented ones.
