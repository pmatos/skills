"""Run read-only, config-isolated child agents through the same harness as the caller.

Review content is attacker-controlled and the machine may hold powerful MCP tools, so every
child is started with its tools restricted to reading and the harness-identifying environment
removed. The prompt always goes through stdin, never argv, so it can start with `-` and is
not limited by ARG_MAX.

Isolation is enforced as far as each CLI allows:

- claude: `--strict-mcp-config`, empty setting sources, `--restricted` (command tools gone,
  file tools confined to the working directories). The one flag that also kills auto-memory
  and hooks outright, `--bare`, is unusable here because it restricts auth to API keys.
- codex: `--ignore-user-config` plus `-c mcp_servers={}` (codex has no project-level config)
  and the disabled-features list. Its read-only sandbox limits writes only: the child can
  read the whole filesystem, unlike claude/omp whose file tools are confined by --add-dir.
- omp: `--no-extensions` (which is also what disables hooks: they are discovered inside
  extension packages), `--no-skills`, `--no-rules`, and the overlay, whose
  `mcp.enableProjectConfig: false` blocks OMP-native project MCP files (verified on omp
  18.8.0). There is no supported switch for the user-level `~/.omp/agent/mcp.json`, the
  portable root `.mcp.json` fallback, or third-party tool configs, and relocating the whole
  config root would also drop stored auth; those sources stay reachable and are documented
  in SKILL.md's limitations.


Effort mapping (our level -> native option; the first three are passed through unchanged):

    low, medium, high, xhigh, max   claude --effort / codex model_reasoning_effort / omp --thinking
    minimal                         -> low
    ultra                           -> max
    anything else                   -> high (with a note)

If the CLI rejects the effort the call is retried once without it and a note is recorded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

HOSTS = ("claude", "codex", "omp")

STRIPPED_ENV = frozenset(
    {
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_MESSAGING_SOCKET",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_EXECPATH",
        "CLAUDE_CODE_SESSION_ATTENDED",
        "CLAUDE_CODE_ENABLE_TODO_TOOLS",
        "CLAUDE_EFFORT",
        "CLAUDE_PID",
        "CLAUDE_PLUGIN_DATA",
        "CLAUDE_PLUGIN_ROOT",
        "CODEX_THREAD_ID",
        "CODEX_CI",
        "CODEX_SANDBOX",
        "CODEX_SANDBOX_NETWORK_DISABLED",
    }
)
STRIPPED_ENV_PREFIXES = ("CODEX_COMPANION_",)

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
_EFFORT_ALIASES = {"minimal": "low", "ultra": "max"}

CODEX_DISABLED_FEATURES = (
    "apps",
    "plugins",
    "hooks",
    "memories",
    "multi_agent",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "image_generation",
    "in_app_browser",
    "tool_suggest",
    "skill_mcp_dependency_install",
    "realtime_conversation",
    "goals",
    "plugin_sharing",
    "remote_plugin",
    "skill_search",
)

CLAUDE_TOOLS = "Read,Grep,Glob"
OMP_TOOLS = "read,grep,glob"

OMP_OVERLAY_NAME = "omp-overlay.yml"
OMP_OVERLAY = """\
mcp:
  enableProjectConfig: false
memory:
  backend: "off"
autolearn:
  enabled: false
advisor:
  enabled: false
skillful: false
skills:
  enabled: false
fetch:
  enabled: false
web_search:
  enabled: false
"""

_EFFORT_REJECTED = re.compile(r"effort|reasoning|thinking", re.IGNORECASE)


class HostError(RuntimeError):
    pass


class ResumeFailed(HostError):
    """The session could not be resumed; replay the history into a fresh session."""


class HostTimeout(HostError):
    pass


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    env: dict[str, str]
    stdin: str


@dataclass(frozen=True)
class HostResult:
    text: str
    session: str
    notes: list[str] = field(default_factory=list)


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base is None else base
    return {
        key: value
        for key, value in source.items()
        if key not in STRIPPED_ENV and not key.startswith(STRIPPED_ENV_PREFIXES)
    }


def normalize_effort(effort: str | None) -> tuple[str | None, str | None]:
    """Return (native-level, note). `None` means no effort option is sent."""
    if effort is None:
        return None, None
    level = effort.strip().lower()
    level = _EFFORT_ALIASES.get(level, level)
    if level in EFFORT_LEVELS:
        return level, None
    return "high", f"unknown effort {effort!r}; using high"


def default_state_dir() -> Path:
    override = os.environ.get("REVIEW_OFFLINE_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "review-offline"


def _jsonl(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def parse_claude(stdout: str) -> tuple[str, str]:
    """Accepts `--output-format json` (object or array) and `stream-json` output."""
    events: list[dict] = []
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError:
        events = _jsonl(stdout)
    else:
        events = document if isinstance(document, list) else [document]
    results = [e for e in events if isinstance(e, dict) and e.get("type") == "result"]
    if not results:
        raise HostError("claude produced no result event")
    result = results[-1]
    text = result.get("result")
    if result.get("is_error"):
        raise HostError(f"claude reported an error: {text or result.get('subtype')}")
    session = result.get("session_id")
    if not isinstance(text, str) or not text.strip() or not session:
        raise HostError("claude result lacks a session id or final text")
    return session, text


def parse_codex(stdout: str) -> tuple[str, str]:
    events = _jsonl(stdout)
    session = next(
        (
            e["thread_id"]
            for e in events
            if e.get("type") == "thread.started" and e.get("thread_id")
        ),
        None,
    )
    failed = [e for e in events if e.get("type") in ("turn.failed", "error")]
    if failed:
        # Prefer a turn.failed's detail over a later, unrelated protocol error.
        event = next((e for e in failed if e.get("type") == "turn.failed"), failed[0])
        detail = event.get("error", {}).get("message") or event.get("message")
        raise HostError(f"codex {event.get('type')}: {detail}")
    messages = [
        e["item"]["text"]
        for e in events
        if e.get("type") == "item.completed"
        and e.get("item", {}).get("type") == "agent_message"
        and isinstance(e["item"].get("text"), str)
    ]
    if not session or not messages or not messages[-1].strip():
        raise HostError("codex produced no thread id or final agent message")
    return session, messages[-1]


def parse_omp(stdout: str) -> tuple[str, str]:
    events = _jsonl(stdout)
    session = next((e["id"] for e in events if e.get("type") == "session" and e.get("id")), None)
    final = None
    for event in events:
        message = event.get("message")
        is_assistant_end = event.get("type") == "message_end" and isinstance(message, dict)
        if is_assistant_end and message.get("role") == "assistant":
            final = message
    if not session or final is None:
        raise HostError("omp produced no session id or assistant message")
    if final.get("stopReason") in ("error", "aborted"):
        raise HostError(f"omp stopped with {final['stopReason']}: {final.get('errorMessage')}")
    content = final.get("content")
    if isinstance(content, str):
        text = content
    else:
        text = "".join(
            part.get("text", "")
            for part in content or []
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if not text.strip():
        raise HostError("omp final message has no text")
    return session, text


class Host:
    name = ""
    binary = ""

    def __init__(self, model: str | None = None):
        self.model = model

    def build_command(
        self,
        prompt: str,
        *,
        session: str | None = None,
        effort: str | None = "high",
        readonly_dirs: Sequence[str | Path] = (),
        cwd: str | Path = ".",
        support_dir: Path | None = None,
        session_id: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Command:
        raise NotImplementedError

    def parse(self, stdout: str) -> tuple[str, str]:
        raise NotImplementedError

    def prepare(self, support_dir: Path) -> None:
        pass

    def run(
        self,
        prompt: str,
        *,
        cwd: str | Path,
        session: str | None = None,
        effort: str = "high",
        readonly_dirs: Sequence[str | Path] = (),
        timeout: float = 600,
    ) -> HostResult:
        notes: list[str] = []
        if not self.model:
            notes.append(
                f"model not pinned: {self.name} runs on its built-in default model, ignoring your settings"
            )
        level, note = normalize_effort(effort)
        if note:
            notes.append(note)
        support_dir = default_state_dir()
        self.prepare(support_dir)
        env = child_env()
        if shutil.which(self.binary, path=env.get("PATH")) is None:
            raise HostError(f"{self.binary!r} not found on PATH")

        attempts = [level, None] if level else [None]
        for current in attempts:
            command = self.build_command(
                prompt,
                session=session,
                effort=current,
                readonly_dirs=readonly_dirs,
                cwd=cwd,
                support_dir=support_dir,
                env=env,
            )
            try:
                code, out, err = _spawn(command, cwd, timeout)
            except HostTimeout as exc:
                # A timed-out resume must be recoverable like any other resume failure.
                if session:
                    raise ResumeFailed(str(exc)) from None
                raise
            if code != 0 and current and _EFFORT_REJECTED.search(out + err):
                notes.append(f"effort ignored by {self.name}")
                continue
            if "Unknown --effort" in err and current:
                notes.append(f"effort ignored by {self.name}")
            break

        failure = None
        if code != 0:
            failure = f"{self.binary} exited {code}: {(err or out).strip()[-800:]}"
        else:
            try:
                found_session, text = self.parse(out)
            except HostError as exc:
                failure = str(exc)
        if failure:
            raise (ResumeFailed if session else HostError)(failure)
        return HostResult(text=text, session=found_session, notes=notes)


class ClaudeHost(Host):
    name = binary = "claude"

    def build_command(
        self,
        prompt,
        *,
        session=None,
        effort="high",
        readonly_dirs=(),
        cwd=".",
        support_dir=None,
        session_id=None,
        env=None,
    ):
        argv = [
            self.binary,
            "-p",
            "--tools",
            CLAUDE_TOOLS,
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--disable-slash-commands",
            "--permission-mode",
            "dontAsk",
            "--restricted",
            "--output-format",
            "json",
        ]
        if session:
            argv += ["--resume", session]
        else:
            argv += ["--session-id", session_id or str(uuid.uuid4())]
        if effort:
            argv += ["--effort", effort]
        if self.model:
            argv += ["--model", self.model]
        for directory in readonly_dirs:
            argv += ["--add-dir", str(directory)]
        return Command(tuple(argv), child_env(env), prompt)

    def parse(self, stdout):
        return parse_claude(stdout)


class CodexHost(Host):
    name = binary = "codex"

    def build_command(
        self,
        prompt,
        *,
        session=None,
        effort="high",
        readonly_dirs=(),
        cwd=".",
        support_dir=None,
        session_id=None,
        env=None,
    ):
        # codex's read-only sandbox limits writes, not reads: there is no read-confinement
        # flag, so unlike claude/omp (--add-dir plus a read-only tool set) the child can
        # read anywhere the invoking user can. Documented in SKILL.md's limitations.
        argv = [self.binary, "exec"]
        if session:
            argv += ["resume", session]
        else:
            argv += ["--sandbox", "read-only"]
        argv += [
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--json",
            "-c",
            'sandbox_mode="read-only"',
            "-c",
            'web_search="disabled"',
            # Belt and braces: force the MCP server map empty no matter which config
            # scope a future codex release teaches to load (verified on codex 0.160).
            "-c",
            "mcp_servers={}",
        ]
        for feature in CODEX_DISABLED_FEATURES:
            argv += ["-c", f"features.{feature}=false"]
        if effort:
            argv += ["-c", f'model_reasoning_effort="{effort}"']
        if self.model:
            argv += ["-m", self.model]
        argv.append("-")
        return Command(tuple(argv), child_env(env), prompt)

    def parse(self, stdout):
        return parse_codex(stdout)


class OmpHost(Host):
    name = binary = "omp"

    def prepare(self, support_dir: Path) -> None:
        support_dir.mkdir(parents=True, exist_ok=True)
        overlay = support_dir / OMP_OVERLAY_NAME
        if not overlay.exists() or overlay.read_text() != OMP_OVERLAY:
            overlay.write_text(OMP_OVERLAY)

    def build_command(
        self,
        prompt,
        *,
        session=None,
        effort="high",
        readonly_dirs=(),
        cwd=".",
        support_dir=None,
        session_id=None,
        env=None,
    ):
        support = support_dir or default_state_dir()
        # omp resumes into the cwd the session was created in and looks ids up globally, so
        # sessions are stored per cwd: a resume from another cwd then fails cleanly.
        cwd_key = hashlib.sha1(str(Path(cwd).resolve()).encode()).hexdigest()[:16]
        argv = [
            self.binary,
            "-p",
            "--config",
            str(support / OMP_OVERLAY_NAME),
            "--session-dir",
            str(support / "omp-sessions" / cwd_key),
            "--no-extensions",
            "--no-skills",
            "--no-rules",
            "--no-lsp",
            "--tools",
            OMP_TOOLS,
            "--mode",
            "json",
        ]
        if session:
            argv += ["-r", session]
        if effort:
            argv += ["--thinking", effort]
        if self.model:
            argv += ["--model", self.model]
        for directory in readonly_dirs:
            argv += ["--add-dir", str(directory)]
        return Command(tuple(argv), child_env(env), prompt)

    def parse(self, stdout):
        return parse_omp(stdout)


_HOST_CLASSES = {"claude": ClaudeHost, "codex": CodexHost, "omp": OmpHost}


def get_host(name: str, model: str | None = None) -> Host:
    if not name:
        raise ValueError(f"no host given; pass one of: {', '.join(HOSTS)}")
    try:
        return _HOST_CLASSES[name](model or None)
    except KeyError:
        raise ValueError(f"unknown host {name!r}; expected one of: {', '.join(HOSTS)}") from None


_ACTIVE: set[subprocess.Popen] = set()
_ACTIVE_LOCK = threading.Lock()


def terminate_all() -> None:
    """Kill every child still running; used when the review server shuts down."""
    with _ACTIVE_LOCK:
        running = list(_ACTIVE)
    for process in running:
        _kill_group(process)


def _spawn(command: Command, cwd: str | Path, timeout: float) -> tuple[int, str, str]:
    process = subprocess.Popen(
        command.argv,
        cwd=cwd,
        env=command.env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    with _ACTIVE_LOCK:
        _ACTIVE.add(process)
    try:
        out, err = process.communicate(command.stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        process.communicate()
        raise HostTimeout(f"{command.argv[0]} timed out after {timeout:g}s") from None
    except BaseException:
        _kill_group(process)
        raise
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(process)
    return process.returncode, out, err


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
