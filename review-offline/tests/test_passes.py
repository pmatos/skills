import json
import threading
from pathlib import Path

import pytest
from review_offline import passes
from review_offline.hosts import HostResult, ResumeFailed
from review_offline.store import Store

CHANGESET = {
    "target": "HEAD",
    "title": "T",
    "slug": "head-abc1234",
    "base": {"sha": "a" * 40, "ref": "main"},
    "head": {"sha": "b" * 40, "ref": "x"},
    "root": "/repo",
    "files": [
        {
            "path": "a.py",
            "old_path": None,
            "status": "modified",
            "binary": False,
            "additions": 2,
            "deletions": 0,
            "collapsed": False,
            "collapse_reason": None,
            "hunks": [
                {
                    "header": "@@ -1,2 +1,4 @@",
                    "old_start": 1,
                    "new_start": 1,
                    "lines": [
                        {"t": "ctx", "o": 1, "n": 1, "text": "a"},
                        {"t": "add", "o": None, "n": 2, "text": "b"},
                        {"t": "add", "o": None, "n": 3, "text": "c"},
                        {"t": "ctx", "o": 2, "n": 4, "text": "d"},
                    ],
                }
            ],
        }
    ],
}


def fenced(payload):
    return "reasoning\n```json\n" + json.dumps(payload) + "\n```\n"


def finding(angle, start=2, end=2, label="suggestion", path="a.py"):
    return {
        "path": path,
        "side": "new",
        "start": start,
        "end": end,
        "label": label,
        "body": f"{angle} body",
        "suggestion": None,
        "category": angle,
        "verdict": "PLAUSIBLE",
    }


class FakeHost:
    def __init__(self, script):
        self.script = script
        self.calls = []
        self.lock = threading.Lock()

    def run(self, prompt, *, cwd, session=None, effort="high", readonly_dirs=(), timeout=600):
        with self.lock:
            self.calls.append({"prompt": prompt, "session": session, "effort": effort})
        text = self.script(prompt, session)
        return HostResult(text=text, session="s-" + str(len(self.calls)), notes=["n"])


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / ".reviews", CHANGESET["slug"], CHANGESET)


def make(host, store, tmp_path, effort="high"):
    notes = []
    p = passes.Passes(host, store, CHANGESET, tmp_path, effort, on_note=notes.append)
    p.notes = notes
    return p


def run_all(p):
    p.start()
    for t in p._threads:
        t.join(10)


def test_angles_file_covers_every_angle_id():
    angles = passes.load_angles()
    for angle in (*passes.CORRECTNESS, *passes.CLEANUP, "verify-recall", "verify-precise", "sweep"):
        assert angles[angle].strip(), angle


def test_extract_json_block_takes_last_block_and_reports_errors():
    text = "```json\n[1]\n```\nlater\n```json\n[2]\n```"
    assert passes.extract_json_block(text) == [2]
    with pytest.raises(passes.StoreError, match="no fenced"):
        passes.extract_json_block("nothing")
    with pytest.raises(passes.StoreError, match="not valid JSON"):
        passes.extract_json_block("```json\n[oops\n```")


def test_dedupe_keeps_most_severe_of_overlapping():
    a = finding("x", 2, 3, "nit")
    b = finding("y", 3, 4, "blocking")
    c = finding("z", 9, 9)
    kept = passes.dedupe([a, b, c])
    assert [k["label"] for k in kept] == ["blocking", "suggestion"]


def test_full_high_effort_run_streams_verified_findings(store, tmp_path):
    def script(prompt, session):
        if "You are a verifier" in prompt:
            data = json.loads(prompt.split("```json\n")[1].split("\n```")[0])
            return fenced(
                [
                    {"index": c["index"], "verdict": "REFUTED" if c["start"] == 3 else "CONFIRMED"}
                    for c in data
                ]
            )
        angle = prompt.split("Your angle: ")[1].split("\n")[0]
        if angle == "correctness-scan":
            return fenced([finding(angle, 2, 2, "blocking"), finding(angle, 3, 3)])
        if angle == "cleanup-reuse":
            return fenced([finding(angle, 99, 99), finding(angle, 4, 4, "nit")])
        return fenced([])

    host = FakeHost(script)
    p = make(host, store, tmp_path)
    run_all(p)
    snap = store.snapshot()
    assert snap["passes"] == {"correctness": "done", "cleanup": "done"}
    bodies = sorted(c["body"] for c in snap["comments"])
    assert any("correctness-scan" in b for b in bodies)
    assert not any("99" in b for b in bodies)
    lines = sorted((c["anchor"]["start"], c["verdict"]) for c in snap["comments"])
    assert lines == [(2, "CONFIRMED"), (4, "CONFIRMED")]
    assert all(c["origin"] == "agent" and c["status"] == "pending" for c in snap["comments"])
    assert {c["effort"] for c in host.calls} == {"high"}
    assert any("untrusted" in c["prompt"] for c in host.calls)


def test_finder_retries_once_with_the_exact_error(store, tmp_path):
    seen = {}

    def script(prompt, session):
        if "Your angle: correctness-scan" in prompt:
            return "no block here"
        if "previous answer was rejected" in prompt:
            seen["retry"] = prompt
            return fenced([])
        return fenced([])

    p = make(FakeHost(script), store, tmp_path, effort="low")
    run_all(p)
    assert "no fenced" in seen["retry"]
    assert store.snapshot()["passes"]["correctness"] == "done"


def test_all_angles_failing_marks_pass_failed(store, tmp_path):
    def script(prompt, session):
        raise RuntimeError("host down")

    p = make(FakeHost(script), store, tmp_path, effort="low")
    run_all(p)
    assert store.snapshot()["passes"] == {"correctness": "failed", "cleanup": "failed"}
    assert any("host down" in n for n in p.notes)


def test_xhigh_runs_sweep(store, tmp_path):
    def script(prompt, session):
        if "You are a verifier" in prompt:
            return fenced([])
        if "Already found" in prompt:
            return fenced([finding("sweep", 3, 3, "blocking")])
        return fenced([])

    run_all(make(FakeHost(script), store, tmp_path, effort="xhigh"))
    cats = [c["sources"] for c in store.snapshot()["comments"]]
    assert cats and store.snapshot()["passes"]["correctness"] == "done"


def test_asker_resumes_then_replays_when_resume_fails(tmp_path):
    calls = []

    class H:
        def run(self, prompt, *, cwd, session=None, effort="high", readonly_dirs=(), timeout=600):
            calls.append((session, prompt))
            if session:
                raise ResumeFailed("gone")
            return HostResult(text="fresh", session="s2")

    asker = passes.Asker(H(), CHANGESET, Path(tmp_path))
    thread = {
        "id": "t1",
        "session": "old",
        "anchor": {"scope": "line", "path": "a.py", "side": "new", "start": 2, "end": 3},
        "messages": [
            {"role": "user", "text": "first"},
            {"role": "agent", "text": "answer"},
            {"role": "user", "text": "second"},
        ],
    }
    text, session = asker.ask(thread, "second")
    assert (text, session) == ("fresh", "s2")
    assert calls[0][0] == "old" and calls[1][0] is None
    assert "Conversation so far" in calls[1][1] and "answer" in calls[1][1]
    assert "```\nb\nc\n```" in calls[1][1]


def test_resume_skips_passes_already_done(store, tmp_path):
    store.set_pass_status("correctness", "done")
    seen = []

    def script(prompt, session):
        seen.append(prompt)
        return fenced([])

    run_all(make(FakeHost(script), store, tmp_path, effort="low"))
    assert all("Your angle: correctness" not in p for p in seen)
    assert any("Your angle: cleanup" in p for p in seen)
    assert store.snapshot()["passes"] == {"correctness": "done", "cleanup": "done"}


def test_resume_reruns_passes_when_head_moved(store, tmp_path, monkeypatch):
    store.set_pass_status("correctness", "done")
    store.set_pass_status("cleanup", "done")
    monkeypatch.setattr(type(store), "head_moved", property(lambda self: True))
    seen = []

    def script(prompt, session):
        seen.append(prompt)
        return fenced([])

    run_all(make(FakeHost(script), store, tmp_path, effort="low"))
    assert any("Your angle: correctness" in p for p in seen)
