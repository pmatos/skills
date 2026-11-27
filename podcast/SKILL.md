---
name: podcast
description: This skill should be used when the user asks to "make a podcast", "create a podcast episode about ...", "turn this article / paper / page into a podcast", "generate an audio discussion", "a NotebookLM-style audio overview", or invokes /podcast. Researches a topic or reads the given sources, writes a two- or three-voice conversational script, and renders a mastered MP3 with ElevenLabs Text to Dialogue (Eleven v4) and generated theme music.
argument-hint: "<topic | url | file> [--minutes N] [--voices 2|3] [--language xx]"
user-invocable: true
---

# Podcast

Make a high-quality conversational podcast episode with two or three voices. You
write the script yourself, in this session, so the quality of the episode is
decided by steps 2 to 5. The bundled script only does the audio.

`scripts/podcast.py` lives next to this file. It needs Python 3.11+ (standard
library only) and `ffmpeg`. Run it as `python3 <skill-dir>/scripts/podcast.py`.

| Command | What it does |
| --- | --- |
| `doctor` | Checks the key, ffmpeg, the cast's voices and the quota |
| `voices [--search q] [--language xx]` | Lists voices on the account |
| `check <script.json>` | Validates the script and estimates its size and cost |
| `all <script.json>` | Generates music, renders speech and masters the episode |
| `music`, `render`, `master` | The three steps of `all`, one at a time |
| `config` | Prints the effective config with the key masked |

## Defaults

- Length: about 15 minutes, which is 12,000–13,500 characters of dialogue. A
  length the user asks for wins.
- Participants: 2. Use 3 only when the user asks for it, or when the topic has a
  real third perspective (see [craft](references/craft.md#two-or-three-voices)).
- Language: English. Write natively in another language when the user asks for
  it, and set `"language"` to its ISO 639-1 code.
- Episode folder: `~/Podcasts/<YYYY-MM-DD>-<slug>/`, or `output_dir` from the
  config. Every file for the episode goes there.

## Workflow

### 0. Preflight

Run `doctor` once per session. If it reports no API key, show the user its
message (export `ELEVENLABS_API_KEY`, or put `{"api_key": "..."}` in
`~/.config/podcast/config.json` with mode 600) and stop. Never ask the user to
paste the key into the chat, and never print it. A key that lacks Voices read
or User read still works. `doctor` then reports those checks as skipped.

### 1. Brief

Do not ask questions unless the request has no topic. Infer the rest and write
`brief.md` with these points:

- the topic, and the one-sentence promise the episode makes to the listener
- the audience and what they already know
- the length, the participants and their roles, the language and the tone
- the sources the user gave, if any

### 2. Research

- **The user gave sources** (URLs, files, pasted text): read every one of them
  in full. Add web research only to fill gaps the user did not cover.
- **The user gave only a topic**: run several web searches in parallel. Then read
  the 4–8 best primary sources, not just the search snippets.

Write `research.md`:

- numbered sources, as `[1] Title — URL or path`
- a fact bank where every fact carries its source number
- the surprises, the open disagreements, concrete stories and examples, a few
  numbers worth saying aloud, and common misconceptions

Every factual claim in the script must trace back to this file. Never invent
studies, quotes, statistics or anecdotes.

### 3. Outline

Write `outline.md` before any dialogue. Follow
[craft: structure](references/craft.md#structure):

- a cold-open hook
- 3–6 beats, each with the question that drives it, its facts with source
  numbers, who leads it, and its turn (a surprise or a disagreement)
- a character budget for each beat
- the payoff, and 2–3 takeaways

### 4. Write the script

Write `script.json` in the episode folder. The format is in
[script-format](references/script-format.md), and the writing rules are in
[craft](references/craft.md). Read both files in full before you write. The
rules that matter most:

- It is a conversation, not a lecture read by two people. Mix short reactions
  with longer explanations, and let people interrupt, push back and build on
  each other.
- It is written for the ear: short sentences, the point first, no lists, no URLs
  and no markdown.
- Use audio tags such as `[laughs]`, `[curious]` and `[sighs]` sparingly,
  in English, about one every 3–5 turns.

### 5. Edit pass

Review the draft with a fresh reader. If a subagent tool is available, give a
subagent the files `research.md`, `outline.md` and `script.json` and the
[critic checklist](references/craft.md#critic-checklist). Ask it for concrete
line-level fixes, not praise. Otherwise, run the checklist yourself, turn by
turn. Apply the fixes, then read the opening two minutes once more as a
listener would hear them.

### 6. Check and approve

Run `check script.json` and fix every error it reports. Read its warnings too.

- If `needs_approval` is `false`, continue without asking. The script is
  within `auto_render_max_chars`, which is 14,000 by default (about 15 minutes).
- If it is `true`, show the user the title, cast, estimated minutes, characters,
  number of requests and the quota, if known. Then ask with `AskUserQuestion`:
  render as it is, shorten it to the default length, or stop.

Music is billed separately from speech characters and does not count toward the
limit.

### 7. Render

Run `all script.json`. It does three things:

- It generates a short instrumental theme once per episode. A missing paid plan
  or quota only drops the music and never fails the episode.
- It renders the speech in requests of at most 1,800 characters, joined with
  request stitching.
- It masters the episode to -16 LUFS and writes `<slug>.mp3` and
  `transcript.md`.

Rendering can be resumed. Each request is cached by a hash of its text, voices
and settings. If a run fails, fix the cause and run `all` again. Finished
requests are reused and are not paid for twice.

### 8. Deliver

Write `shownotes.md`: the title, a two-sentence summary, the chapters (the
section titles) and the numbered sources. Then report the MP3 path, its length,
the characters charged, whether music was added, and where the transcript and
show notes are.

## Revisions

To change a line, a voice or the music, edit `script.json` and run `all`
again. Only requests whose content changed are rendered again. A change in
length can move later request boundaries within the same section, so run
`check` first if you need to know the cost.

To try other voices, run `voices --search "<quality>"` and set `voice_id` on
that speaker. To change the default cast for every episode, edit the config; see
[config](references/config.md).
