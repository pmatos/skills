import http.client
import json
import threading
import time
from pathlib import Path

import pytest
from review_offline import server as server_mod
from review_offline.server import ReviewServer
from review_offline.store import Store

CHANGESET = {
    "target": "HEAD",
    "title": "T",
    "slug": "head-abc1234",
    "base": {"sha": "a" * 40, "ref": "main"},
    "head": {"sha": "b" * 40, "ref": "x"},
    "root": ".",
    "files": [
        {
            "path": "a.py",
            "old_path": None,
            "status": "modified",
            "binary": False,
            "additions": 1,
            "deletions": 0,
            "collapsed": False,
            "collapse_reason": None,
            "hunks": [
                {
                    "header": "@@ -1 +1,2 @@",
                    "old_start": 1,
                    "new_start": 1,
                    "lines": [
                        {"t": "ctx", "o": 1, "n": 1, "text": "x = 1"},
                        {"t": "add", "o": None, "n": 2, "text": "y = 2"},
                    ],
                }
            ],
        }
    ],
}
GRAPH = {"schemaVersion": "1", "title": "g", "summary": "s", "lanes": [], "nodes": []}


class FakeService:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.asked = []
        self.fail = False

    def start_passes(self):
        self.started = True

    def ask(self, thread, text):
        self.asked.append((thread["id"], text))
        if self.fail:
            raise RuntimeError("boom")
        return f"answer to {text}", "sess-1"

    def shutdown(self):
        self.stopped = True


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server_mod, "LONG_POLL_SECONDS", 0.3)
    store = Store.open(tmp_path / ".reviews", CHANGESET["slug"], CHANGESET)
    svc = FakeService()
    review = ReviewServer(
        store=store,
        changeset=CHANGESET,
        graph=GRAPH,
        reviews_dir=tmp_path / ".reviews",
        service=svc,
        host="claude",
        effort="high",
    )
    review.svc = svc
    result = {}
    thread = threading.Thread(target=lambda: result.update(o=review.serve()), daemon=True)
    thread.start()
    review.result = result
    review.thread = thread
    yield review
    if review.outcome.kind == "running":
        review.stop()
    thread.join(timeout=5)


def call(app, method, path, body=None, headers=None, token=True, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=5)
    hdrs = {"Host": host or f"127.0.0.1:{app.port}"}
    if token:
        hdrs["X-Review-Token"] = app.token
    hdrs.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body)
        hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp, raw


def jcall(app, *args, **kwargs):
    resp, raw = call(app, *args, **kwargs)
    return resp.status, json.loads(raw or b"{}")


def test_shell_served_without_token_and_without_review_data(app):
    resp, raw = call(app, "GET", "/", token=False)
    assert resp.status == 200
    assert b"htmPreact" in raw
    assert b"x = 1" not in raw
    assert "script-src 'unsafe-inline'" in resp.getheader("Content-Security-Policy")
    assert resp.getheader("Cache-Control") == "no-store"


def test_api_requires_token(app):
    assert jcall(app, "GET", "/api/bootstrap", token=False)[0] == 403
    assert jcall(app, "GET", "/api/bootstrap", headers={"X-Review-Token": "nope"})[0] == 403


def test_wrong_host_rejected_even_with_token(app):
    assert jcall(app, "GET", "/api/bootstrap", host="evil.example:80")[0] == 403
    assert call(app, "GET", "/", token=False, host="evil.example:80")[0].status == 403


def test_foreign_origin_rejected_matching_origin_allowed(app):
    status, _ = jcall(app, "GET", "/api/bootstrap", headers={"Origin": "http://evil.example"})
    assert status == 403
    ok = jcall(app, "GET", "/api/bootstrap", headers={"Origin": f"http://127.0.0.1:{app.port}"})
    assert ok[0] == 200


def test_bootstrap_shape(app):
    status, data = jcall(app, "GET", "/api/bootstrap")
    assert status == 200
    assert data["host"] == "claude" and data["effort"] == "high"
    assert data["changeset"]["slug"] == CHANGESET["slug"]
    assert data["state"]["comments"] == [] and data["pending_threads"] == []
    assert app.svc.started


def test_comment_crud(app):
    anchor = {"scope": "line", "path": "a.py", "side": "new", "start": 2, "end": 2}
    status, comment = jcall(
        app,
        "POST",
        "/api/comments",
        {"anchor": anchor, "body": "hi", "label": "nit", "suggestion": None},
    )
    assert status == 201 and comment["origin"] == "user" and comment["status"] == "accepted"
    status, patched = jcall(app, "PATCH", f"/api/comments/{comment['id']}", {"body": "yo"})
    assert status == 200 and patched["body"] == "yo"
    assert jcall(app, "DELETE", f"/api/comments/{comment['id']}")[0] == 200
    assert jcall(app, "PATCH", "/api/comments/c999", {"body": "x"})[0] == 404


def test_bad_input_is_400_not_500(app):
    assert jcall(app, "POST", "/api/comments", {"anchor": {"scope": "nope"}, "body": "x"})[0] == 400
    resp, _ = call(app, "POST", "/api/comments", body=None)
    assert resp.status == 400


def test_body_size_limit(app):
    status, _ = jcall(app, "PUT", "/api/summary", {"text": "x" * 1_100_000})
    assert status == 400


def test_negative_content_length_is_rejected(app):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=5)
    conn.request(
        "PUT",
        "/api/summary",
        body="{}",
        headers={
            "Host": f"127.0.0.1:{app.port}",
            "X-Review-Token": app.token,
            "Content-Length": "-1",
        },
    )
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    assert resp.status == 400
    assert b"invalid Content-Length" in raw


def test_events_long_poll_wakes(app):
    _, snap = jcall(app, "GET", "/api/snapshot")
    since = snap["state"]["events"]
    got = {}

    def poll():
        got["r"] = jcall(app, "GET", f"/api/events?since={since}")

    t = threading.Thread(target=poll)
    t.start()
    time.sleep(0.05)
    jcall(app, "PUT", "/api/summary", {"text": "hello"})
    t.join(5)
    status, data = got["r"]
    assert status == 200 and data["events"] and data["last"] > since


def test_ask_flow_and_pending_tracking(app):
    anchor = {"scope": "line", "path": "a.py", "side": "new", "start": 1, "end": 1}
    status, data = jcall(app, "POST", "/api/ask", {"anchor": anchor, "text": "why?"})
    assert status == 202
    tid = data["thread_id"]
    for _ in range(100):
        _, snap = jcall(app, "GET", "/api/snapshot")
        thread = next(t for t in snap["state"]["threads"] if t["id"] == tid)
        if len(thread["messages"]) == 2 and tid not in snap["pending_threads"]:
            break
        time.sleep(0.02)
    assert [m["role"] for m in thread["messages"]] == ["user", "agent"]
    assert thread["messages"][1]["text"] == "answer to why?"
    status, _ = jcall(app, "POST", "/api/ask", {"anchor": anchor, "text": "more", "thread_id": tid})
    assert status == 202


def test_rapid_double_ask_answers_each_question_in_order(app):
    anchor = {"scope": "line", "path": "a.py", "side": "new", "start": 1, "end": 1}
    _, first = jcall(app, "POST", "/api/ask", {"anchor": anchor, "text": "why?"})
    tid = first["thread_id"]
    _, second = jcall(
        app, "POST", "/api/ask", {"anchor": anchor, "text": "and now?", "thread_id": tid}
    )
    assert second["thread_id"] == tid
    for _ in range(200):
        _, snap = jcall(app, "GET", "/api/snapshot")
        if tid not in snap["pending_threads"]:
            break
        time.sleep(0.02)
    thread = next(t for t in snap["state"]["threads"] if t["id"] == tid)
    assert [m["role"] for m in thread["messages"]] == ["user", "agent", "user", "agent"]
    assert [m["text"] for m in thread["messages"]] == [
        "why?",
        "answer to why?",
        "and now?",
        "answer to and now?",
    ]


def test_ask_failure_is_reported_in_thread(app):
    app.svc.fail = True
    anchor = {"scope": "pr"}
    _, data = jcall(app, "POST", "/api/ask", {"anchor": anchor, "text": "?"})
    for _ in range(100):
        _, snap = jcall(app, "GET", "/api/snapshot")
        if data["thread_id"] not in snap["pending_threads"]:
            break
        time.sleep(0.02)
    thread = snap["state"]["threads"][0]
    assert "failed" in thread["messages"][-1]["text"]


def test_finish_writes_markdown_and_stops(app):
    anchor = {"scope": "pr"}
    jcall(app, "POST", "/api/comments", {"anchor": anchor, "body": "ship it", "label": "nit"})
    status, data = jcall(app, "POST", "/api/finish", {})
    assert status == 200
    app.thread.join(5)
    assert not app.thread.is_alive()
    assert app.result["o"].kind == "complete"
    text = Path(data["path"]).read_text()
    assert "ship it" in text
    assert app.svc.stopped


def test_idle_timeout_suspends(tmp_path):
    clock = {"t": 0.0}
    store = Store.open(tmp_path / ".reviews", CHANGESET["slug"], CHANGESET)
    svc = FakeService()
    review = ReviewServer(
        store=store,
        changeset=CHANGESET,
        graph=GRAPH,
        reviews_dir=tmp_path / ".reviews",
        service=svc,
        host="claude",
        effort="high",
        idle_timeout=0.2,
        clock=lambda: clock["t"],
    )
    result = {}
    thread = threading.Thread(target=lambda: result.update(o=review.serve()), daemon=True)
    thread.start()
    clock["t"] = 10.0
    thread.join(5)
    assert result["o"].kind == "suspended"
    assert result["o"].path.endswith(".state.json")
    assert svc.stopped


def test_idle_timeout_zero_disables_the_watchdog(tmp_path):
    review = ReviewServer(
        store=Store.open(tmp_path / ".reviews", CHANGESET["slug"], CHANGESET),
        changeset=CHANGESET,
        graph=GRAPH,
        reviews_dir=tmp_path / ".reviews",
        service=FakeService(),
        host="claude",
        effort="high",
        idle_timeout=0,
    )
    review._watchdog()  # returns immediately instead of suspending
    assert review.outcome.kind == "running"


def test_events_polling_does_not_reset_the_idle_clock(tmp_path):
    clock = {"t": 0.0}
    review = ReviewServer(
        store=Store.open(tmp_path / ".reviews", CHANGESET["slug"], CHANGESET),
        changeset=CHANGESET,
        graph=GRAPH,
        reviews_dir=tmp_path / ".reviews",
        service=FakeService(),
        host="claude",
        effort="high",
        idle_timeout=0.2,
        clock=lambda: clock["t"],
    )
    result = {}
    thread = threading.Thread(target=lambda: result.update(o=review.serve()), daemon=True)
    thread.start()
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            try:
                jcall(review, "GET", "/api/events?since=0")
            except OSError:
                return  # the server stopped; that is what we are waiting for
            time.sleep(0.02)

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    clock["t"] = 10.0
    thread.join(5)
    stop.set()
    poller.join(5)
    assert result["o"].kind == "suspended"
