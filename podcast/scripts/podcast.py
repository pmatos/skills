#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render multi-voice podcast episodes with the ElevenLabs API.

The agent writes `script.json`; this tool validates it, turns it into speech with
Text to Dialogue, generates intro/outro music and masters the episode with ffmpeg.

Subcommands: config, doctor, voices, check, music, render, master, all.
Standard library only, plus ffmpeg/ffprobe on PATH.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API_BASE = "https://api.elevenlabs.io"
ROLES = ("host", "cohost", "guest")
CHARS_PER_MINUTE = 900
INTERRUPTION_ENDINGS = ("-", "—", "–", "...", "…")

DEFAULTS: dict = {
    "model_id": "eleven_v4",
    "output_format": "mp3_44100_128",
    "output_dir": "~/Podcasts",
    "auto_render_max_chars": 14000,
    "chunk_max_chars": 1800,
    "gap_ms": 250,
    "stitching": True,
    "settings": {"stability": 0.5},
    "cast": {
        "host": {"name": "George", "voice_id": "JBFqnCBsd6RMkjVDRZzb"},
        "cohost": {"name": "Sarah", "voice_id": "EXAVITQu4vr4xnSDxMaL"},
        "guest": {"name": "Charlie", "voice_id": "IKne3meq5aSn9XLyUdCD"},
    },
    "music": {
        "enabled": True,
        "model_id": "music_v2_5",
        "intro_ms": 10000,
        "outro_ms": 12000,
        "volume": 0.7,
        "prompt": (
            "Warm, modern podcast theme. Light electronic beat, soft synth pads, "
            "clean bass, optimistic and curious mood, 100 bpm, no vocals."
        ),
    },
    "loudness": {"integrated": -16.0, "true_peak": -1.5, "lra": 11.0},
}

KEY_HELP = """No ElevenLabs API key found.

Either export it for this shell:
    export ELEVENLABS_API_KEY=...
or put it in {path} (and keep that file private):
    {{"api_key": "..."}}
    chmod 600 {path}

The key needs Text to Speech and Music access. Voices read and User read are
optional: without them, voice checks and the quota report are skipped."""


class PodcastError(Exception):
    """A failure the user should read; printed without a traceback."""


# --------------------------------------------------------------------------- config


def config_path() -> Path:
    return Path(os.environ.get("PODCAST_CONFIG", "~/.config/podcast/config.json")).expanduser()


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    user: dict = {}
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise PodcastError(f"{path} is not valid JSON: {e}") from e
    return deep_merge(DEFAULTS, user)


def resolve_api_key(cfg: dict, path: Path | None = None) -> tuple[str, str]:
    """Return (key, source). The environment wins over the config file."""
    path = path or config_path()
    env = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if env:
        return env, "env ELEVENLABS_API_KEY"
    key = str(cfg.get("api_key") or "").strip()
    if key:
        try:
            if path.stat().st_mode & 0o077:
                warn(f"{path} is readable by other users; run: chmod 600 {path}")
        except OSError:
            pass
        return key, str(path)
    raise PodcastError(KEY_HELP.format(path=path))


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- HTTP


class ApiError(PodcastError):
    def __init__(self, status: int, message: str, path: str):
        super().__init__(f"ElevenLabs {path} failed with HTTP {status}: {message}")
        self.status = status
        self.message = message


@dataclass
class Response:
    body: bytes
    headers: dict


def _error_message(raw: bytes) -> str:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw[:300].decode("utf-8", "replace")
    detail = data.get("detail", data) if isinstance(data, dict) else data
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("status") or detail)
    if isinstance(detail, list):
        return "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
    return str(detail)


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read()


class Client:
    def __init__(self, key: str, transport=urllib_transport, retries: int = 4, sleep=time.sleep):
        self._key = key
        self.transport = transport
        self.retries = retries
        self.sleep = sleep

    def call(
        self, method, path, *, query=None, json_body=None, accept="application/json", timeout=300.0
    ) -> Response:
        url = API_BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        headers = {"xi-api-key": self._key, "Accept": accept}
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        for attempt in range(self.retries + 1):
            try:
                status, rheaders, raw = self.transport(method, url, headers, body, timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < self.retries:
                    self._backoff(attempt, None)
                    continue
                raise PodcastError(f"network error calling ElevenLabs {path}: {e}") from e
            if (status == 429 or status >= 500) and attempt < self.retries:
                self._backoff(attempt, rheaders.get("retry-after"))
                continue
            if status >= 400:
                raise ApiError(status, _error_message(raw).replace(self._key, "***"), path)
            return Response(raw, rheaders)
        raise PodcastError(f"ElevenLabs {path}: retries exhausted")

    def json(self, method, path, **kw):
        return json.loads(self.call(method, path, **kw).body or b"null")

    def _backoff(self, attempt: int, retry_after) -> None:
        try:
            base = float(retry_after) if retry_after else min(2**attempt, 30)
        except ValueError:
            base = min(2**attempt, 30)
        self.sleep(base + random.uniform(0, 1))


def missing_permission(e: ApiError) -> bool:
    return e.status in (401, 403) and "permission" in e.message.lower()


# --------------------------------------------------------------------------- script model


@dataclass
class Speaker:
    key: str
    name: str
    role: str
    voice_id: str


@dataclass
class Turn:
    section: int
    speaker: str
    text: str


@dataclass
class Chunk:
    index: int
    turns: list[Turn]
    inputs: list[dict]
    hash: str = ""

    @property
    def chars(self) -> int:
        return sum(len(i["text"]) for i in self.inputs)


@dataclass
class Episode:
    path: Path
    data: dict
    speakers: dict[str, Speaker]
    turns: list[Turn]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return self.path.parent

    @property
    def language(self) -> str:
        return str(self.data.get("language") or "en")

    @property
    def title(self) -> str:
        return str(self.data.get("title") or self.dir.name)

    @property
    def chars(self) -> int:
        return sum(len(t.text) for t in self.turns)


def load_episode(path: Path, cfg: dict) -> Episode:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise PodcastError(f"script not found: {path}") from e
    except json.JSONDecodeError as e:
        raise PodcastError(f"{path} is not valid JSON: {e}") from e
    ep = Episode(path=path, data=data, speakers={}, turns=[])
    validate(ep, cfg)
    return ep


def validate(ep: Episode, cfg: dict) -> None:
    data, err, wrn = ep.data, ep.errors, ep.warnings
    if not isinstance(data, dict):
        err.append("script must be a JSON object")
        return
    if not str(data.get("title") or "").strip():
        wrn.append("no title; the episode folder name is used instead")

    speakers = data.get("speakers")
    if not isinstance(speakers, dict) or not 2 <= len(speakers) <= 3:
        err.append("'speakers' must be an object with 2 or 3 participants")
        speakers = speakers if isinstance(speakers, dict) else {}
    cast = cfg.get("cast", {})
    seen_roles: set[str] = set()
    for key, spec in speakers.items():
        spec = spec if isinstance(spec, dict) else {}
        role = spec.get("role")
        if role not in ROLES:
            err.append(f"speaker '{key}': role must be one of {', '.join(ROLES)}")
            continue
        if role in seen_roles:
            err.append(f"speaker '{key}': role '{role}' is used twice")
        seen_roles.add(role)
        voice = spec.get("voice_id") or (cast.get(role) or {}).get("voice_id")
        if not voice:
            err.append(f"speaker '{key}': no voice_id, and the config cast has none for '{role}'")
            continue
        name = spec.get("name") or (cast.get(role) or {}).get("name") or key.capitalize()
        ep.speakers[key] = Speaker(key=key, name=name, role=role, voice_id=voice)
    voices = [s.voice_id for s in ep.speakers.values()]
    if len(set(voices)) != len(voices):
        err.append("two speakers share the same voice_id; every participant needs a distinct voice")

    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        err.append("'sections' must be a non-empty list")
        return
    for si, section in enumerate(sections):
        turns = section.get("turns") if isinstance(section, dict) else None
        label = (section.get("title") if isinstance(section, dict) else None) or f"#{si + 1}"
        if not isinstance(turns, list) or not turns:
            err.append(f"section {label}: 'turns' must be a non-empty list")
            continue
        for ti, turn in enumerate(turns):
            where = f"section {label}, turn {ti + 1}"
            if not isinstance(turn, dict):
                err.append(f"{where}: must be an object")
                continue
            spk, text = turn.get("speaker"), str(turn.get("text") or "").strip()
            if spk not in speakers:
                err.append(f"{where}: unknown speaker '{spk}'")
                continue
            if not text:
                err.append(f"{where}: empty text")
                continue
            if "<break" in text or "<speak" in text:
                err.append(f"{where}: SSML tags are not supported by Eleven v4; use punctuation")
            if re.search(r"https?://|\*\*|^#", text):
                wrn.append(f"{where}: contains a URL or markdown, which will be read aloud")
            ep.turns.append(Turn(section=si, speaker=str(spk), text=text))
    spoken = {t.speaker for t in ep.turns}
    for key in speakers:
        if key not in spoken:
            err.append(f"speaker '{key}' never speaks")


# --------------------------------------------------------------------------- chunking


def split_long_text(text: str, limit: int) -> list[str]:
    """Split one long turn at sentence ends, then at spaces, so each part fits."""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    parts: list[str] = []
    cur = ""
    for s in sentences:
        while len(s) > limit:
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(s[:cut].strip())
            s = s[cut:].strip()
        candidate = f"{cur} {s}".strip()
        if len(candidate) > limit and cur:
            parts.append(cur)
            cur = s
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts


def ends_in_interruption(text: str) -> bool:
    return text.rstrip().rstrip("\"'”").endswith(INTERRUPTION_ENDINGS)


def plan_chunks(ep: Episode, cfg: dict) -> list[Chunk]:
    limit = int(cfg["chunk_max_chars"])
    turns: list[Turn] = []
    for t in ep.turns:
        if len(t.text) <= limit:
            turns.append(t)
        else:
            turns.extend(Turn(t.section, t.speaker, p) for p in split_long_text(t.text, limit))

    groups: list[list[Turn]] = []
    cur: list[Turn] = []
    size = 0

    def close():
        nonlocal cur, size
        carry: list[Turn] = []
        # Keep an interrupted line together with the reply that cuts it off.
        while len(cur) > 1 and ends_in_interruption(cur[-1].text):
            carry.insert(0, cur.pop())
        groups.append(cur)
        cur = carry
        size = sum(len(x.text) for x in cur)

    for t in turns:
        new_section = bool(cur) and t.section != cur[-1].section
        if cur and (size + len(t.text) > limit or (new_section and size >= 0.6 * limit)):
            close()
            if cur and size + len(t.text) > limit:
                groups.append(cur)
                cur, size = [], 0
        cur.append(t)
        size += len(t.text)
    if cur:
        groups.append(cur)

    chunks = []
    for i, g in enumerate(groups):
        inputs = [{"text": t.text, "voice_id": ep.speakers[t.speaker].voice_id} for t in g]
        c = Chunk(index=i, turns=g, inputs=inputs)
        c.hash = chunk_hash(c, ep, cfg)
        chunks.append(c)
    return chunks


def chunk_seed(ep: Episode, inputs: list[dict]) -> int | None:
    """Derive each request's seed from its content, so moving a request keeps its seed."""
    seed = ep.data.get("seed")
    if seed is None:
        return None
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return (int(seed) + int(digest[:8], 16)) % 4294967296


def chunk_hash(c: Chunk, ep: Episode, cfg: dict) -> str:
    material = {
        "inputs": c.inputs,
        "model_id": cfg["model_id"],
        "output_format": cfg["output_format"],
        "settings": cfg.get("settings"),
        "language": ep.language,
        "seed": chunk_seed(ep, c.inputs),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------- check


def quota(client: Client | None) -> dict:
    if client is None:
        return {"available": False, "reason": "no API key"}
    try:
        sub = client.json("GET", "/v1/user/subscription")
    except ApiError as e:
        reason = "the key lacks User read permission" if missing_permission(e) else e.message
        return {"available": False, "reason": reason}
    used, limit = int(sub.get("character_count") or 0), int(sub.get("character_limit") or 0)
    return {
        "available": True,
        "tier": sub.get("tier"),
        "used": used,
        "limit": limit,
        "remaining": max(limit - used, 0),
    }


def check_report(ep: Episode, cfg: dict, client: Client | None) -> dict:
    report = {"script": str(ep.path), "errors": ep.errors, "warnings": ep.warnings}
    if ep.errors:
        return report
    chunks = plan_chunks(ep, cfg)
    limit = int(cfg["auto_render_max_chars"])
    words = {k: 0 for k in ep.speakers}
    for t in ep.turns:
        words[t.speaker] += len(t.text.split())
    total_words = sum(words.values()) or 1
    music = music_spec(ep, cfg)
    report.update(
        {
            "title": ep.title,
            "language": ep.language,
            "speakers": {
                k: {
                    "name": s.name,
                    "role": s.role,
                    "voice_id": s.voice_id,
                    "share": f"{100 * words[k] // total_words}%",
                }
                for k, s in ep.speakers.items()
            },
            "turns": len(ep.turns),
            "characters": ep.chars,
            "estimated_minutes": round(ep.chars / CHARS_PER_MINUTE, 1),
            "requests": len(chunks),
            "largest_request_chars": max(c.chars for c in chunks),
            "music": "intro/outro theme (billed separately)" if music else "none",
            "auto_render_max_chars": limit,
            "needs_approval": ep.chars > limit,
            "quota": quota(client),
        }
    )
    q = report["quota"]
    if q.get("available") and q["remaining"] < ep.chars:
        report["errors"].append(
            f"only {q['remaining']} characters left this period; the script needs {ep.chars}"
        )
    return report


# --------------------------------------------------------------------------- render


def state_path(ep: Episode) -> Path:
    return ep.dir / "render" / "state.json"


def load_state(ep: Episode) -> dict:
    p = state_path(ep)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"chunks": {}, "stitching_disabled": False}


def save_state(ep: Episode, state: dict) -> None:
    p = state_path(ep)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(p)


def chunk_file(ep: Episode, c: Chunk, cfg: dict) -> Path:
    ext = str(cfg["output_format"]).split("_")[0]
    return ep.dir / "render" / f"chunk-{c.hash[:16]}.{ext}"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def render(ep: Episode, cfg: dict, client: Client, log=print) -> dict:
    chunks = plan_chunks(ep, cfg)
    state = load_state(ep)
    request_ids: list[str] = []
    charged = rendered = reused = 0
    for c in chunks:
        out = chunk_file(ep, c, cfg)
        entry = state["chunks"].get(c.hash)
        if entry and out.exists():
            reused += 1
            if entry.get("request_id"):
                request_ids.append(entry["request_id"])
            continue
        body = {"inputs": c.inputs, "model_id": cfg["model_id"], "language_code": ep.language}
        if cfg.get("settings"):
            body["settings"] = cfg["settings"]
        seed = chunk_seed(ep, c.inputs)
        if seed is not None:
            body["seed"] = seed
        stitch = cfg.get("stitching", True) and not state.get("stitching_disabled")
        if stitch and request_ids:
            body["previous_request_ids"] = request_ids[-3:]
        log(f"rendering request {c.index + 1}/{len(chunks)} ({c.chars} chars)")
        query = {"output_format": cfg["output_format"]}
        try:
            resp = client.call(
                "POST", "/v1/text-to-dialogue", query=query, json_body=body, accept="audio/*"
            )
        except ApiError as e:
            if "previous_request_ids" in body and e.status in (400, 422):
                log(f"request stitching rejected ({e.message}); continuing without it")
                state["stitching_disabled"] = True
                del body["previous_request_ids"]
                resp = client.call(
                    "POST", "/v1/text-to-dialogue", query=query, json_body=body, accept="audio/*"
                )
            else:
                save_state(ep, state)
                raise
        if not resp.body:
            raise PodcastError(f"request {c.index + 1} returned no audio")
        atomic_write(out, resp.body)
        rid = resp.headers.get("request-id")
        cost = resp.headers.get("character-cost")
        state["chunks"][c.hash] = {
            "index": c.index,
            "file": out.name,
            "request_id": rid,
            "characters": c.chars,
            "character_cost": cost,
        }
        save_state(ep, state)
        if rid:
            request_ids.append(rid)
        charged += int(cost) if cost and cost.isdigit() else c.chars
        rendered += 1
    return {
        "requests": len(chunks),
        "rendered": rendered,
        "reused": reused,
        "characters_charged": charged,
        "stitching": not state.get("stitching_disabled"),
    }


# --------------------------------------------------------------------------- music


def music_spec(ep: Episode, cfg: dict) -> dict | None:
    m = cfg.get("music") or {}
    over = ep.data.get("music", {})
    if over is False or not m.get("enabled", True):
        return None
    spec = deep_merge(m, over if isinstance(over, dict) else {})
    spec["length_ms"] = max(int(spec["intro_ms"]), int(spec["outro_ms"])) + 3000
    return spec


def music_file(ep: Episode, spec: dict) -> Path:
    key = json.dumps([spec["prompt"], spec["length_ms"], spec["model_id"]])
    return ep.dir / "music" / f"theme-{hashlib.sha256(key.encode()).hexdigest()[:10]}.mp3"


def music_unavailable(e: ApiError) -> bool:
    """True for errors that mean this account cannot make music now, not a bad request."""
    words = ("paid", "plan", "quota", "subscription")
    return e.status in (401, 402, 403, 429) or any(w in e.message.lower() for w in words)


def make_music(ep: Episode, cfg: dict, client: Client, log=print) -> Path | None:
    """Generate (or reuse) the theme. Plan, permission and quota errors drop the music."""
    spec = music_spec(ep, cfg)
    if spec is None:
        return None
    if spec.get("file"):
        p = Path(spec["file"]).expanduser()
        if not p.exists():
            raise PodcastError(f"music file not found: {p}")
        return p
    out = music_file(ep, spec)
    if out.exists():
        return out
    body = {
        "prompt": spec["prompt"],
        "music_length_ms": spec["length_ms"],
        "model_id": spec["model_id"],
        "force_instrumental": True,
    }
    log(f"generating {spec['length_ms'] // 1000}s theme music")
    try:
        resp = client.call(
            "POST",
            "/v1/music",
            query={"output_format": "mp3_44100_128"},
            json_body=body,
            accept="audio/*",
        )
    except ApiError as e:
        if not music_unavailable(e):
            raise
        log(f"warning: music generation failed ({e.message}); the episode will have no music")
        return None
    atomic_write(out, resp.body)
    return out


# --------------------------------------------------------------------------- mastering


def need_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise PodcastError(f"{tool} is required; install ffmpeg")


def run_ffmpeg(args: list[str]) -> str:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise PodcastError("ffmpeg failed:\n" + proc.stderr[-3000:])
    return proc.stderr


def duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(proc.stdout.strip())


NORM = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"


def concat_voice(files: list[Path], gap_ms: int, out: Path) -> None:
    args: list[str] = []
    for f in files:
        args += ["-i", str(f)]
    parts = []
    for i in range(len(files)):
        pad = f",apad=pad_dur={gap_ms / 1000}" if i < len(files) - 1 else ""
        parts.append(f"[{i}:a]{NORM}{pad}[v{i}]")
    joined = "".join(f"[v{i}]" for i in range(len(files)))
    graph = ";".join(parts) + f";{joined}concat=n={len(files)}:v=0:a=1[out]"
    run_ffmpeg([*args, "-filter_complex", graph, "-map", "[out]", "-c:a", "pcm_s16le", str(out)])


def mix_music(voice: Path, theme: Path, spec: dict, out: Path) -> None:
    vdur = duration(voice)
    intro, outro = int(spec["intro_ms"]) / 1000, int(spec["outro_ms"]) / 1000
    vol = float(spec.get("volume", 0.7))
    voice_start = max(intro - 1.5, 0)
    outro_start = voice_start + vdur - 1.0
    graph = (
        f"[1:a]{NORM},asplit=2[m1][m2];"
        f"[m1]atrim=0:{intro},afade=t=out:st={max(intro - 2.5, 0)}:d=2.5,volume={vol}[intro];"
        f"[m2]atrim=0:{outro},asetpts=PTS-STARTPTS,afade=t=in:d=1.5,"
        f"afade=t=out:st={max(outro - 4, 0)}:d=4,volume={vol},"
        f"adelay={int(outro_start * 1000)}:all=1[outro];"
        f"[0:a]{NORM},adelay={int(voice_start * 1000)}:all=1[v];"
        f"[intro][v][outro]amix=inputs=3:normalize=0:duration=longest[out]"
    )
    run_ffmpeg(
        [
            "-i",
            str(voice),
            "-i",
            str(theme),
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            str(out),
        ]
    )


def loudnorm(src: Path, out: Path, loud: dict, tags: dict) -> dict:
    target = f"I={loud['integrated']}:TP={loud['true_peak']}:LRA={loud['lra']}"
    log = run_ffmpeg(
        ["-i", str(src), "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"]
    )
    m = json.loads(log[log.rindex("{") : log.rindex("}") + 1])
    second = (
        f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
        f"offset={m['target_offset']}:linear=true,aresample=44100"
    )
    meta: list[str] = []
    for k, v in tags.items():
        meta += ["-metadata", f"{k}={v}"]
    run_ffmpeg(
        [
            "-i",
            str(src),
            "-af",
            second,
            "-ar",
            "44100",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            *meta,
            str(out),
        ]
    )
    return {"input_lufs": m["input_i"], "target_lufs": loud["integrated"]}


TAG_RE = re.compile(r"\s*\[[^\]]*\]\s*")


def write_transcript(ep: Episode) -> Path:
    lines = [f"# {ep.title}", ""]
    cast = ", ".join(f"{s.name} ({s.role})" for s in ep.speakers.values())
    lines += [f"With {cast}.", ""]
    sections = ep.data.get("sections", [])
    current = None
    for t in ep.turns:
        if t.section != current:
            current = t.section
            title = sections[t.section].get("title") if t.section < len(sections) else None
            if title:
                lines += [f"## {title}", ""]
        text = TAG_RE.sub(" ", t.text).strip()
        lines += [f"**{ep.speakers[t.speaker].name}:** {text}", ""]
    out = ep.dir / "transcript.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "episode"


def master(ep: Episode, cfg: dict, theme: Path | None, log=print) -> dict:
    need_ffmpeg()
    chunks = plan_chunks(ep, cfg)
    state = load_state(ep)
    files = []
    for c in chunks:
        f = chunk_file(ep, c, cfg)
        if c.hash not in state["chunks"] or not f.exists():
            raise PodcastError(f"request {c.index + 1} has not been rendered; run render first")
        files.append(f)
    spec = music_spec(ep, cfg) if theme else None
    out = ep.dir / f"{slugify(ep.title)}.mp3"
    with tempfile.TemporaryDirectory(dir=ep.dir) as tmp:
        voice = Path(tmp) / "voice.wav"
        log(f"joining {len(files)} requests")
        concat_voice(files, int(cfg["gap_ms"]), voice)
        mixed = voice
        if theme and spec:
            log("mixing intro and outro music")
            mixed = Path(tmp) / "mixed.wav"
            mix_music(voice, theme, spec, mixed)
        log("normalising loudness")
        names = ", ".join(s.name for s in ep.speakers.values())
        loud = loudnorm(
            mixed,
            out,
            cfg["loudness"],
            {
                "title": ep.title,
                "artist": names,
                "album": "Podcast",
                "date": time.strftime("%Y"),
                "language": ep.language,
            },
        )
    transcript = write_transcript(ep)
    return {
        "episode": str(out),
        "minutes": round(duration(out) / 60, 1),
        "transcript": str(transcript),
        "music": bool(theme),
        **loud,
    }


# --------------------------------------------------------------------------- doctor / voices


def doctor(cfg: dict) -> dict:
    report: dict = {"config": str(config_path()), "ffmpeg": bool(shutil.which("ffmpeg"))}
    try:
        key, source = resolve_api_key(cfg)
    except PodcastError:
        report["api_key"] = "missing"
        return report
    report["api_key"] = f"found ({source})"
    client = Client(key)
    report["quota"] = quota(client)
    voices = {}
    for role, spec in cfg.get("cast", {}).items():
        vid = (spec or {}).get("voice_id")
        if not vid:
            voices[role] = "not set"
            continue
        try:
            v = client.json("GET", f"/v1/voices/{vid}")
            voices[role] = f"ok: {v.get('name')} ({vid})"
        except ApiError as e:
            voices[role] = (
                "not checked: the key lacks Voices read permission"
                if missing_permission(e)
                else f"problem: {e.message}"
            )
    report["cast"] = voices
    return report


def list_voices(cfg: dict, search: str | None, language: str | None, voice_type: str | None):
    key, _ = resolve_api_key(cfg)
    query: dict = {"page_size": 50}
    if search:
        query["search"] = search
    if language:
        query["language"] = language
    if voice_type:
        query["voice_type"] = voice_type
    data = Client(key).json("GET", "/v2/voices", query=query)
    rows = []
    for v in data.get("voices", []):
        labels = v.get("labels") or {}
        desc = ", ".join(
            str(labels[k])
            for k in ("gender", "age", "accent", "descriptive", "use_case")
            if labels.get(k)
        )
        rows.append(f"{v['voice_id']}  {v.get('name')}  [{v.get('category')}]  {desc}")
    return rows


# --------------------------------------------------------------------------- CLI


def masked_config(cfg: dict) -> dict:
    out = json.loads(json.dumps(cfg))
    if out.get("api_key"):
        out["api_key"] = "***"
    return out


def client_or_none(cfg: dict) -> Client | None:
    try:
        return Client(resolve_api_key(cfg)[0])
    except PodcastError:
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="podcast.py",
        description="Render multi-voice podcast episodes with the ElevenLabs API.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("config", help="print the effective config (key masked)")
    sub.add_parser("doctor", help="check key, ffmpeg, cast voices and quota")
    v = sub.add_parser("voices", help="list voices available to the account")
    v.add_argument("--search")
    v.add_argument("--language", help="ISO 639-1 code, e.g. de")
    v.add_argument(
        "--type", dest="voice_type", help="personal, community, default, workspace, saved, ..."
    )
    for name, help_ in (
        ("check", "validate a script and estimate its cost"),
        ("music", "generate the intro/outro theme"),
        ("render", "render speech for every request"),
        ("master", "join, mix and normalise the episode"),
        ("all", "music, render and master in one go"),
    ):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("script", type=Path)
    args = p.parse_args(argv)

    try:
        cfg = load_config()
        if args.cmd == "config":
            print(json.dumps(masked_config(cfg), indent=2))
            return 0
        if args.cmd == "doctor":
            print(json.dumps(doctor(cfg), indent=2))
            return 0
        if args.cmd == "voices":
            print("\n".join(list_voices(cfg, args.search, args.language, args.voice_type)))
            return 0
        ep = load_episode(args.script.expanduser().resolve(), cfg)
        if args.cmd == "check":
            report = check_report(ep, cfg, client_or_none(cfg))
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1 if report["errors"] else 0
        if ep.errors:
            raise PodcastError("script has errors; run check:\n  " + "\n  ".join(ep.errors))
        client = Client(resolve_api_key(cfg)[0])
        result: dict = {}
        if args.cmd in ("music", "all"):
            theme = make_music(ep, cfg, client)
            result["music"] = str(theme) if theme else None
        if args.cmd in ("render", "all"):
            result["render"] = render(ep, cfg, client)
        if args.cmd in ("master", "all"):
            spec = music_spec(ep, cfg)
            theme = None
            if spec:
                candidate = (
                    Path(spec["file"]).expanduser() if spec.get("file") else music_file(ep, spec)
                )
                theme = candidate if candidate.exists() else None
            result["master"] = master(ep, cfg, theme)
        print(json.dumps(result, indent=2))
        return 0
    except PodcastError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
