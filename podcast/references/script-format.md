# script.json format

`script.json` lives in the episode folder. All rendered files are written next
to it: `render/`, `music/`, `<slug>.mp3` and `transcript.md`.

```json
{
  "title": "Why Bees Dance",
  "language": "en",
  "speakers": {
    "maya": { "role": "host", "name": "Maya" },
    "tom": { "role": "cohost", "name": "Tom" },
    "ines": { "role": "guest", "name": "Inês", "voice_id": "optional-override" }
  },
  "music": { "prompt": "Playful acoustic folk theme, ukulele and light percussion, no vocals" },
  "seed": 1234,
  "sections": [
    {
      "title": "The dance floor",
      "turns": [
        { "speaker": "maya", "text": "A honeybee can give directions to a flower two miles away... with a dance." },
        { "speaker": "tom", "text": "[laughs] And the other bees actually follow it." }
      ]
    }
  ]
}
```

## Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `title` | yes | The episode title. It sets the MP3 file name, the ID3 title, and the headings of the transcript and show notes. |
| `language` | no | An ISO 639-1 code. The default is `en`, and it is passed to the API as `language_code`. |
| `speakers` | yes | 2 or 3 entries, keyed by a short id that the turns refer to. |
| `speakers.*.role` | yes | `host`, `cohost` or `guest`, each used at most once. The role picks the default voice from the config cast. |
| `speakers.*.name` | no | The name used in the transcript. It defaults to the cast name for the role, which fits its voice, and then to the capitalised id. |
| `speakers.*.voice_id` | no | Overrides the cast voice for this episode. Every speaker needs a different voice. |
| `music` | no | `false` turns music off for this episode. An object overrides any of `prompt`, `intro_ms`, `outro_ms`, `volume` and `model_id`, or names a `file` to reuse an existing theme. |
| `seed` | no | An integer that makes the renders more repeatable. Each request's seed is derived from `seed` and the request's own text, so moving a request does not change it. |
| `sections` | yes | An ordered list of `{ "title", "turns" }`. The section titles become chapters. |
| `turns[].speaker` | yes | A key from `speakers`. |
| `turns[].text` | yes | What is said, including any audio tags. |

## How the script becomes audio

- The turns are packed in order into requests of at most `chunk_max_chars`
  characters, which is 1,800 by default. The API's reliable limit is 2,000.
- A new section starts a new request once the current one is at least 60% full.
- A turn that ends in an interruption (a dash or an ellipsis) stays in the
  same request as the reply that follows it.
- A single turn longer than the limit is split at sentence ends. Keep turns
  short enough that this never happens.
- Each request after the first sends the ids of up to 3 previous requests, so
  that the voices and prosody carry over. If the API rejects this, rendering
  continues without it and the state records that.
- The cache key of each request is a hash of its text, its voice ids, the model,
  the output format, the settings, the language and the seed. Changing any of
  them renders that request again. Everything else is reused, even when an
  insertion earlier in the script moves it to a new position.
