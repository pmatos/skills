#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0",
# ]
# ///
"""Validate the YAML frontmatter of every skill's SKILL.md.

The skills' `name` / `description` frontmatter is the product surface — it drives
discovery — so a broken or missing block must fail CI. For each `<skill>/SKILL.md`
this checks that the file opens with a `---`-delimited YAML block containing a
non-empty string `name` and `description`, and that `name` matches its directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def frontmatter(text: str) -> dict | None:
    """Return the parsed leading `---`-fenced YAML block, or None if absent/invalid."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    # first line is the opening fence; find the closing fence
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            block = "\n".join(lines[1:idx])
            data = yaml.safe_load(block)
            return data if isinstance(data, dict) else None
    return None


def main() -> int:
    skill_files = sorted(ROOT.glob("*/SKILL.md"))
    if not skill_files:
        print("validate-frontmatter: no */SKILL.md files found", file=sys.stderr)
        return 1

    errors: list[str] = []
    for path in skill_files:
        rel = path.relative_to(ROOT)
        expected_name = path.parent.name
        fm = frontmatter(path.read_text(encoding="utf-8"))
        if fm is None:
            errors.append(f"{rel}: missing or invalid YAML frontmatter block")
            continue
        for field in ("name", "description"):
            value = fm.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{rel}: frontmatter '{field}' must be a non-empty string")
        name = fm.get("name")
        if isinstance(name, str) and name.strip() and name.strip() != expected_name:
            errors.append(
                f"{rel}: frontmatter name '{name.strip()}' does not match directory '{expected_name}'"
            )

    if errors:
        print("Skill frontmatter validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"validate-frontmatter: {len(skill_files)} skill(s) OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
