# Craft: writing a podcast that sounds human

These rules turn research into a conversation that people want to keep listening
to. They apply in every language.

## Two or three voices

| Role | Job |
| --- | --- |
| `host` | Stands in for the listener. Opens and closes the show, steers between beats, and asks what the audience is thinking. It also sums up in plain words, and has opinions of its own. |
| `cohost` | Brings the depth: the explanations, the stories and the examples. It is not a lecturer. It gets interrupted, it is unsure about some things, and it sometimes asks questions back. |
| `guest` | The optional third voice. It brings a perspective that the other two cannot: a practitioner, a sceptic, someone with first-hand experience, or the other side of a debate. |

Use a third voice only when it adds a real point of view. Three people who agree
are worse than two. A guest is introduced by the host, speaks less often than
the other two (about 20–30% of the words), and has at least one moment where
they change the direction of the conversation.

Give every participant a name, a point of view, a level of knowledge and one or
two light verbal habits. Names default to the names in the config cast, which
fit their voices. If you choose other names, keep them plausible for the voice,
for example in gender and accent. A habit might be a favourite comparison, a dry sense of
humour, or a habit of asking "but why?". Keep the habits subtle. The personas
are fictional, so they may hold opinions. Do not give them made-up real-world
credentials or invented personal experiences presented as fact. A hypothetical
can be framed as one: "Imagine you run a bakery...".

## Structure

1. **Cold open, 20–40 seconds.** Start with the most surprising fact, a short
   story or a sharp question, before any "welcome". Then the host welcomes the
   listener and states the promise of the episode in one or two sentences.
2. **Beats, 3–6 of them.** Each beat answers one question that a curious
   listener would ask next. Each one needs a turn: a surprise, a
   misconception being corrected, a disagreement, or a concrete story. Order
   the beats so that each answer raises the next question.
3. **Payoff.** Bring the threads together. Use a callback to the cold open if
   there is a natural one.
4. **Takeaways.** Give 2–3 things the listener should remember, said in the
   speakers' own words rather than read as a list.
5. **Sign-off.** Keep it short and warm. One line from each voice is enough.

Map sections in `script.json` to these parts. Use a short, human title for each
section, because the titles become chapters in the show notes.

Length budget: about 900 characters is one minute of audio. A 15-minute episode
is 12,000–13,500 characters, which is roughly 120–170 turns.

## Conversation mechanics

- **Vary turn length.** Most turns are 1–3 sentences. An explanation can run 4–6
  sentences, about 600 characters at most, and is then broken by a reaction or a
  question. Never alternate in a strict A-B-A-B rhythm of equal lengths.
- **Build on the previous turn.** Each reply should respond to what was just said
  before it moves on. "So if that's true, then..." is better than a new
  question from nowhere.
- **Interrupt, sometimes.** End the interrupted line with an em dash and start the
  reply with one: `"and the strange part is—"` / `"—that nobody noticed for
  ten years."` Use this a few times per episode, not in every exchange.
- **Disagree at least once.** Let it settle on evidence, or leave it open on
  purpose. Polite, constant agreement is the biggest giveaway of a generated
  show.
- **Use backchannels sparingly.** "Right.", "Mm.", "Wait, really?" are fine as
  short turns of their own, but not more than one every 6–8 turns.
- **Make it concrete.** Every abstract point needs an example, an analogy or a
  number. Prefer one vivid example to three quick ones.
- **Say sources naturally.** Write "a 2024 survey of about two thousand nurses
  found..." rather than "according to source three". Mention the source only
  when it helps the listener trust the point.
- **Use names now and then.** People rarely say each other's names. Use a name
  only when the speaker addresses someone directly, or when a new voice comes
  in.

## Writing for the ear

- Use short sentences, with the point first. Use contractions.
- Use no lists of more than three items, no parentheses, and no stacked clauses.
- Spell things the way they should be said. Round numbers ("about two thirds",
  "nearly forty percent"). Spell out units ("kilometres per hour"). Expand
  abbreviations that are not spoken as words ("for example", not "e.g.").
  Years are fine as digits.
- Use no URLs, no markdown, no emoji and no stage directions in the text.
- Pauses come from punctuation: an ellipsis for hesitation, an em dash for a
  break. Eleven v4 ignores SSML, and `check` rejects `<break>` tags.
- In German, Portuguese or any other language, write natively in that language
  with its own idioms. Do not translate an English draft.

## Audio tags (Eleven v4)

Tags are short instructions in square brackets, written in English even when
the script is in another language. They shape the delivery of the words that
follow them.

- Delivery and emotion: `[laughs]`, `[chuckles]`, `[sighs]`,
  `[curious]`, `[excited]`, `[thoughtful]`, `[skeptical]`,
  `[surprised]`, `[whispers]`, `[deadpan]`, `[warmly]`.
- Put a tag at the start of a turn, or just before the phrase it should change:
  `"Well... [sighs] that's where it went wrong."`
- Use about one tag every 3–5 turns, and never more than two in one turn.
- Describe the voice, not a sound effect. `[laughs]` is safe. `[applause]` may
  be played as an actual sound.
- Written reactions work too, and are often more natural: "Ha!", "Hmm.", "Oh no."

## Accuracy

- Every factual claim must trace back to a fact in `research.md`.
- When sources disagree, the speakers say so. That disagreement is good
  material.
- Do not quote people word for word unless a source has the exact quote.
- When the research cannot back a claim, cut it or turn it into a question.

## Phrases and habits to avoid

These mark a script as generated. Cut them on sight:

- "Great question", "Absolutely!", "Exactly!", "That's fascinating", "So
  true", "I love that"
- "Let's dive in", "delve", "buckle up", "in today's fast-paced world", "game
  changer", "at the end of the day", "it's not just X, it's Y"
- a speaker repeating or summarising what the other one just said
- every turn opening with a reaction word
- both hosts agreeing all the time, or the host only asking questions while the
  expert only answers them
- a wrap-up that lists every beat again
- a final line like "Thanks for listening, and remember to stay curious!"

## Critic checklist

Hand this checklist to the reviewer in step 5. Every item needs a verdict and,
when it fails, a concrete fix that quotes the line.

1. Does the first 30 seconds give a reason to keep listening, before the
   welcome?
2. Does each beat answer a question the listener would actually have next, and
   does each one have a turn (a surprise, a disagreement or a story)?
3. Is there at least one real disagreement? Does each speaker sound like a
   different person, with their own opinions and habits?
4. Are the turn lengths varied? Does any explanation run past about 600
   characters without a break? Is the rhythm a strict A-B alternation?
5. Does every factual claim match `research.md`? List any claim that does not.
6. Are there phrases from the avoid list, or any repeated filler or reaction
   words?
7. Does any line fail when heard: written-only phrasing, lists, numbers or
   abbreviations that read badly aloud, URLs, markdown?
8. Are the audio tags sparse and plausible, with no sound-effect tags and none
   stacked?
9. With 3 voices: does the guest earn their place, and do they get about 20–30%
   of the words?
10. Is the length inside the budget? Which beat would you cut first if it is not?
