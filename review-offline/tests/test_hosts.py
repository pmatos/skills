import json
import os
import shutil
import stat
import sys
import time
import uuid
from itertools import pairwise
from pathlib import Path

import pytest
from review_offline import hosts
from review_offline.hosts import (
    HostError,
    HostTimeout,
    ResumeFailed,
    child_env,
    get_host,
    normalize_effort,
    parse_claude,
    parse_codex,
    parse_omp,
)

smoke = pytest.mark.smoke

FAKE_CLI = """\
#!{python}
import json, os, subprocess, sys, time

name = os.path.basename(sys.argv[0])
argv = sys.argv[1:]
stdin = sys.stdin.read()
log = os.environ["FAKE_LOG"]
with open(log, "a") as fh:
    fh.write(json.dumps({{"name": name, "argv": argv, "stdin": stdin,
                         "env": sorted(os.environ)}}) + "\\n")
mode = os.environ.get("FAKE_MODE", "ok")
resume = ("--resume" in argv) or ("-r" in argv) or ("resume" in argv)

if mode == "hang":
    child = subprocess.Popen(["sleep", "60"])
    open(os.environ["FAKE_PIDFILE"], "w").write(str(child.pid))
    time.sleep(60)

if mode == "reject-effort" and any(
    a in argv for a in ("--effort", "--thinking", 'model_reasoning_effort="high"')
):
    msg = "invalid value for reasoning.effort"
    if name == "codex":
        print(json.dumps({{"type": "thread.started", "thread_id": "t"}}))
        print(json.dumps({{"type": "turn.failed", "error": {{"message": msg}}}}))
    else:
        sys.stderr.write(msg + "\\n")
    sys.exit(1)

if resume and mode == "no-session":
    sys.stderr.write("session not found\\n")
    sys.exit(1)

reply = "ECHO:" + stdin
if name == "claude":
    sid = argv[argv.index("--resume") + 1] if resume else argv[argv.index("--session-id") + 1]
    print(json.dumps({{"type": "result", "is_error": False, "result": reply, "session_id": sid}}))
elif name == "codex":
    sid = argv[argv.index("resume") + 1] if resume else "codex-thread-1"
    print(json.dumps({{"type": "thread.started", "thread_id": sid}}))
    print(json.dumps({{"type": "item.completed",
                      "item": {{"type": "agent_message", "text": "working on it"}}}}))
    print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": reply}}}}))
    print(json.dumps({{"type": "turn.completed"}}))
else:
    sid = argv[argv.index("-r") + 1] if resume else "omp-session-1"
    print(json.dumps({{"type": "session", "id": sid, "cwd": os.getcwd()}}))
    print(json.dumps({{"type": "message_end", "message": {{
        "role": "assistant", "stopReason": "stop",
        "content": [{{"type": "thinking", "thinking": "hm"}}, {{"type": "text", "text": reply}}]}}}}))
"""

CLAUDE_JSON = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "The secret word is **ZEBRA**.",
    "session_id": "04c0b1c8-8cf4-4fa2-94e1-a3b704a8ad15",
    "total_cost_usd": 0.01,
}

CODEX_JSONL = "\n".join(
    json.dumps(e)
    for e in [
        {"type": "thread.started", "thread_id": "01a115a9-31da-7ab1-a6da-99d8e85fa14a"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"id": "i0", "type": "agent_message", "text": "Reading."},
        },
        {"type": "item.started", "item": {"id": "i1", "type": "command_execution"}},
        {"type": "item.completed", "item": {"id": "i1", "type": "command_execution"}},
        {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "ZEBRA"}},
        {"type": "turn.completed", "usage": {"input_tokens": 1}},
    ]
)

OMP_JSONL = "\n".join(
    json.dumps(e)
    for e in [
        {"type": "session", "version": 3, "id": "01a115a8-5493-73ff-89db-d9143e0bed09"},
        {"type": "agent_start"},
        {
            "type": "message_end",
            "message": {"role": "user", "content": [{"type": "text", "text": "q"}]},
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "toolUse",
                "content": [{"type": "text", "text": "let me look"}],
            },
        },
        {"type": "message_end", "message": {"role": "toolResult", "content": "x"}},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "stop",
                "content": [
                    {"type": "thinking", "thinking": "..."},
                    {"type": "text", "text": "ZEBRA"},
                ],
            },
        },
        {"type": "agent_end"},
    ]
)


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in hosts.HOSTS:
        path = bin_dir / name
        path.write_text(FAKE_CLI.format(python=sys.executable))
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_PIDFILE", str(tmp_path / "pid"))
    monkeypatch.setenv("REVIEW_OFFLINE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("FAKE_MODE", raising=False)

    def calls():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    return calls


def build(host_name, prompt="review this", **kwargs):
    kwargs.setdefault("support_dir", Path("/state"))
    kwargs.setdefault("cwd", "/work/tree")
    return get_host(host_name, kwargs.pop("model", None)).build_command(prompt, **kwargs)


def pairs(argv):
    return list(pairwise(argv))


def test_get_host_rejects_unknown_and_missing():
    with pytest.raises(ValueError, match="unknown host 'gemini'"):
        get_host("gemini")
    with pytest.raises(ValueError, match="no host given"):
        get_host("")
    assert [get_host(n).name for n in hosts.HOSTS] == ["claude", "codex", "omp"]


@pytest.mark.parametrize("session", [None, "sess-1"])
def test_claude_command_is_read_only_and_isolated(session):
    cmd = build("claude", session=session, readonly_dirs=["/data/a"])
    assert ("--tools", "Read,Grep,Glob") in pairs(cmd.argv)
    assert ("--setting-sources", "") in pairs(cmd.argv)
    assert ("--permission-mode", "dontAsk") in pairs(cmd.argv)
    assert ("--add-dir", "/data/a") in pairs(cmd.argv)
    for flag in ("--strict-mcp-config", "--restricted", "--disable-slash-commands", "-p"):
        assert flag in cmd.argv
    assert not {"Bash", "Edit", "Write"} & set(",".join(cmd.argv).split(","))
    if session:
        assert ("--resume", "sess-1") in pairs(cmd.argv)
        assert "--session-id" not in cmd.argv
    else:
        assert "--session-id" in cmd.argv
        uuid.UUID(cmd.argv[cmd.argv.index("--session-id") + 1])


@pytest.mark.parametrize("session", [None, "thread-1"])
def test_codex_command_is_read_only_and_isolated(session):
    cmd = build("codex", session=session)
    argv = cmd.argv
    assert argv[:2] == ("codex", "exec")
    assert ("-c", 'sandbox_mode="read-only"') in pairs(argv)
    assert ("--sandbox", "read-only") in pairs(argv) or session
    for flag in ("--ignore-user-config", "--ignore-rules", "--json", "--skip-git-repo-check"):
        assert flag in argv
    for feature in ("apps", "plugins", "hooks", "memories", "multi_agent"):
        assert ("-c", f"features.{feature}=false") in pairs(argv)
    assert ("-c", 'web_search="disabled"') in pairs(argv)
    assert "danger-full-access" not in " ".join(argv)
    assert argv[-1] == "-"
    assert (argv[2:4] == ("resume", "thread-1")) == bool(session)


def test_omp_command_is_read_only_and_isolated(tmp_path):
    cmd = build("omp", session="s1", support_dir=tmp_path, readonly_dirs=["/x"])
    argv = cmd.argv
    assert ("--tools", "read,grep,glob") in pairs(argv)
    assert ("--config", str(tmp_path / hosts.OMP_OVERLAY_NAME)) in pairs(argv)
    assert ("-r", "s1") in pairs(argv)
    assert ("--add-dir", "/x") in pairs(argv)
    for flag in ("--no-extensions", "--no-skills", "--no-rules", "--no-lsp", "-p"):
        assert flag in argv
    assert ("--mode", "json") in pairs(argv)
    assert "enableProjectConfig: false" in hosts.OMP_OVERLAY
    for needle in ('backend: "off"', "fetch:\n  enabled: false", "advisor:\n  enabled: false"):
        assert needle in hosts.OMP_OVERLAY


def test_omp_sessions_are_keyed_by_cwd(tmp_path):
    a = build("omp", support_dir=tmp_path, cwd="/work/a").argv
    b = build("omp", support_dir=tmp_path, cwd="/work/b").argv
    again = build("omp", support_dir=tmp_path, cwd="/work/a").argv

    def session_dir(argv):
        return argv[argv.index("--session-dir") + 1]

    assert session_dir(a) != session_dir(b)
    assert session_dir(a) == session_dir(again)


@pytest.mark.parametrize("name", hosts.HOSTS)
def test_prompt_goes_through_stdin_never_argv(name):
    prompt = "--dangerously-skip-permissions -rf"
    cmd = build(name, prompt=prompt)
    assert cmd.stdin == prompt
    assert not any(prompt in arg or arg == "--dangerously-skip-permissions" for arg in cmd.argv)


@pytest.mark.parametrize(
    ("name", "flag"), [("claude", "--model"), ("codex", "-m"), ("omp", "--model")]
)
def test_model_is_passed_only_when_given(name, flag):
    assert (flag, "m-1") in pairs(build(name, model="m-1").argv)
    assert flag not in build(name).argv


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("claude", ("--effort", "xhigh")),
        ("codex", ("-c", 'model_reasoning_effort="xhigh"')),
        ("omp", ("--thinking", "xhigh")),
    ],
)
def test_effort_maps_to_native_option(name, expected):
    assert expected in pairs(build(name, effort="xhigh").argv)
    assert not any("effort" in a or a == "--thinking" for a in build(name, effort=None).argv)


def test_effort_normalisation():
    assert normalize_effort("max") == ("max", None)
    assert normalize_effort("ultra") == ("max", None)
    assert normalize_effort("minimal") == ("low", None)
    assert normalize_effort(None) == (None, None)
    level, note = normalize_effort("turbo")
    assert level == "high"
    assert "turbo" in note


def test_child_env_drops_harness_variables():
    base = {
        "PATH": "/bin",
        "HOME": "/h",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "x",
        "CLAUDE_CODE_MESSAGING_SOCKET": "s",
        "CLAUDE_CODE_MESSAGING_TOKEN": "t",
        "CLAUDE_CODE_CHILD_SESSION": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "CODEX_COMPANION_SESSION_ID": "c",
        "CODEX_HOME": "/keep",
        "CLAUDE_CODE_OAUTH_TOKEN": "keep-auth",
    }
    env = child_env(base)
    assert env == {
        "PATH": "/bin",
        "HOME": "/h",
        "CODEX_HOME": "/keep",
        "CLAUDE_CODE_OAUTH_TOKEN": "keep-auth",
    }
    assert build("claude", env=base).env == env


def test_parse_claude_json_array_and_stream():
    assert parse_claude(json.dumps(CLAUDE_JSON)) == (
        CLAUDE_JSON["session_id"],
        CLAUDE_JSON["result"],
    )
    init = {"type": "system", "subtype": "init", "tools": ["Glob", "Grep", "Read"]}
    assert parse_claude(json.dumps([init, CLAUDE_JSON]))[1] == CLAUDE_JSON["result"]
    stream = "\n".join(json.dumps(e) for e in [init, {"type": "assistant"}, CLAUDE_JSON])
    assert parse_claude(stream)[0] == CLAUDE_JSON["session_id"]


def test_parse_claude_errors():
    with pytest.raises(HostError, match="no result"):
        parse_claude("not json at all")
    with pytest.raises(HostError, match="reported an error"):
        parse_claude(json.dumps({**CLAUDE_JSON, "is_error": True, "result": "API Error"}))


def test_parse_codex_takes_last_agent_message():
    assert parse_codex(CODEX_JSONL) == ("01a115a9-31da-7ab1-a6da-99d8e85fa14a", "ZEBRA")
    noisy = "Reading additional input from stdin...\n" + CODEX_JSONL
    assert parse_codex(noisy)[1] == "ZEBRA"


def test_parse_codex_failure():
    failed = "\n".join(
        json.dumps(e)
        for e in [
            {"type": "thread.started", "thread_id": "t"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "partial"}},
            {"type": "turn.failed", "error": {"message": "boom"}},
        ]
    )
    with pytest.raises(HostError, match="boom"):
        parse_codex(failed)
    with pytest.raises(HostError):
        parse_codex('{"type":"thread.started","thread_id":"t"}')


def test_parse_omp_takes_last_assistant_text():
    assert parse_omp(OMP_JSONL) == ("01a115a8-5493-73ff-89db-d9143e0bed09", "ZEBRA")


def test_parse_omp_errors():
    bad = OMP_JSONL.replace('"stopReason": "stop"', '"stopReason": "error"')
    with pytest.raises(HostError, match="error"):
        parse_omp(bad)
    with pytest.raises(HostError):
        parse_omp('{"type":"agent_start"}')


@pytest.mark.parametrize("name", hosts.HOSTS)
def test_run_new_session_then_resume(fake_bin, tmp_path, name):
    host = get_host(name, "some-model")
    first = host.run("-- leading dashes", cwd=tmp_path, effort="high")
    assert first.text == "ECHO:-- leading dashes"
    assert first.session
    assert first.notes == []
    second = host.run("again", cwd=tmp_path, session=first.session)
    assert second.session == first.session
    calls = fake_bin()
    assert calls[0]["stdin"] == "-- leading dashes"
    assert "CLAUDECODE" not in calls[0]["env"]


def test_run_notes_unpinned_model(fake_bin, tmp_path):
    result = get_host("claude").run("hi", cwd=tmp_path)
    assert any("model not pinned" in n for n in result.notes)


@pytest.mark.parametrize("name", hosts.HOSTS)
def test_effort_rejection_retries_once_without_effort(fake_bin, tmp_path, monkeypatch, name):
    monkeypatch.setenv("FAKE_MODE", "reject-effort")
    result = get_host(name, "m").run("hi", cwd=tmp_path, effort="high")
    assert result.text == "ECHO:hi"
    assert f"effort ignored by {name}" in result.notes
    calls = fake_bin()
    assert len(calls) == 2
    native = {"--effort", "--thinking", 'model_reasoning_effort="high"'}
    assert native & set(calls[0]["argv"])
    assert not native & set(calls[1]["argv"])


@pytest.mark.parametrize("name", hosts.HOSTS)
def test_failed_resume_raises_resume_failed(fake_bin, tmp_path, monkeypatch, name):
    monkeypatch.setenv("FAKE_MODE", "no-session")
    with pytest.raises(ResumeFailed):
        get_host(name, "m").run("hi", cwd=tmp_path, session="gone")


def test_missing_binary_is_a_host_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("REVIEW_OFFLINE_STATE_DIR", str(tmp_path / "state"))
    with pytest.raises(HostError, match="not found on PATH"):
        get_host("codex", "m").run("hi", cwd=tmp_path)


def test_timeout_kills_the_whole_process_group(fake_bin, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    started = time.monotonic()
    with pytest.raises(HostTimeout):
        get_host("claude", "m").run("hi", cwd=tmp_path, timeout=1.5)
    assert time.monotonic() - started < 20
    grandchild = int((tmp_path / "pid").read_text())
    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild survived the timeout")


def smoke_enabled(name):
    return os.environ.get("REVIEW_OFFLINE_SMOKE") == "1" and shutil.which(name) is not None


def smoke_host(name):
    if not smoke_enabled(name):
        pytest.skip(f"set REVIEW_OFFLINE_SMOKE=1 and install {name} to run")
    return get_host(name, os.environ.get(f"REVIEW_OFFLINE_SMOKE_MODEL_{name.upper()}"))


@smoke
@pytest.mark.parametrize("name", hosts.HOSTS)
def test_smoke_two_turn_memory(name, tmp_path, monkeypatch):
    host = smoke_host(name)
    monkeypatch.setenv("REVIEW_OFFLINE_STATE_DIR", str(tmp_path / "state"))
    work = tmp_path / "work"
    work.mkdir()
    word = f"kiwi{uuid.uuid4().hex[:8]}"
    (work / "secret.txt").write_text(f"the codeword is {word}\n")
    first = host.run(
        "Read secret.txt in the current directory and reply with only the codeword.",
        cwd=work,
        effort="low",
        timeout=300,
    )
    assert word in first.text
    second = host.run(
        "Without reading any file again: which codeword did you just find? Reply with only it.",
        cwd=work,
        session=first.session,
        effort="low",
        timeout=300,
    )
    assert word in second.text
    assert second.session == first.session


@smoke
def test_smoke_claude_init_lists_no_mcp_servers(tmp_path):
    smoke_host("claude")
    marker = tmp_path / "MCP_STARTED"
    server = tmp_path / "server.sh"
    server.write_text(f"#!/bin/sh\ntouch {marker}\nexec sleep 30\n")
    server.chmod(0o755)
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"evil": {"command": str(server), "args": []}}})
    )
    cmd = build("claude", prompt="Reply with the word PONG.", effort="low", cwd=tmp_path)
    argv = list(cmd.argv)
    argv[argv.index("json")] = "stream-json"
    argv.append("--verbose")
    code, out, _ = hosts._spawn(hosts.Command(tuple(argv), cmd.env, cmd.stdin), tmp_path, 300)
    assert code == 0
    init = next(
        e for e in hosts._jsonl(out) if e.get("type") == "system" and e.get("subtype") == "init"
    )
    assert sorted(init["tools"]) == ["Glob", "Grep", "Read"]
    assert init["mcp_servers"] == []
    assert not marker.exists()
