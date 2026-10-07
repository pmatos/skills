"""Assemble the static page shell: all CSS and JS inlined, no review data."""

from __future__ import annotations

from pathlib import Path

PAGE_DIR = Path(__file__).parent / "page"
SCRIPTS = (
    "vendor/htm-preact-standalone.umd.js",
    "layout.js",
    "viz.js",
    "diff.js",
    "panel.js",
    "app.js",
)


def build_shell() -> str:
    shell = (PAGE_DIR / "shell.html").read_text(encoding="utf-8")
    style = (PAGE_DIR / "style.css").read_text(encoding="utf-8")
    script = "\n;\n".join((PAGE_DIR / name).read_text(encoding="utf-8") for name in SCRIPTS)
    if "</script" in script.lower() or "</style" in style.lower():
        raise ValueError("page asset contains a closing tag that would end its inline block")
    return shell.replace("/*STYLE*/", style).replace("/*SCRIPT*/", script)
