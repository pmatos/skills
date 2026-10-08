"""Sole writer of `<reviews_dir>/<slug>.state.json`, plus the in-memory event log."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .anchors import anchor_hash

LABELS = ("blocking", "suggestion", "question", "nit")
STATUSES = ("pending", "accepted", "rejected")
VERDICTS = ("CONFIRMED", "PLAUSIBLE")
SIDES = ("old", "new")
SCOPES = ("line", "file", "pr")
PASS_STATUSES = ("running", "done", "failed")
ROLES = ("user", "agent")
EDITABLE_FIELDS = ("body", "label", "suggestion", "status")

_LABEL_RANK = {label: len(LABELS) - i for i, label in enumerate(LABELS)}
_VERDICT_RANK = {"CONFIRMED": 2, "PLAUSIBLE": 1, None: 0}
_STATE_VERSION = 1


class StoreError(ValueError):
    """Invalid input; the message is safe to feed back to the caller."""


class NotFoundError(StoreError):
    pass


class ForbiddenError(StoreError):
    pass


def atomic_write(path: str | Path, text: str, mode: int = 0o644) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _check_range(prefix: str, start: object, end: object, errors: list[str]) -> None:
    for name, value in (("start", start), ("end", end)):
        if not _is_int(value) or value < 1:
            errors.append(f"{prefix}.{name}: must be an integer >= 1")
    if _is_int(start) and _is_int(end) and start > end:
        errors.append(f"{prefix}: start must be <= end")


def validate_findings(findings: object) -> None:
    """Raise StoreError listing every contract violation in a pass's findings array."""
    if not isinstance(findings, list):
        raise StoreError("findings: must be a JSON array")
    errors: list[str] = []
    for i, f in enumerate(findings):
        p = f"findings[{i}]"
        if not isinstance(f, dict):
            errors.append(f"{p}: must be an object")
            continue
        for key in ("path", "body", "category"):
            if not isinstance(f.get(key), str) or not f[key].strip():
                errors.append(f"{p}.{key}: must be a non-empty string")
        if f.get("side") not in SIDES:
            errors.append(f"{p}.side: must be one of {', '.join(SIDES)}")
        _check_range(p, f.get("start"), f.get("end"), errors)
        if f.get("label") not in LABELS:
            errors.append(f"{p}.label: must be one of {', '.join(LABELS)}")
        if f.get("verdict") not in VERDICTS:
            errors.append(f"{p}.verdict: must be one of {', '.join(VERDICTS)}")
        if f.get("suggestion") is not None and not isinstance(f["suggestion"], str):
            errors.append(f"{p}.suggestion: must be a string or null")
    if errors:
        raise StoreError("\n".join(errors))


def _overlaps(a: dict, b: dict) -> bool:
    return a["start"] <= b["end"] and b["start"] <= a["end"]


class Store:
    def __init__(self, path: Path, state: dict, changeset: dict) -> None:
        self.path = path
        self._state = state
        self._files = {f["path"]: f for f in changeset.get("files", [])}
        self._cond = threading.Condition(threading.RLock())
        self._base_seq = self._seq = int(state.get("events", 0))
        self._events: list[dict] = []

    @classmethod
    def open(cls, reviews_dir: str | Path, slug: str, changeset: dict) -> Store:
        if not slug or "/" in slug or "\\" in slug or slug in (".", ".."):
            raise StoreError(f"invalid slug: {slug!r}")
        directory = Path(reviews_dir)
        directory.mkdir(parents=True, exist_ok=True)
        ignore = directory / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")

        path = directory / f"{slug}.state.json"
        head_sha = changeset.get("head", {}).get("sha")
        content_sha = hashlib.sha1(
            json.dumps(changeset.get("files", []), sort_keys=True).encode("utf-8")
        ).hexdigest()
        if path.exists():
            state = cls._load(path)
            store = cls(path, state, changeset)
            previous = state.get("head_sha")
            moved = previous != head_sha or state.get("content_sha") != content_sha
            state["head_moved"] = moved
            state["previous_head_sha"] = previous if previous != head_sha else None
            state["head_sha"] = head_sha
            state["base_sha"] = changeset.get("base", {}).get("sha")
            state["content_sha"] = content_sha
            for comment in state["comments"]:
                comment["stale"] = store._is_stale(comment["anchor"])
        else:
            state = {
                "version": _STATE_VERSION,
                "revision": 0,
                "target": changeset.get("target"),
                "base_sha": changeset.get("base", {}).get("sha"),
                "head_sha": head_sha,
                "content_sha": content_sha,
                "summary": "",
                "comments": [],
                "threads": [],
                "passes": {},
                "head_moved": False,
                "previous_head_sha": None,
                "counters": {"c": 0, "t": 0},
                "events": 0,
                "updated_at": _now(),
            }
            store = cls(path, state, changeset)
        state["revision"] += 1
        state["updated_at"] = _now()
        store._save()
        return store

    @staticmethod
    def _load(path: Path) -> dict:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StoreError(f"cannot read state file {path}: {exc}") from exc
        if not isinstance(state, dict) or state.get("version") != _STATE_VERSION:
            raise StoreError(f"unsupported state file {path}")
        state.setdefault("revision", 0)
        state.setdefault("summary", "")
        state.setdefault("comments", [])
        state.setdefault("threads", [])
        state.setdefault("passes", {})
        state.setdefault("events", 0)
        counters = state.setdefault("counters", {})
        for prefix, items in (("c", state["comments"]), ("t", state["threads"])):
            seen = [int(i["id"][1:]) for i in items if str(i.get("id", "")).startswith(prefix)]
            counters[prefix] = max(counters.get(prefix, 0), *seen, 0)
        return state

    def _save(self) -> None:
        self._state["events"] = self._seq
        atomic_write(self.path, json.dumps(self._state, indent=2, ensure_ascii=False), 0o600)

    def _commit(self, events: list[tuple[str, dict]]) -> None:
        self._state["revision"] += 1
        self._state["updated_at"] = _now()
        for type_, data in events:
            self._seq += 1
            self._events.append({"seq": self._seq, "type": type_, "data": copy.deepcopy(data)})
        self._save()
        self._cond.notify_all()

    def _next_id(self, prefix: str) -> str:
        counters = self._state["counters"]
        counters[prefix] += 1
        return f"{prefix}{counters[prefix]}"

    def _hash(self, path: str, side: str, start: int, end: int) -> str | None:
        entry = self._files.get(path)
        return None if entry is None else anchor_hash(entry, side, start, end)

    def _is_stale(self, anchor: dict) -> bool:
        if anchor["scope"] == "pr":
            return False
        if anchor["scope"] == "file":
            return anchor["path"] not in self._files
        if anchor["path"] not in self._files:
            return True  # a None-vs-None hash comparison must not read as "not stale"
        current = self._hash(anchor["path"], anchor["side"], anchor["start"], anchor["end"])
        return anchor.get("hash") != current

    def _normalize_anchor(self, anchor: object) -> dict:
        if not isinstance(anchor, dict):
            raise StoreError("anchor: must be an object")
        scope = anchor.get("scope")
        if scope not in SCOPES:
            raise StoreError(f"anchor.scope: must be one of {', '.join(SCOPES)}")
        if scope == "pr":
            return {"scope": "pr"}
        path = anchor.get("path")
        if not isinstance(path, str) or not path:
            raise StoreError("anchor.path: required for line and file scope")
        if scope == "file":
            return {"scope": "file", "path": path}
        side = anchor.get("side")
        if side not in SIDES:
            raise StoreError(f"anchor.side: must be one of {', '.join(SIDES)}")
        errors: list[str] = []
        _check_range("anchor", anchor.get("start"), anchor.get("end"), errors)
        if errors:
            raise StoreError("; ".join(errors))
        start, end = anchor["start"], anchor["end"]
        return {
            "scope": "line",
            "path": path,
            "side": side,
            "start": start,
            "end": end,
            "hash": self._hash(path, side, start, end),
        }

    @staticmethod
    def _check_body(body: object) -> str:
        if not isinstance(body, str) or not body.strip():
            raise StoreError("body: must be a non-empty string")
        return body

    @staticmethod
    def _check_enum(name: str, value: object, allowed: tuple[str, ...]) -> str:
        if value not in allowed:
            raise StoreError(f"{name}: must be one of {', '.join(allowed)}")
        return value

    @staticmethod
    def _check_suggestion(value: object) -> str | None:
        if value is not None and not isinstance(value, str):
            raise StoreError("suggestion: must be a string or null")
        return value

    def _find_comment(self, comment_id: str) -> dict:
        for comment in self._state["comments"]:
            if comment["id"] == comment_id:
                return comment
        raise NotFoundError(f"no comment {comment_id}")

    def _find_thread(self, thread_id: str) -> dict:
        for thread in self._state["threads"]:
            if thread["id"] == thread_id:
                return thread
        raise NotFoundError(f"no thread {thread_id}")

    def snapshot(self) -> dict:
        with self._cond:
            state = copy.deepcopy(self._state)
            state["events"] = self._seq
            return state

    @property
    def revision(self) -> int:
        with self._cond:
            return self._state["revision"]

    @property
    def head_moved(self) -> bool:
        with self._cond:
            return bool(self._state["head_moved"])

    def get_comment(self, comment_id: str) -> dict:
        with self._cond:
            return copy.deepcopy(self._find_comment(comment_id))

    def add_comment(
        self, anchor: dict, body: str, label: str = "suggestion", suggestion: str | None = None
    ) -> dict:
        with self._cond:
            comment = {
                "id": None,
                "anchor": self._normalize_anchor(anchor),
                "label": self._check_enum("label", label, LABELS),
                "body": self._check_body(body),
                "suggestion": self._check_suggestion(suggestion),
                "origin": "user",
                "sources": [],
                "verdict": None,
                "status": "accepted",
                "stale": False,
                "edited": False,
            }
            comment["id"] = self._next_id("c")
            self._state["comments"].append(comment)
            self._commit([("comment_added", comment)])
            return copy.deepcopy(comment)

    def patch_comment(self, comment_id: str, fields: dict) -> dict:
        with self._cond:
            comment = self._find_comment(comment_id)
            if not isinstance(fields, dict) or not fields:
                raise StoreError("fields: must be a non-empty object")
            unknown = sorted(set(fields) - set(EDITABLE_FIELDS))
            if unknown:
                raise StoreError(f"cannot change: {', '.join(unknown)}")
            clean: dict = {}
            if "body" in fields:
                clean["body"] = self._check_body(fields["body"])
            if "label" in fields:
                clean["label"] = self._check_enum("label", fields["label"], LABELS)
            if "suggestion" in fields:
                clean["suggestion"] = self._check_suggestion(fields["suggestion"])
            if "status" in fields:
                clean["status"] = self._check_enum("status", fields["status"], STATUSES)
            for key in ("body", "label", "suggestion"):
                if key in clean and clean[key] != comment[key]:
                    comment["edited"] = True
            comment.update(clean)
            self._commit([("comment_updated", comment)])
            return copy.deepcopy(comment)

    def delete_comment(self, comment_id: str) -> None:
        with self._cond:
            comment = self._find_comment(comment_id)
            if comment["origin"] != "user":
                raise ForbiddenError("only user comments can be deleted; reject it instead")
            self._state["comments"].remove(comment)
            self._commit([("comment_deleted", {"id": comment_id})])

    def set_summary(self, text: str) -> None:
        if not isinstance(text, str):
            raise StoreError("summary: must be a string")
        with self._cond:
            self._state["summary"] = text
            self._commit([("summary_updated", {"summary": text})])

    def set_pass_status(self, name: str, status: str) -> None:
        if not isinstance(name, str) or not name:
            raise StoreError("name: must be a non-empty string")
        self._check_enum("status", status, PASS_STATUSES)
        with self._cond:
            self._state["passes"][name] = status
            self._commit([("pass_status", {"name": name, "status": status})])

    def publish(self, type_: str, data: dict) -> int:
        """Emit a transient event (e.g. ask progress) without touching saved state."""
        with self._cond:
            self._seq += 1
            self._events.append(
                {"seq": self._seq, "type": type_, "data": copy.deepcopy(data)},
            )
            self._cond.notify_all()
            return self._seq

    def add_findings(self, findings: list[dict], source: str | None = None) -> list[dict]:
        validate_findings(findings)
        with self._cond:
            events: list[tuple[str, dict]] = []
            touched: dict[str, dict] = {}
            for finding in findings:
                incoming = self._incoming(finding, source or finding["category"])
                targets = self._merge_targets(incoming["anchor"])
                if not targets:
                    comment = self._new_agent_comment(incoming)
                    self._state["comments"].append(comment)
                    events.append(("comment_added", comment))
                    touched[comment["id"]] = comment
                    continue
                target = targets[0]
                self._merge(target, incoming)
                while True:
                    others = [c for c in self._merge_targets(target["anchor"]) if c is not target]
                    if not others:
                        break
                    other = others[0]
                    self._merge(target, self._incoming_from(other))
                    self._state["comments"].remove(other)
                    touched.pop(other["id"], None)
                    events.append(("comment_deleted", {"id": other["id"]}))
                events.append(("comment_updated", target))
                touched[target["id"]] = target
            if events:
                self._commit(events)
            return [copy.deepcopy(c) for c in touched.values()]

    def _incoming(self, finding: dict, source: str) -> dict:
        path, side = finding["path"], finding["side"]
        start, end = finding["start"], finding["end"]
        suggestion = finding.get("suggestion")
        digest = self._hash(path, side, start, end)
        if path not in self._files:
            anchor = {"scope": "pr"}
            suggestion = None
        elif digest is None:
            anchor = {"scope": "file", "path": path}
            suggestion = None
        else:
            anchor = {
                "scope": "line",
                "path": path,
                "side": side,
                "start": start,
                "end": end,
                "hash": digest,
            }
        return {
            "anchor": anchor,
            "label": finding["label"],
            "verdict": finding["verdict"],
            "body": finding["body"],
            "suggestion": suggestion,
            "sources": [source],
        }

    @staticmethod
    def _incoming_from(comment: dict) -> dict:
        return {k: comment[k] for k in ("anchor", "label", "verdict", "body", "suggestion")} | {
            "sources": list(comment["sources"])
        }

    def _new_agent_comment(self, incoming: dict) -> dict:
        return {
            "id": self._next_id("c"),
            **incoming,
            "origin": "agent",
            "status": "pending",
            "stale": False,
            "edited": False,
        }

    def _merge_targets(self, anchor: dict) -> list[dict]:
        if anchor["scope"] != "line":
            return []
        return [
            c
            for c in self._state["comments"]
            if c["origin"] == "agent"
            and c["status"] == "pending"
            and not c["edited"]
            and not c["stale"]
            and c["anchor"]["scope"] == "line"
            and c["anchor"]["path"] == anchor["path"]
            and c["anchor"]["side"] == anchor["side"]
            and _overlaps(c["anchor"], anchor)
        ]

    def _merge(self, target: dict, incoming: dict) -> None:
        old, new = target["anchor"], incoming["anchor"]
        start, end = min(old["start"], new["start"]), max(old["end"], new["end"])
        suggestion = next(
            (
                s
                for s, a in ((target["suggestion"], old), (incoming["suggestion"], new))
                if s is not None and (a["start"], a["end"]) == (start, end)
            ),
            None,
        )
        t_rank = (_LABEL_RANK[target["label"]], _VERDICT_RANK[target["verdict"]])
        i_rank = (_LABEL_RANK[incoming["label"]], _VERDICT_RANK[incoming["verdict"]])
        winner, loser = (incoming, target) if i_rank > t_rank else (target, incoming)
        body = winner["body"]
        if loser["body"].strip() and loser["body"].strip() not in body:
            body = f"{body}\n\n{loser['body']}"
        target["anchor"] = {
            **old,
            "start": start,
            "end": end,
            "hash": self._hash(old["path"], old["side"], start, end),
        }
        target["label"] = _best(target["label"], incoming["label"], _LABEL_RANK)
        target["verdict"] = _best(target["verdict"], incoming["verdict"], _VERDICT_RANK)
        target["body"] = body
        target["suggestion"] = suggestion
        target["sources"] = list(dict.fromkeys([*target["sources"], *incoming["sources"]]))

    def add_thread(
        self, anchor: dict, text: str, role: str = "user", session: str | None = None
    ) -> dict:
        self._check_enum("role", role, ROLES)
        self._check_body(text)
        with self._cond:
            thread = {
                "id": None,
                "anchor": self._normalize_anchor(anchor),
                "messages": [{"role": role, "text": text}],
                "session": session,
            }
            thread["id"] = self._next_id("t")
            self._state["threads"].append(thread)
            self._commit([("thread_added", thread)])
            return copy.deepcopy(thread)

    def append_message(
        self, thread_id: str, role: str, text: str, session: str | None = None
    ) -> dict:
        self._check_enum("role", role, ROLES)
        self._check_body(text)
        with self._cond:
            thread = self._find_thread(thread_id)
            thread["messages"].append({"role": role, "text": text})
            if session is not None:
                thread["session"] = session
            self._commit([("thread_updated", thread)])
            return copy.deepcopy(thread)

    def get_thread(self, thread_id: str) -> dict:
        with self._cond:
            return copy.deepcopy(self._find_thread(thread_id))

    def events_since(self, since: int, timeout: float = 0.0) -> tuple[list[dict], int]:
        """Events with seq > since, blocking up to `timeout` seconds when there are none.

        A `since` ahead of the log (client from before a restart) returns immediately
        with the current last_seq so the client can resynchronise.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                if since > self._seq:
                    return [], self._seq
                if self._seq > since:
                    tail = self._events[max(0, since - self._base_seq) :]
                    return copy.deepcopy(tail), self._seq
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return [], self._seq
                self._cond.wait(remaining)


def _best(a: object, b: object, rank: dict) -> object:
    return a if rank[a] >= rank[b] else b
