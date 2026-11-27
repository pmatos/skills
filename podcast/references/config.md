# Configuration

The config file is `~/.config/podcast/config.json`. Set `PODCAST_CONFIG` to use a
different path. Every key is optional, and any key you set is merged over these
defaults:

```json
{
  "api_key": "only if ELEVENLABS_API_KEY is not exported",
  "model_id": "eleven_v4",
  "output_format": "mp3_44100_128",
  "output_dir": "~/Podcasts",
  "auto_render_max_chars": 14000,
  "chunk_max_chars": 1800,
  "gap_ms": 250,
  "stitching": true,
  "settings": { "stability": 0.5 },
  "cast": {
    "host": { "name": "George", "voice_id": "JBFqnCBsd6RMkjVDRZzb" },
    "cohost": { "name": "Sarah", "voice_id": "EXAVITQu4vr4xnSDxMaL" },
    "guest": { "name": "Charlie", "voice_id": "IKne3meq5aSn9XLyUdCD" }
  },
  "music": {
    "enabled": true,
    "model_id": "music_v2_5",
    "intro_ms": 10000,
    "outro_ms": 12000,
    "volume": 0.7,
    "prompt": "Warm, modern podcast theme ..."
  },
  "loudness": { "integrated": -16, "true_peak": -1.5, "lra": 11 }
}
```

## API key

The `ELEVENLABS_API_KEY` environment variable wins. Otherwise the tool uses
`api_key` from this file, and warns if the file can be read by other users
(`chmod 600`). The key is never printed. `config` masks it, and API error
messages have it removed.

A restricted key needs Text to Speech, for Text to Dialogue, and Music access.
Voices read lets `doctor` and `voices` check voice ids. User read lets `check`
report the remaining quota. Without these two, the checks are skipped. The
Music API needs a paid plan. On a free plan the episode is rendered without
music.

## Settings worth changing

- **`cast`**: the default voice for each role. Find voices with `voices
  --search "warm british"` or `voices --language de`. Choose voices that
  contrast in pitch, pace and accent, so listeners can tell the speakers apart
  without names.
- **`settings.stability`**: lower values (0.3–0.4) are more expressive and less
  predictable. Higher values (0.6–0.7) are steadier.
- **`auto_render_max_chars`**: above this size the skill asks before it renders.
  14,000 characters is about 15 minutes.
- **`music.prompt`**: the theme for every episode. A per-episode `music.prompt`
  in `script.json` overrides it. Set `music.file` to reuse one theme for the
  whole show and skip music generation.
- **`output_format`**: `mp3_44100_192` needs the Creator tier or higher, and
  PCM at 44.1 kHz needs Pro. The final MP3 is always re-encoded after
  mastering, so the default is enough.
- **`loudness`**: -16 LUFS integrated and -1.5 dBTP are the usual targets for
  podcasts. The tool measures in a first pass and corrects in a second pass.
