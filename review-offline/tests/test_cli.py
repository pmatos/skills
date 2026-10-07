import http.client
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_offline.py"
GRAPH = {
    "schemaVersion": "1",
    "title": "g",
    "summary": "s",
    "lanes": [{"id": "l", "label": "L", "order": 0}],
    "nodes": [
        {"id": "a", "label": "a", "kind": "module", "delta": "added", "lane": "l", "summary": "a"},
        {
            "id": "b",
            "label": "b",
            "kind": "module",
            "delta": "unchanged",
            "lane": "l",
            "summary": "b",
        },
    ],
}


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def prepared(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "a.py").write_text("x = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")
    (repo / "a.py").write_text("x = 1\ny = 2\n")
    run_dir = tmp_path / "run"
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "prepare", "--repo", str(repo), "--run-dir", str(run_dir)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )
    info = json.loads(out.stdout)
    (run_dir / "graph.json").write_text(json.dumps(GRAPH))
    fake = tmp_path / "bin"
    fake.mkdir()
    claude = fake / "claude"
    claude.write_text("#!/bin/sh\ncat >/dev/null\nsleep 30\n")
    claude.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}
    env["REVIEW_OFFLINE_STATE_DIR"] = str(tmp_path / "state")
    return repo, run_dir, info, env


def start(run_dir, env):
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "serve", str(run_dir), "--host", "claude"],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    line = proc.stdout.readline().strip()
    assert line.startswith("LISTENING http://127.0.0.1:"), line
    url = line.split(" ", 1)[1]
    host, token = url.split("#t=")
    port = int(host.rsplit(":", 1)[1].rstrip("/"))
    return proc, port, token


def api(port, token, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(
        method,
        path,
        body=json.dumps(body) if body is not None else None,
        headers={"X-Review-Token": token, "Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read() or b"{}")


def test_prepare_wrote_run_dir(prepared):
    _, run_dir, info, _ = prepared
    assert info["files"][0]["path"] == "a.py"
    assert (run_dir / "changeset.json").exists() and (run_dir / "prefetch" / "diff.patch").exists()


def test_finish_ends_with_complete_line_and_markdown(prepared):
    repo, run_dir, _info, env = prepared
    proc, port, token = start(run_dir, env)
    status, _ = api(port, token, "POST", "/api/comments", {"anchor": {"scope": "pr"}, "body": "ok"})
    assert status == 201
    status, data = api(port, token, "POST", "/api/finish", {})
    assert status == 200
    rest = proc.stdout.read()
    assert proc.wait(timeout=10) == 0
    assert rest.strip().splitlines()[-1] == f"REVIEW-COMPLETE {data['path']}"
    assert Path(data["path"]).read_text().count("ok") >= 1
    assert (repo / ".reviews" / ".gitignore").read_text().strip() == "*"


def test_sigterm_suspends_instead_of_hanging(prepared):
    _, run_dir, _, env = prepared
    proc, _, _ = start(run_dir, env)
    proc.send_signal(signal.SIGTERM)
    rest = proc.stdout.read()
    assert proc.wait(timeout=10) == 0
    assert rest.strip().splitlines()[-1].startswith("REVIEW-SUSPENDED stopped ")


def test_invalid_graph_reports_error_line(prepared):
    _, run_dir, _, env = prepared
    (run_dir / "graph.json").write_text('{"schemaVersion": "9"}')
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "serve", str(run_dir), "--host", "claude"],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    out = proc.stdout.read()
    assert proc.wait(timeout=10) == 1
    assert out.startswith("REVIEW-ERROR ") and "graph.json is invalid" in out


def prepare_json(repo, run_dir, *extra, env=None):
    out = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            *extra,
            "--repo",
            str(repo),
            "--run-dir",
            str(run_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return out


def test_prepare_with_no_changes_fails_clearly(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "a.py").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")
    out = prepare_json(repo, tmp_path / "run")
    assert out.returncode == 1
    assert "no changes found" in out.stderr


def test_prepare_reports_resume_and_reuses_graph_only_for_same_diff(prepared):
    repo, run_dir, info, _ = prepared
    assert info["resumed"] is False and info["graph_reusable"] is False
    (run_dir / "graph.json").write_text(json.dumps(GRAPH))
    again = json.loads(prepare_json(repo, run_dir).stdout)
    assert again["graph_reusable"] is True
    (repo / "a.py").write_text("x = 1\ny = 3\n")
    changed = json.loads(prepare_json(repo, run_dir).stdout)
    assert changed["graph_reusable"] is False
    assert not (run_dir / "graph.json").exists()


def test_prepare_fresh_sets_state_aside(prepared):
    repo, run_dir, info, _ = prepared
    state = repo / ".reviews" / f"{info['slug']}.state.json"
    state.parent.mkdir(exist_ok=True)
    state.write_text("{}")
    assert json.loads(prepare_json(repo, run_dir).stdout)["resumed"] is True
    fresh = json.loads(prepare_json(repo, run_dir, "--fresh").stdout)
    assert fresh["resumed"] is False
    assert list(state.parent.glob(f"{state.name}.*.bak"))


def test_default_run_dirs_differ_per_repo(tmp_path):
    from review_offline.cli import _run_dir_for

    assert _run_dir_for("pr-1", tmp_path / "a") != _run_dir_for("pr-1", tmp_path / "b")


def test_prepare_from_a_subdirectory_uses_the_repo_toplevel(prepared):
    repo, run_dir, _info, _ = prepared
    sub = repo / "pkg"
    sub.mkdir()
    out = prepare_json(sub, run_dir)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["resumed"] is False
    assert (repo / ".reviews").parent == repo
    assert not (sub / ".reviews").exists()


def test_graph_error_is_a_single_review_error_line(prepared):
    _, run_dir, _, env = prepared
    bad = json.loads(json.dumps(GRAPH))
    bad["nodes"][0]["lane"] = "nope"
    bad["nodes"][1]["lane"] = "nope2"
    (run_dir / "graph.json").write_text(json.dumps(bad))
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "serve", str(run_dir), "--host", "claude"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    lines = proc.stdout.strip().splitlines()
    assert proc.returncode == 1 and len(lines) == 1
    assert lines[0].startswith("REVIEW-ERROR ") and "nodes[0].lane" in lines[0]


def test_second_server_for_the_same_run_is_refused(prepared):
    _, run_dir, _, env = prepared
    proc, _, _ = start(run_dir, env)
    try:
        second = subprocess.run(
            [sys.executable, str(SCRIPT), "serve", str(run_dir), "--host", "claude"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert second.returncode == 1
        assert second.stdout.startswith("REVIEW-ERROR a review server for this run is already")
        assert (run_dir / "serve.lock").exists()
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.stdout.read()
        proc.wait(timeout=10)
    assert not (run_dir / "serve.lock").exists()
