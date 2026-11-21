---
name: ask-rulings
description: >-
  This skill should be used when the user asks to "ask about the pending rulings", "ask the pending questions", "what needs my ruling", "ask me the open decisions", "ask the rulings again", or wants the open questions that block further progress, and that only they can answer, gathered, asked with background and a recommendation, and the answers recorded so the work can continue. Not for the needs-triage backlog (use pm-triage). Also triggered by the /ask-rulings command.
argument-hint: "[issue|PR|url ...]"
user-invocable: true
---

# ask-rulings — Ask the Questions That Block Progress

Work stalls on questions that only the human may answer. This skill gathers
them, asks them with enough background to decide, records each answer where the
question lives, and then lets the blocked work continue. It is a conversational
step: do not use the `Workflow` tool or subagents. Refer to the human as
they/them.

A question is pending until it has a ruling. A ruling counts only if it is in
the human's own words: an answer to `AskUserQuestion`, text the human typed, or
a record that quotes the human and is dated. Agent comments and agent-written
ADRs are never rulings, even when they are posted from the human's `gh` login.

## 1. Gather

Build the list from durable sources, never from memory alone:

- Questions raised in this session, by you or by agents, that have no ruling.
- Any record of open questions tied to this session's work or to the
  arguments, such as a comment or document that lists them, a "waiting on the
  human" label on one of those issues, or a PR body section waiting on
  acceptance.
- The issues, PRs or URLs passed as arguments.

Re-read each source item (the issue, the comment, the PR body, the agent's
notes) so that the background and the options are exact. If a record you
expected is missing or has an unfamiliar layout, say so rather than report that
nothing is pending.

## 2. Order and split

Ask first what blocks a merge or a ready PR, then what blocks a later step, then
the rest. When one change raises several separate points, ask each as its own
question.

## 3. Ask

Use `AskUserQuestion`, at most 4 questions per call, with as many calls in a row
as needed.

- Each question stands alone, because the dialog may be all that the human
  sees. Say what the issue or PR is, what it does, why a choice is needed, and
  give a concrete example where it helps.
- Use plain words. Explain or avoid jargon and bare identifiers.
- When a question asks to accept a change that weakens a stated guarantee, name
  each statement that it removes, narrows or weakens, or makes depend on a new
  assumption. Give the old and the new form in plain words, and say what is
  lost in practice, such as "a later change that adds X can no longer rely on
  this".
- Take the options from whoever raised the question, or draft them if there
  are none. Recommend one yourself, put it first with "(Recommended)" on the
  label, and give the reason in the question. If you disagree with the raiser's
  pick, say so. Each option's description gives its trade-off in one or two
  sentences.
- The tool needs 2 to 4 options: keep the most distinct ones, and with only one
  option add "Not yet: keep it pending". Never add "Other": the tool adds it.
- The header is at most 12 characters, such as `#123` or `#123 scope`.

If the call times out or gets no answer, every unanswered question stays
pending. Never choose an option because of a timeout or because the human is
away. After a timeout, ask nothing more: record the rulings you have and go to
step 6. A free-text reply that asks something or defers is not a ruling: answer
it and ask again, or keep the question pending.

## 4. Record

Record each ruling where its question lives, so that a later session finds it.
A question that lives only in this session needs no record beyond the report.
Write every comment body and edited comment to a file with a file-writing tool,
then pass the file to `gh`. Answers are free text and must never be spliced
into a shell command.

- If a record lists the open questions, fetch it again right before you edit
  it. Keep every other entry, add `YYYY-MM-DD, the human: <ruling> (as
  recommended | against the recommendation: <recommended>)`, and remove the
  question from the open list.
- On the issue or PR that the question is about, post a short comment with the
  same dated line and the main rejected alternative.
- Remove a "waiting on the human" label from an issue with no open question
  left, and keep it on the others.

## 5. Continue

Resume the work that the rulings unblock, within what the session was already
authorised to do. A ruling is not permission to merge, close or push if the
session had no such permission before. In that case, list what is unblocked in
the report.

## 6. Report

Give a short summary: what was ruled, what is still pending (including any
unanswered after a timeout), and what happens next. Do not restate every
question.
