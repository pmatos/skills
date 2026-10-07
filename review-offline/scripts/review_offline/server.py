"""Local review server: static shell plus a token-guarded JSON API on 127.0.0.1."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from . import markdown
from .assets import build_shell
from .store import ForbiddenError, NotFoundError, Store, StoreError

MAX_BODY = 1_000_000
LONG_POLL_SECONDS = 25.0
CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


class AgentService(Protocol):
    def start_passes(self) -> None: ...

    def ask(self, thread: dict, text: str) -> tuple[str, str | None]: ...

    def shutdown(self) -> None: ...


@dataclass
class Outcome:
    kind: str = "running"
    path: str = ""


@dataclass
class ReviewServer:
    store: Store
    changeset: dict
    graph: dict
    reviews_dir: Path
    service: AgentService
    host: str
    effort: str
    notes: list[str] = field(default_factory=list)
    idle_timeout: float = 1800.0
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self.token = secrets.token_urlsafe(24)
        self.outcome = Outcome()
        self._pending: set[str] = set()
        self._thread_locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._last_activity = self.clock()
        self._shell = build_shell()
        handler = _make_handler(self)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.output_path = self.reviews_dir / f"{self.changeset['slug']}.md"

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#t={self.token}"

    def touch(self) -> None:
        self._last_activity = self.clock()

    def snapshot(self) -> dict:
        with self._guard:
            pending = sorted(self._pending)
        return {"state": self.store.snapshot(), "pending_threads": pending}

    def bootstrap(self) -> dict:
        return {
            **self.snapshot(),
            "changeset": self.changeset,
            "graph": self.graph,
            "host": self.host,
            "effort": self.effort,
            "notes": self.notes,
        }

    def start_ask(self, anchor: dict, text: str, thread_id: str | None) -> str:
        if not isinstance(text, str) or not text.strip():
            raise StoreError("text: required")
        if thread_id:
            self.store.get_thread(thread_id)
            self.store.append_message(thread_id, "user", text)
        else:
            thread_id = self.store.add_thread(anchor, text)["id"]
        with self._guard:
            self._pending.add(thread_id)
            lock = self._thread_locks.setdefault(thread_id, threading.Lock())
        threading.Thread(target=self._answer, args=(thread_id, lock), daemon=True).start()
        return thread_id

    def _answer(self, thread_id: str, lock: threading.Lock) -> None:
        with lock:
            try:
                thread = self.store.get_thread(thread_id)
                answer, session = self.service.ask(thread, thread["messages"][-1]["text"])
            except Exception as exc:  # noqa: BLE001 - surfaced to the reviewer in the thread
                answer, session = f"The agent request failed: {exc}", None
            self.store.append_message(thread_id, "agent", answer, session=session)
            with self._guard:
                self._pending.discard(thread_id)
            self.store.publish("ask_done", {"id": thread_id})

    def finish(self) -> str:
        markdown.write(self.store.snapshot(), self.changeset, self.output_path)
        self.outcome = Outcome("complete", str(self.output_path))
        threading.Timer(0.3, self.stop).start()
        return str(self.output_path)

    def stop(self) -> None:
        self.service.shutdown()
        self.httpd.shutdown()

    def _watchdog(self) -> None:
        while self.outcome.kind == "running":
            time.sleep(min(5.0, max(0.05, self.idle_timeout / 10)))
            if self.clock() - self._last_activity > self.idle_timeout:
                if self.outcome.kind == "running":
                    self.outcome = Outcome("suspended", str(self._state_path()))
                    self.stop()
                return

    def _state_path(self) -> Path:
        return self.reviews_dir / f"{self.changeset['slug']}.state.json"

    def serve(self) -> Outcome:
        threading.Thread(target=self._watchdog, daemon=True).start()
        self.service.start_passes()
        try:
            self.httpd.serve_forever(poll_interval=0.2)
        finally:
            self.httpd.server_close()
        if self.outcome.kind == "running":
            self.outcome = Outcome("suspended", str(self._state_path()))
        return self.outcome


def _make_handler(app: ReviewServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            return

        def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"))

        def _trusted(self) -> bool:
            if self.headers.get("Host") != f"127.0.0.1:{app.port}":
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin == f"http://127.0.0.1:{app.port}"

        def _authed(self) -> bool:
            given = self.headers.get("X-Review-Token", "")
            return hmac.compare_digest(given.encode(), app.token.encode())

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                remaining = min(length, 10 * MAX_BODY)
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                raise StoreError("request body too large")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise StoreError("request body must be a JSON object")
            return data

        def _route(self, method: str) -> None:
            if not self._trusted():
                return self._json(403, {"error": "forbidden host or origin"})
            url = urlparse(self.path)
            if method == "GET" and url.path == "/":
                return self._send(200, app._shell.encode("utf-8"), "text/html; charset=utf-8")
            if not url.path.startswith("/api/") or not self._authed():
                return self._json(403 if url.path.startswith("/api/") else 404, {"error": "no"})
            app.touch()
            try:
                self._api(method, url.path, parse_qs(url.query))
            except NotFoundError as exc:
                self._json(404, {"error": str(exc)})
            except ForbiddenError as exc:
                self._json(403, {"error": str(exc)})
            except (StoreError, json.JSONDecodeError, ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})

        def _api(self, method: str, path: str, query: dict) -> None:
            parts = path.strip("/").split("/")[1:]
            if method == "GET" and parts == ["bootstrap"]:
                return self._json(200, app.bootstrap())
            if method == "GET" and parts == ["snapshot"]:
                return self._json(200, app.snapshot())
            if method == "GET" and parts == ["events"]:
                since = int(query.get("since", ["0"])[0])
                events, last = app.store.events_since(since, LONG_POLL_SECONDS)
                app.touch()
                return self._json(200, {"events": events, "last": last})
            if method == "POST" and parts == ["comments"]:
                data = self._body()
                comment = app.store.add_comment(
                    data.get("anchor"),
                    data.get("body", ""),
                    data.get("label", "suggestion"),
                    data.get("suggestion"),
                )
                return self._json(201, comment)
            if len(parts) == 2 and parts[0] == "comments":
                if method == "PATCH":
                    return self._json(200, app.store.patch_comment(parts[1], self._body()))
                if method == "DELETE":
                    app.store.delete_comment(parts[1])
                    return self._json(200, {"ok": True})
            if method == "PUT" and parts == ["summary"]:
                app.store.set_summary(self._body().get("text", ""))
                return self._json(200, {"ok": True})
            if method == "POST" and parts == ["ask"]:
                data = self._body()
                thread_id = app.start_ask(
                    data.get("anchor"), data.get("text"), data.get("thread_id")
                )
                return self._json(202, {"thread_id": thread_id})
            if method == "POST" and parts == ["finish"]:
                return self._json(200, {"path": app.finish()})
            self._json(404, {"error": "unknown route"})

        def do_GET(self) -> None:
            self._route("GET")

        def do_POST(self) -> None:
            self._route("POST")

        def do_PUT(self) -> None:
            self._route("PUT")

        def do_PATCH(self) -> None:
            self._route("PATCH")

        def do_DELETE(self) -> None:
            self._route("DELETE")

    return Handler
