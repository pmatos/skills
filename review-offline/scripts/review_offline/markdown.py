"""Render the accepted comments of a review as a markdown document."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from .store import atomic_write

_HEADING = re.compile(r"^(\s*)(#{1,6})(?=\s|$)")
_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})")
_SETEXT = re.compile(r"^(\s*)([=-])[=-]*\s*$")
_HTML = re.compile(r"^(\s*)<")
_BACKTICKS = re.compile(r"`+")
_SIDE_ORDER = {"old": 0, "new": 1}


def _oneline(text: object) -> str:
    return " ".join(str(text).split())


def _lines(text: str) -> list[str]:
    return text.replace("\x00", "�").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _defuse(line: str) -> str:
    """Backslash-escape a line start that would open a heading, fence, setext rule or HTML block."""
    for pattern in (_HEADING, _FENCE, _SETEXT, _HTML):
        match = pattern.match(line)
        if match:
            cut = match.end(1)
            return f"{line[:cut]}\\{line[cut:]}"
    return line


def _block(text: str, indent: str = "", inline_first: bool = False) -> list[str]:
    out = []
    for i, line in enumerate(_lines(text.strip())):
        line = line.rstrip() if inline_first and i == 0 else _defuse(line.rstrip())
        out.append(f"{indent}{line}" if line else "")
    return out


def _fenced(text: str, indent: str) -> list[str]:
    longest = max((len(run) for run in _BACKTICKS.findall(text)), default=0)
    fence = "`" * max(3, longest + 1)
    body = [f"{indent}{line}" if line else "" for line in _lines(text)] if text else []
    return [f"{indent}{fence}suggestion", *body, f"{indent}{fence}"]


def _id_number(comment: dict) -> int:
    digits = "".join(ch for ch in str(comment.get("id", "")) if ch.isdigit())
    return int(digits) if digits else 0


def _line_key(comment: dict) -> tuple:
    a = comment["anchor"]
    return (a["start"], _SIDE_ORDER.get(a["side"], 2), a["end"], _id_number(comment))


def _heading(comment: dict) -> str:
    anchor = comment["anchor"]
    label = comment["label"]
    if anchor["scope"] == "line":
        start, end = anchor["start"], anchor["end"]
        span = f"L{start}" if start == end else f"L{start}-{end}"
        return f"{span} ({anchor['side']}) · {label}"
    if anchor["scope"] == "file":
        return f"file · {label}"
    return label


def _comment(comment: dict) -> list[str]:
    tag = " (stale)" if comment.get("stale") else ""
    body = _block(comment.get("body") or "", "  ", inline_first=True)
    first = body[0].strip() if body else ""
    head = f"- **{_heading(comment)}**{tag}" + (f" — {first}" if first else "")
    out = [head, *body[1:]]
    suggestion = comment.get("suggestion")
    if suggestion is not None:
        out += ["", *_fenced(suggestion, "  ")]
    return out


def _section(comments: list[dict]) -> list[str]:
    out: list[str] = []
    for comment in comments:
        out += _comment(comment)
        out.append("")
    return out


def render(state: dict, changeset: dict) -> str:
    target = state.get("target") or changeset.get("target") or "unknown"
    title = _oneline(changeset.get("title") or target)
    base = state.get("base_sha") or changeset.get("base", {}).get("sha") or "unknown"
    head = state.get("head_sha") or changeset.get("head", {}).get("sha") or "unknown"
    date = str(state.get("updated_at") or "")[:10] or datetime.now(UTC).strftime("%Y-%m-%d")

    out = [
        f"# Review: {title}",
        "",
        f"- Target: {_oneline(target)}",
        f"- Base: {_oneline(base)} → Head: {_oneline(head)}",
        f"- Reviewed: {_oneline(date)}",
        "",
        "## Summary",
        "",
    ]
    summary = (state.get("summary") or "").strip()
    out += _block(summary) if summary else ["_No summary._"]
    out += ["", "## Comments", ""]

    accepted = [c for c in state.get("comments", []) if c.get("status") == "accepted"]
    by_path: dict[str, list[dict]] = {}
    general: list[dict] = []
    for comment in accepted:
        scope = comment["anchor"]["scope"]
        if scope == "pr":
            general.append(comment)
        else:
            by_path.setdefault(comment["anchor"]["path"], []).append(comment)

    if not accepted:
        out += ["_No comments._", ""]
    for path in sorted(by_path):
        group = by_path[path]
        files = [c for c in group if c["anchor"]["scope"] == "file"]
        lines = [c for c in group if c["anchor"]["scope"] == "line"]
        files.sort(key=_id_number)
        lines.sort(key=_line_key)
        out += [f"### {_oneline(path)}", ""]
        out += _section(files + lines)
    if general:
        general.sort(key=_id_number)
        out += ["### General", ""]
        out += _section(general)

    return "\n".join(out).rstrip("\n") + "\n"


def write(state: dict, changeset: dict, path: str | Path) -> None:
    atomic_write(path, render(state, changeset))
