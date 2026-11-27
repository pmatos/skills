import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "podcast.py"
spec = importlib.util.spec_from_file_location("podcast", SCRIPT)
assert spec and spec.loader
pc = importlib.util.module_from_spec(spec)
sys.modules["podcast"] = pc
spec.loader.exec_module(pc)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_CONFIG", str(tmp_path / "no-config.json"))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


def cfg(**over):
    return pc.deep_merge(pc.DEFAULTS, over)


def script(tmp_path, turns=None, speakers=None, **extra):
    speakers = speakers or {
        "maya": {"role": "host", "name": "Maya"},
        "tom": {"role": "cohost", "name": "Tom"},
    }
    turns = turns or [
        {"speaker": "maya", "text": "Welcome back. Today we talk about bees."},
        {"speaker": "tom", "text": "[excited] I have been waiting for this one."},
    ]
    data = {"title": "Bees", "speakers": speakers, "sections": [{"title": "Open", "turns": turns}]}
    data.update(extra)
    d = tmp_path / "ep"
    d.mkdir(exist_ok=True)
    p = d / "script.json"
    p.write_text(json.dumps(data))
    return p


class FakeApi:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}
        self.n = 0

    def __call__(self, method, url, headers, body, timeout):
        payload = json.loads(body) if body else None
        self.calls.append({"method": method, "url": url, "headers": headers, "body": payload})
        for needle, response in list(self.fail.items()):
            if needle(url, payload):
                if isinstance(response, list):
                    r = response.pop(0)
                    if not response:
                        del self.fail[needle]
                    return r
                return response
        self.n += 1
        return 200, {"request-id": f"req-{self.n}", "character-cost": "10"}, b"AUDIO%d" % self.n


def client(api):
    return pc.Client("sk_secret_key", transport=api, sleep=lambda s: None)


# ---------------------------------------------------------------- key resolution


def test_env_key_wins_over_file(tmp_path, monkeypatch):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"api_key": "from-file"}))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-env")
    assert pc.resolve_api_key(pc.load_config(path), path) == ("from-env", "env ELEVENLABS_API_KEY")


def test_file_key_used_and_loose_permissions_warn(tmp_path, capsys):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"api_key": "from-file"}))
    path.chmod(0o644)
    key, source = pc.resolve_api_key(pc.load_config(path), path)
    assert key == "from-file" and source == str(path)
    assert "chmod 600" in capsys.readouterr().err


def test_missing_key_explains_both_options(tmp_path):
    path = tmp_path / "c.json"
    with pytest.raises(pc.PodcastError) as e:
        pc.resolve_api_key(pc.load_config(path), path)
    assert "ELEVENLABS_API_KEY" in str(e.value) and str(path) in str(e.value)


def test_config_command_masks_key():
    assert pc.masked_config({"api_key": "sk_x", "a": 1}) == {"api_key": "***", "a": 1}


# ---------------------------------------------------------------- validation


def test_valid_two_speaker_script(tmp_path):
    ep = pc.load_episode(script(tmp_path), cfg())
    assert ep.errors == []
    assert ep.speakers["maya"].voice_id == pc.DEFAULTS["cast"]["host"]["voice_id"]


def test_name_defaults_to_cast_name(tmp_path):
    speakers = {"a": {"role": "host"}, "b": {"role": "cohost", "name": "Bea"}}
    turns = [{"speaker": s, "text": "Hi."} for s in "ab"]
    ep = pc.load_episode(script(tmp_path, turns, speakers), cfg())
    assert ep.speakers["a"].name == pc.DEFAULTS["cast"]["host"]["name"]
    assert ep.speakers["b"].name == "Bea"


def test_three_speakers_with_voice_override(tmp_path):
    speakers = {
        "a": {"role": "host"},
        "b": {"role": "cohost"},
        "c": {"role": "guest", "voice_id": "custom"},
    }
    turns = [{"speaker": s, "text": "Hi."} for s in "abc"]
    ep = pc.load_episode(script(tmp_path, turns, speakers), cfg())
    assert ep.errors == []
    assert ep.speakers["c"].voice_id == "custom"


@pytest.mark.parametrize(
    "speakers,turns,needle",
    [
        ({"a": {"role": "host"}}, [{"speaker": "a", "text": "x"}], "2 or 3"),
        (
            {k: {"role": r} for k, r in zip("abcd", ["host", "cohost", "guest", "host"])},
            [{"speaker": "a", "text": "x"}],
            "2 or 3",
        ),
        (None, [{"speaker": "zed", "text": "x"}], "unknown speaker"),
        (None, [{"speaker": "maya", "text": "  "}], "empty text"),
        (None, [{"speaker": "maya", "text": "Hello"}], "never speaks"),
        ({"a": {"role": "host"}, "b": {"role": "host"}}, None, "used twice"),
        ({"a": {"role": "narrator"}, "b": {"role": "host"}}, None, "role must be"),
        (
            {"a": {"role": "host", "voice_id": "v"}, "b": {"role": "cohost", "voice_id": "v"}},
            None,
            "same voice_id",
        ),
        (
            None,
            [
                {"speaker": "maya", "text": 'Hi <break time="1s"/> there'},
                {"speaker": "tom", "text": "Yo"},
            ],
            "SSML",
        ),
    ],
)
def test_validation_errors(tmp_path, speakers, turns, needle):
    if turns is None and speakers:
        turns = [{"speaker": k, "text": "Hi."} for k in speakers]
    ep = pc.load_episode(script(tmp_path, turns, speakers), cfg())
    assert any(needle in e for e in ep.errors), ep.errors


def test_url_in_text_warns(tmp_path):
    turns = [
        {"speaker": "maya", "text": "See https://example.com"},
        {"speaker": "tom", "text": "Sure."},
    ]
    ep = pc.load_episode(script(tmp_path, turns), cfg())
    assert ep.errors == [] and any("URL" in w for w in ep.warnings)


# ---------------------------------------------------------------- chunking


def long_turns(n, size=300):
    return [
        {"speaker": "maya" if i % 2 == 0 else "tom", "text": f"Line {i}. " + "word " * (size // 5)}
        for i in range(n)
    ]


def test_chunks_fit_limit_and_keep_order(tmp_path):
    ep = pc.load_episode(script(tmp_path, long_turns(40)), cfg())
    chunks = pc.plan_chunks(ep, cfg())
    assert len(chunks) > 1
    assert all(c.chars <= pc.DEFAULTS["chunk_max_chars"] for c in chunks)
    assert [t.text for c in chunks for t in c.turns] == [t.text for t in ep.turns]


def test_oversize_turn_is_split_at_sentences(tmp_path):
    big = " ".join(f"Sentence number {i} is here." for i in range(200))
    turns = [{"speaker": "maya", "text": big}, {"speaker": "tom", "text": "Wow."}]
    ep = pc.load_episode(script(tmp_path, turns), cfg())
    chunks = pc.plan_chunks(ep, cfg())
    parts = [t.text for c in chunks for t in c.turns if t.speaker == "maya"]
    assert len(parts) > 1 and all(p.endswith(".") for p in parts)
    assert " ".join(parts) == big


def test_interruption_stays_with_its_reply(tmp_path):
    turns = long_turns(5, size=340)
    cut = "So the thing about hives is—"
    reply = "—that they swarm, yes!"
    turns += [{"speaker": "tom", "text": cut}, {"speaker": "maya", "text": reply}]
    ep = pc.load_episode(script(tmp_path, turns), cfg())
    # The limit fits the interrupted line but not its reply, forcing a boundary between them.
    limit = sum(len(t["text"]) for t in turns[:-1]) + 5
    chunks = pc.plan_chunks(ep, cfg(chunk_max_chars=limit))
    assert len(chunks) == 2
    assert [t.text for t in chunks[1].turns] == [cut, reply]


def test_new_section_starts_new_chunk_when_full_enough(tmp_path):
    p = script(tmp_path)
    data = json.loads(p.read_text())
    data["sections"] = [
        {"title": "One", "turns": long_turns(4, size=300)},
        {"title": "Two", "turns": long_turns(2, size=100)},
    ]
    p.write_text(json.dumps(data))
    ep = pc.load_episode(p, cfg())
    chunks = pc.plan_chunks(ep, cfg())
    assert {t.section for t in chunks[0].turns} == {0}
    assert {t.section for t in chunks[1].turns} == {1}


def test_hash_changes_with_voice_and_model(tmp_path):
    ep = pc.load_episode(script(tmp_path), cfg())
    base = pc.plan_chunks(ep, cfg())[0].hash
    assert pc.plan_chunks(ep, cfg(model_id="eleven_v3"))[0].hash != base
    other = cfg(cast={"host": {"voice_id": "other"}})
    ep2 = pc.load_episode(ep.path, other)
    assert pc.plan_chunks(ep2, other)[0].hash != base


# ---------------------------------------------------------------- check


def test_check_flags_approval_and_reports_missing_permission(tmp_path):
    ep = pc.load_episode(script(tmp_path, long_turns(60)), cfg())
    api = FakeApi(
        fail={
            (lambda u, b: "subscription" in u): (
                401,
                {},
                json.dumps({"detail": {"message": "missing the permission user_read"}}).encode(),
            )
        }
    )
    report = pc.check_report(ep, cfg(), client(api))
    assert report["needs_approval"] is True
    assert report["quota"] == {"available": False, "reason": "the key lacks User read permission"}
    assert report["requests"] >= 10


def test_check_errors_when_quota_too_small(tmp_path):
    ep = pc.load_episode(script(tmp_path), cfg())
    sub = {"character_count": 99_990, "character_limit": 100_000, "tier": "creator"}
    api = FakeApi(fail={(lambda u, b: "subscription" in u): (200, {}, json.dumps(sub).encode())})
    report = pc.check_report(ep, cfg(), client(api))
    assert any("characters left" in e for e in report["errors"])


# ---------------------------------------------------------------- render


def test_render_stitches_and_resumes(tmp_path):
    ep = pc.load_episode(script(tmp_path, long_turns(30)), cfg())
    api = FakeApi()
    result = pc.render(ep, cfg(), client(api), log=lambda *_: None)
    n = result["requests"]
    assert n >= 4 and result["rendered"] == n
    bodies = [c["body"] for c in api.calls]
    assert "previous_request_ids" not in bodies[0]
    assert bodies[1]["previous_request_ids"] == ["req-1"]
    assert bodies[-1]["previous_request_ids"] == [f"req-{n - 3}", f"req-{n - 2}", f"req-{n - 1}"]
    assert all(b["model_id"] == "eleven_v4" and b["language_code"] == "en" for b in bodies)

    again = pc.render(ep, cfg(), client(api), log=lambda *_: None)
    assert again["rendered"] == 0 and again["reused"] == n
    assert len(api.calls) == n


def test_inserting_a_section_only_renders_new_requests(tmp_path):
    p = script(tmp_path, long_turns(20), seed=5)
    ep = pc.load_episode(p, cfg())
    api = FakeApi()
    first = pc.render(ep, cfg(), client(api), log=lambda *_: None)
    data = json.loads(p.read_text())
    data["sections"].insert(0, {"title": "New open", "turns": long_turns(6, size=200)})
    p.write_text(json.dumps(data))
    ep2 = pc.load_episode(p, cfg())
    before = len(api.calls)
    second = pc.render(ep2, cfg(), client(api), log=lambda *_: None)
    assert second["reused"] == first["requests"]
    assert len(api.calls) - before == second["rendered"] == second["requests"] - first["requests"]


def test_render_disables_stitching_when_rejected(tmp_path):
    ep = pc.load_episode(script(tmp_path, long_turns(20)), cfg())
    rejected = json.dumps({"detail": {"message": "previous_request_ids not supported"}}).encode()
    api = FakeApi(fail={(lambda u, b: b and "previous_request_ids" in b): (422, {}, rejected)})
    result = pc.render(ep, cfg(), client(api), log=lambda *_: None)
    assert result["stitching"] is False
    assert result["rendered"] == result["requests"]
    later = [c["body"] for c in api.calls[2:]]
    assert all("previous_request_ids" not in b for b in later)


def test_render_failure_keeps_finished_chunks_and_hides_key(tmp_path):
    ep = pc.load_episode(script(tmp_path, long_turns(20)), cfg())
    calls = {"n": 0}

    def flaky(u, b):
        calls["n"] += 1
        return calls["n"] == 2

    msg = json.dumps({"detail": {"message": "quota exceeded for sk_secret_key"}}).encode()
    api = FakeApi(fail={flaky: (401, {}, msg)})
    with pytest.raises(pc.ApiError) as e:
        pc.render(ep, cfg(), client(api), log=lambda *_: None)
    assert "sk_secret_key" not in str(e.value)
    state = pc.load_state(ep)
    assert len(state["chunks"]) == 1


def test_retries_on_rate_limit(tmp_path):
    api = FakeApi(fail={(lambda u, b: True): [(429, {"retry-after": "0"}, b""), (503, {}, b"")]})
    resp = client(api).call("GET", "/v1/models")
    assert resp.body.startswith(b"AUDIO") and len(api.calls) == 3


# ---------------------------------------------------------------- music


def test_music_failure_falls_back_to_voice_only(tmp_path):
    ep = pc.load_episode(script(tmp_path), cfg())
    api = FakeApi(fail={(lambda u, b: "/v1/music" in u): (402, {}, b'{"detail":"paid plan"}')})
    logs = []
    assert pc.make_music(ep, cfg(), client(api), log=logs.append) is None
    assert any("no music" in m for m in logs)


def test_music_request_errors_are_not_hidden(tmp_path):
    ep = pc.load_episode(script(tmp_path), cfg())
    bad = json.dumps({"detail": [{"msg": "music_length_ms must be at least 3000"}]}).encode()
    api = FakeApi(fail={(lambda u, b: "/v1/music" in u): (422, {}, bad)})
    with pytest.raises(pc.ApiError, match="music_length_ms"):
        pc.make_music(ep, cfg(), client(api), log=lambda *_: None)


def test_music_disabled_per_episode(tmp_path):
    ep = pc.load_episode(script(tmp_path, music=False), cfg())
    assert pc.make_music(ep, cfg(), client(FakeApi()), log=lambda *_: None) is None


def test_music_is_cached(tmp_path):
    ep = pc.load_episode(script(tmp_path), cfg())
    api = FakeApi()
    first = pc.make_music(ep, cfg(), client(api), log=lambda *_: None)
    second = pc.make_music(ep, cfg(), client(api), log=lambda *_: None)
    assert first == second and len(api.calls) == 1
    assert api.calls[0]["body"]["force_instrumental"] is True


# ---------------------------------------------------------------- mastering


def tone(path, freq, seconds, rate, channels):
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate={rate}",
            "-ac", str(channels), str(path),
        ],
        check=True,
    )  # fmt: skip


def probe(path):
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels",
            "-show_entries", "format=duration", "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    data = json.loads(out)
    s = data["streams"][0]
    return int(s["sample_rate"]), int(s["channels"]), float(data["format"]["duration"])


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
@pytest.mark.parametrize("with_music", [False, True])
def test_master_mixes_mixed_formats(tmp_path, with_music):
    ep = pc.load_episode(script(tmp_path, long_turns(20)), cfg())
    chunks = pc.plan_chunks(ep, cfg())
    state = {"chunks": {}, "stitching_disabled": False}
    rates = [44100, 24000, 22050]
    for c in chunks:
        f = pc.chunk_file(ep, c, cfg())
        f.parent.mkdir(parents=True, exist_ok=True)
        tone(f, 300 + 50 * c.index, 2, rates[c.index % 3], 1)
        state["chunks"][c.hash] = {"file": f.name}
    pc.save_state(ep, state)
    theme = None
    if with_music:
        theme = tmp_path / "theme.mp3"
        tone(theme, 440, 15, 48000, 2)
    result = pc.master(ep, cfg(), theme, log=lambda *_: None)
    rate, channels, seconds = probe(result["episode"])
    assert (rate, channels) == (44100, 2)
    voice = 2 * len(chunks) + 0.25 * (len(chunks) - 1)
    expected = voice + (10 - 1.5 + 12 - 1.0 if with_music else 0)
    assert abs(seconds - expected) < 1.0
    assert Path(result["transcript"]).read_text().startswith("# Bees")
    assert "[" not in Path(result["transcript"]).read_text().split("\n", 3)[3]


def test_master_refuses_unrendered_episode(tmp_path):
    ep = pc.load_episode(script(tmp_path), cfg())
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    with pytest.raises(pc.PodcastError, match="not been rendered"):
        pc.master(ep, cfg(), None, log=lambda *_: None)


def test_cli_check_exit_codes(tmp_path):
    good = script(tmp_path)
    run = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "check", str(good)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["quota"]["reason"] == "no API key"
    bad = script(tmp_path, [{"speaker": "nobody", "text": "x"}])
    run = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "check", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 1
