import json
import threading
import time

import pytest
from review_offline.store import ForbiddenError, NotFoundError, Store, StoreError


def make_changeset(head="h1", line2="two"):
    def lines(prefix):
        return [{"t": "ctx", "o": i, "n": i, "text": f"{prefix}{i}"} for i in range(1, 9)]

    a_lines = lines("a")
    a_lines[1] = {"t": "ctx", "o": 2, "n": 2, "text": line2}
    return {
        "target": "pr:1",
        "title": "T",
        "slug": "pr-1",
        "base": {"sha": "b0", "ref": "main"},
        "head": {"sha": head, "ref": "feat"},
        "files": [
            {"path": "a.py", "hunks": [{"lines": a_lines}]},
            {"path": "b.py", "hunks": [{"lines": lines("b")}]},
        ],
    }


def line(path="a.py", start=1, end=1, side="new"):
    return {"scope": "line", "path": path, "side": side, "start": start, "end": end}


def finding(start=1, end=1, **kw):
    base = {
        "path": "a.py",
        "side": "new",
        "start": start,
        "end": end,
        "label": "nit",
        "body": f"body {start}-{end}",
        "suggestion": None,
        "category": "correctness",
        "verdict": "PLAUSIBLE",
    }
    return base | kw


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / ".reviews", "pr-1", make_changeset())


def test_creates_gitignore_once(tmp_path):
    d = tmp_path / "r"
    Store.open(d, "pr-1", make_changeset())
    assert (d / ".gitignore").read_text().strip() == "*"
    (d / ".gitignore").write_text("custom\n")
    Store.open(d, "pr-1", make_changeset())
    assert (d / ".gitignore").read_text() == "custom\n"


def test_rejects_path_like_slug(tmp_path):
    with pytest.raises(StoreError):
        Store.open(tmp_path, "../x", make_changeset())


def test_state_file_written_and_atomic(store):
    store.add_comment(line(), "hi", "nit")
    data = json.loads(store.path.read_text())
    assert data["version"] == 1 and data["comments"][0]["id"] == "c1"
    assert [p.name for p in store.path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_ids_never_reused(tmp_path):
    d = tmp_path / "r"
    s = Store.open(d, "pr-1", make_changeset())
    s.add_comment(line(), "one", "nit")
    c2 = s.add_comment(line(), "two", "nit")
    s.delete_comment(c2["id"])
    c3 = s.add_comment(line(), "three", "nit")
    assert c3["id"] == "c3"
    s.delete_comment("c3")
    t = s.add_thread({"scope": "pr"}, "q")
    s.add_thread({"scope": "pr"}, "q2")
    assert t["id"] == "t1"
    s2 = Store.open(d, "pr-1", make_changeset())
    assert s2.add_comment(line(), "four", "nit")["id"] == "c4"
    assert s2.add_thread({"scope": "pr"}, "q3")["id"] == "t3"


def test_revision_and_event_seq_increase(store):
    revisions = [store.revision]
    store.add_comment(line(), "a", "nit")
    revisions.append(store.revision)
    store.set_summary("s")
    revisions.append(store.revision)
    store.set_pass_status("correctness", "running")
    revisions.append(store.revision)
    assert revisions == sorted(set(revisions))
    events, last = store.events_since(0)
    assert [e["seq"] for e in events] == [1, 2, 3] and last == 3
    assert [e["type"] for e in events] == ["comment_added", "summary_updated", "pass_status"]


def test_event_seq_survives_resume(tmp_path):
    d = tmp_path / "r"
    s = Store.open(d, "pr-1", make_changeset())
    s.add_comment(line(), "a", "nit")
    s2 = Store.open(d, "pr-1", make_changeset())
    s2.add_comment(line(), "b", "nit")
    events, last = s2.events_since(1)
    assert [e["seq"] for e in events] == [2] and last == 2
    assert s2.events_since(99) == ([], 2)


def test_concurrent_findings_and_comments_stay_consistent(store):
    errors = []

    def agent(offset):
        try:
            for i in range(20):
                n = offset + i * 10
                store.add_findings([finding(n % 8 + 1, n % 8 + 1, category=f"p{offset}")], "p")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def user():
        try:
            for i in range(40):
                store.add_comment(line("b.py", i % 8 + 1, i % 8 + 1), f"u{i}", "nit")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=agent, args=(o,)) for o in (0, 1, 2)]
    threads.append(threading.Thread(target=user))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    snap = store.snapshot()
    ids = [c["id"] for c in snap["comments"]]
    assert len(ids) == len(set(ids))
    assert sum(c["origin"] == "user" for c in snap["comments"]) == 40
    agents = [c for c in snap["comments"] if c["origin"] == "agent"]
    assert len(agents) == 8
    on_disk = json.loads(store.path.read_text())
    assert on_disk["comments"] == snap["comments"]
    assert on_disk["revision"] == snap["revision"]
    seqs = [e["seq"] for e in store.events_since(0)[0]]
    assert seqs == list(range(1, len(seqs) + 1))


def test_resume_same_head_not_moved_or_stale(tmp_path):
    d = tmp_path / "r"
    s = Store.open(d, "pr-1", make_changeset())
    s.add_comment(line(start=2, end=2), "x", "nit")
    s2 = Store.open(d, "pr-1", make_changeset())
    assert not s2.head_moved
    assert s2.snapshot()["comments"][0]["stale"] is False


def test_resume_head_moved_marks_stale_by_hash(tmp_path):
    d = tmp_path / "r"
    s = Store.open(d, "pr-1", make_changeset())
    s.add_comment(line(start=2, end=2), "changed line", "nit")
    s.add_comment(line(start=3, end=3), "same line", "nit")
    s.add_comment(line("b.py", 1, 1), "other file", "nit")
    s.add_comment({"scope": "file", "path": "a.py"}, "file level", "nit")
    s.add_comment({"scope": "pr"}, "pr level", "nit")
    s2 = Store.open(d, "pr-1", make_changeset(head="h2", line2="TWO"))
    snap = s2.snapshot()
    assert snap["head_moved"] and snap["head_sha"] == "h2" and snap["previous_head_sha"] == "h1"
    assert [c["stale"] for c in snap["comments"]] == [True, False, False, False, False]


def test_resume_head_moved_file_gone_is_stale(tmp_path):
    d = tmp_path / "r"
    s = Store.open(d, "pr-1", make_changeset())
    s.add_comment({"scope": "file", "path": "b.py"}, "f", "nit")
    cs = make_changeset(head="h2")
    cs["files"] = cs["files"][:1]
    assert Store.open(d, "pr-1", cs).snapshot()["comments"][0]["stale"] is True


def test_corrupt_state_raises(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "pr-1.state.json").write_text("{nope")
    with pytest.raises(StoreError):
        Store.open(d, "pr-1", make_changeset())


def test_add_comment_validation(store):
    with pytest.raises(StoreError):
        store.add_comment(line(side="middle"), "x", "nit")
    with pytest.raises(StoreError):
        store.add_comment(line(start=5, end=2), "x", "nit")
    with pytest.raises(StoreError):
        store.add_comment({"scope": "file"}, "x", "nit")
    with pytest.raises(StoreError):
        store.add_comment({"scope": "weird"}, "x", "nit")
    with pytest.raises(StoreError):
        store.add_comment(line(), "x", "huge")
    with pytest.raises(StoreError):
        store.add_comment(line(), "  ", "nit")
    assert store.snapshot()["comments"] == []


def test_user_comment_shape_and_hash(store):
    c = store.add_comment(line(start=2, end=3), "x", "blocking", "fix")
    assert c["origin"] == "user" and c["status"] == "accepted" and c["stale"] is False
    assert c["sources"] == [] and c["verdict"] is None and c["suggestion"] == "fix"
    assert len(c["anchor"]["hash"]) == 12
    assert store.add_comment({"scope": "pr"}, "g", "question")["anchor"] == {"scope": "pr"}


def test_patch_comment(store):
    c = store.add_comment(line(), "x", "nit")
    out = store.patch_comment(c["id"], {"body": "y", "label": "blocking", "status": "rejected"})
    assert (out["body"], out["label"], out["status"]) == ("y", "blocking", "rejected")
    for bad in (
        {"anchor": line()},
        {"origin": "agent"},
        {"label": "x"},
        {"status": "done"},
        {"body": ""},
        {"suggestion": 3},
        {},
    ):
        with pytest.raises(StoreError):
            store.patch_comment(c["id"], bad)
    with pytest.raises(NotFoundError):
        store.patch_comment("c99", {"body": "z"})
    assert store.get_comment(c["id"])["body"] == "y"


def test_delete_user_only(store):
    store.add_findings([finding()], "p")
    with pytest.raises(ForbiddenError):
        store.delete_comment("c1")
    with pytest.raises(NotFoundError):
        store.delete_comment("c9")
    u = store.add_comment(line(), "u", "nit")
    store.delete_comment(u["id"])
    assert [c["id"] for c in store.snapshot()["comments"]] == ["c1"]
    assert store.events_since(0)[0][-1] == {
        "seq": 3,
        "type": "comment_deleted",
        "data": {"id": u["id"]},
    }


def test_findings_become_pending_agent_comments(store):
    (c,) = store.add_findings([finding(2, 3, suggestion="fix")], "correctness")
    assert c["origin"] == "agent" and c["status"] == "pending" and c["sources"] == ["correctness"]
    assert c["verdict"] == "PLAUSIBLE" and c["suggestion"] == "fix"
    assert c["anchor"]["scope"] == "line" and len(c["anchor"]["hash"]) == 12


def test_finding_downgrades(store):
    far, ghost = store.add_findings(
        [finding(50, 51, suggestion="x"), finding(path="zzz.py", suggestion="x")], "p"
    )
    assert far["anchor"] == {"scope": "file", "path": "a.py"} and far["suggestion"] is None
    assert ghost["anchor"] == {"scope": "pr"} and ghost["suggestion"] is None


def test_finding_validation_reports_every_error_and_changes_nothing(store):
    bad = [
        finding(label="huge"),
        finding(start=5, end=2),
        finding(verdict="MAYBE"),
        finding(body=""),
        "not an object",
    ]
    with pytest.raises(StoreError) as err:
        store.add_findings([finding(), *bad], "p")
    msg = str(err.value)
    assert "findings[1].label" in msg and "findings[2]" in msg and "findings[3].verdict" in msg
    assert "findings[4].body" in msg and "findings[5]" in msg
    assert store.snapshot()["comments"] == []
    with pytest.raises(StoreError):
        store.add_findings({"not": "a list"}, "p")


def test_merge_overlapping_same_side(store):
    store.add_findings(
        [finding(2, 4, label="nit", verdict="PLAUSIBLE", body="first", category="cleanup")],
        "cleanup",
    )
    out = store.add_findings(
        [finding(4, 6, label="blocking", verdict="CONFIRMED", body="second")], "correctness"
    )
    comments = store.snapshot()["comments"]
    assert len(comments) == 1 and len(out) == 1
    (c,) = comments
    assert (c["anchor"]["start"], c["anchor"]["end"]) == (2, 6)
    assert c["label"] == "blocking" and c["verdict"] == "CONFIRMED"
    assert c["sources"] == ["cleanup", "correctness"]
    assert c["body"].startswith("second") and "first" in c["body"]
    assert c["id"] == "c1"


def test_merge_keeps_stronger_existing(store):
    store.add_findings([finding(1, 3, label="blocking", verdict="CONFIRMED", body="A")], "x")
    store.add_findings([finding(2, 2, label="question", verdict="PLAUSIBLE", body="B")], "y")
    (c,) = store.snapshot()["comments"]
    assert c["label"] == "blocking" and c["verdict"] == "CONFIRMED" and c["sources"] == ["x", "y"]
    assert (c["anchor"]["start"], c["anchor"]["end"]) == (1, 3)


def test_label_strength_order(store):
    store.add_findings([finding(1, 1, label="nit")], "a")
    store.add_findings([finding(1, 1, label="question")], "b")
    assert store.snapshot()["comments"][0]["label"] == "question"
    store.add_findings([finding(1, 1, label="suggestion")], "c")
    assert store.snapshot()["comments"][0]["label"] == "suggestion"
    store.add_findings([finding(1, 1, label="nit")], "d")
    assert store.snapshot()["comments"][0]["label"] == "suggestion"


def test_no_merge_across_side_path_or_gap(store):
    store.add_findings(
        [
            finding(1, 2),
            finding(1, 2, side="old"),
            finding(1, 2, path="b.py"),
            finding(3, 4),
        ],
        "p",
    )
    assert len(store.snapshot()["comments"]) == 4


def test_batch_bridging_merges_into_one(store):
    store.add_findings([finding(1, 2), finding(5, 6)], "p")
    store.add_findings([finding(2, 5, label="blocking")], "q")
    (c,) = store.snapshot()["comments"]
    assert (c["anchor"]["start"], c["anchor"]["end"]) == (1, 6)
    assert c["sources"] == ["p", "q"] and c["label"] == "blocking"
    types = [e["type"] for e in store.events_since(0)[0]]
    assert "comment_deleted" in types


def test_merge_suggestion_only_when_range_matches(store):
    store.add_findings([finding(1, 2, suggestion="narrow")], "p")
    store.add_findings([finding(2, 3)], "q")
    assert store.snapshot()["comments"][0]["suggestion"] is None
    store.add_findings([finding(1, 3, suggestion="wide")], "r")
    assert store.snapshot()["comments"][0]["suggestion"] == "wide"


@pytest.mark.parametrize(
    "change",
    [
        {"status": "accepted"},
        {"status": "rejected"},
        {"body": "edited by user"},
        {"label": "question"},
        {"suggestion": "mine"},
    ],
)
def test_touched_comments_are_never_overwritten(store, change):
    (agent,) = store.add_findings([finding(2, 3, body="orig", label="nit")], "p")
    store.patch_comment(agent["id"], change)
    before = store.get_comment(agent["id"])
    (new,) = store.add_findings([finding(3, 4, label="blocking", body="later")], "q")
    assert new["id"] != agent["id"] and new["status"] == "pending"
    assert store.get_comment(agent["id"]) == before


def test_user_comments_are_never_merge_targets(store):
    u = store.add_comment(line(start=2, end=3), "mine", "nit")
    (new,) = store.add_findings([finding(2, 3)], "p")
    assert new["id"] != u["id"] and store.get_comment(u["id"])["body"] == "mine"


def test_pass_status_validation(store):
    store.set_pass_status("correctness", "done")
    assert store.snapshot()["passes"] == {"correctness": "done"}
    with pytest.raises(StoreError):
        store.set_pass_status("correctness", "weird")


def test_threads(store):
    t = store.add_thread(line(), "why?", session="s1")
    assert t["messages"] == [{"role": "user", "text": "why?"}] and t["session"] == "s1"
    store.append_message(t["id"], "agent", "because", session="s2")
    got = store.get_thread(t["id"])
    assert [m["role"] for m in got["messages"]] == ["user", "agent"] and got["session"] == "s2"
    with pytest.raises(NotFoundError):
        store.get_thread("t9")
    with pytest.raises(StoreError):
        store.append_message(t["id"], "robot", "x")
    store.append_message(t["id"], "user", "more")
    assert store.get_thread(t["id"])["session"] == "s2"


def test_snapshot_is_a_copy(store):
    store.add_comment(line(), "x", "nit")
    snap = store.snapshot()
    snap["comments"].clear()
    assert len(store.snapshot()["comments"]) == 1
    assert store.snapshot()["events"] == 1


def test_long_poll_wakes_on_mutation(store):
    result = {}

    def waiter():
        start = time.monotonic()
        result["out"] = store.events_since(0, timeout=5)
        result["took"] = time.monotonic() - start

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.2)
    store.add_comment(line(), "wake", "nit")
    t.join(timeout=5)
    events, last = result["out"]
    assert [e["type"] for e in events] == ["comment_added"] and last == 1
    assert result["took"] < 3


def test_long_poll_times_out_empty(store):
    start = time.monotonic()
    assert store.events_since(0, timeout=0.2) == ([], 0)
    assert time.monotonic() - start >= 0.19


def test_events_since_returns_only_newer(store):
    store.add_comment(line(), "a", "nit")
    store.add_comment(line(), "b", "nit")
    events, last = store.events_since(1)
    assert [e["seq"] for e in events] == [2] and last == 2


def test_publish_is_transient(store):
    seq = store.publish("ask_status", {"thread_id": "t1", "status": "thinking"})
    events, last = store.events_since(0)
    assert seq == last == 1 and events[0]["type"] == "ask_status"
    assert json.loads(store.path.read_text())["revision"] == store.revision
