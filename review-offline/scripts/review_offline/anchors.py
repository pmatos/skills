"""Anchor hashing shared by the diff parser, state store and markdown writer."""

from __future__ import annotations

import hashlib


def line_hash(lines: list[str]) -> str:
    """First 12 hex of SHA-1 over the anchored lines' text joined by newlines."""
    return hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()[:12]


def side_lines(changeset_file: dict, side: str, start: int, end: int) -> list[str] | None:
    """Text of lines start..end (inclusive) on `side` of a changeset file entry.

    Returns None when any line in the range is absent from the diff on that side.
    """
    key = "o" if side == "old" else "n"
    by_number: dict[int, str] = {}
    for hunk in changeset_file.get("hunks", []):
        for line in hunk["lines"]:
            number = line[key]
            if number is not None:
                by_number[number] = line["text"]
    wanted = range(start, end + 1)
    if not all(number in by_number for number in wanted):
        return None
    return [by_number[number] for number in wanted]


def anchor_hash(changeset_file: dict, side: str, start: int, end: int) -> str | None:
    lines = side_lines(changeset_file, side, start, end)
    return None if lines is None else line_hash(lines)
