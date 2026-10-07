import re

from review_offline.markdown import render, write

CHANGESET = {
    "target": "pr:7",
    "title": "Add thing",
    "base": {"sha": "b" * 7},
    "head": {"sha": "h" * 7},
    "files": [],
}


def anchor(path="a.py", start=1, end=1, side="new"):
    return {"scope": "line", "path": path, "side": side, "start": start, "end": end, "hash": "x"}


def comment(cid, anc, body="body", label="nit", status="accepted", suggestion=None, **kw):
    return {
        "id": cid,
        "anchor": anc,
        "label": label,
        "body": body,
        "suggestion": suggestion,
        "origin": "user",
        "sources": [],
        "verdict": None,
        "status": status,
        "stale": False,
        **kw,
    }


def state(*comments, summary="all good"):
    return {
        "target": "pr:7",
        "base_sha": "b" * 7,
        "head_sha": "h" * 7,
        "summary": summary,
        "updated_at": "2026-10-07T10:00:00+00:00",
        "comments": list(comments),
    }


def headings(text):
    return [ln for ln in text.splitlines() if re.match(r"#{1,6} ", ln)]


def test_header_and_summary():
    out = render(state(), CHANGESET)
    assert out.startswith("# Review: Add thing\n\n- Target: pr:7\n")
    assert f"- Base: {'b' * 7} → Head: {'h' * 7}\n- Reviewed: 2026-10-07\n" in out
    assert "## Summary\n\nall good\n\n## Comments\n" in out
    assert out.endswith("\n") and not out.endswith("\n\n")


def test_empty_review():
    out = render(state(summary=""), CHANGESET)
    assert "_No summary._" in out and "_No comments._" in out
    assert headings(out) == ["# Review: Add thing", "## Summary", "## Comments"]
    assert out.endswith("_No comments._\n")


def test_only_accepted_rendered_stale_tagged():
    out = render(
        state(
            comment("c1", anchor(), "kept", status="accepted"),
            comment("c2", anchor(start=2, end=2), "pending one", status="pending"),
            comment("c3", anchor(start=3, end=3), "rejected one", status="rejected"),
            comment("c4", anchor(start=4, end=4), "old news", stale=True),
        ),
        CHANGESET,
    )
    assert "kept" in out and "old news" in out
    assert "pending one" not in out and "rejected one" not in out
    assert "- **L4 (new) · nit** (stale) — old news" in out
    assert "(stale)" not in out.split("old news")[0].split("L4")[0]


def test_ordering_files_lines_general():
    out = render(
        state(
            comment("c1", {"scope": "pr"}, "general", label="question"),
            comment("c2", anchor("b.py", 1, 1), "b-line"),
            comment("c3", anchor("a.py", 9, 9), "a-nine"),
            comment("c4", anchor("a.py", 2, 3), "a-two"),
            comment("c5", {"scope": "file", "path": "a.py"}, "a-file"),
            comment("c6", anchor("a.py", 2, 2, side="new"), "a-new-two"),
            comment("c7", anchor("a.py", 2, 2, side="old"), "a-old-two"),
        ),
        CHANGESET,
    )
    assert headings(out)[3:] == ["### a.py", "### b.py", "### General"]
    order = ["a-file", "a-old-two", "a-new-two", "a-two", "a-nine", "b-line", "general"]
    positions = [out.index(text) for text in order]
    assert positions == sorted(positions)


def test_line_labels():
    out = render(
        state(
            comment("c1", anchor(start=10, end=12), "r", label="blocking"),
            comment("c2", anchor(start=20, end=20, side="old"), "s"),
            comment("c3", {"scope": "file", "path": "a.py"}, "f", label="question"),
            comment("c4", {"scope": "pr"}, "g", label="question"),
        ),
        CHANGESET,
    )
    assert "- **L10-12 (new) · blocking** — r" in out
    assert "- **L20 (old) · nit** — s" in out
    assert "- **file · question** — f" in out
    assert "- **question** — g" in out


def test_suggestion_fenced_with_longer_backticks():
    suggestion = "x = '''```'''\ny = '````'"
    out = render(state(comment("c1", anchor(), "b", suggestion=suggestion)), CHANGESET)
    assert "  `````suggestion\n  x = '''```'''\n  y = '````'\n  `````\n" in out


def test_suggestion_default_fence_and_empty_suggestion():
    out = render(state(comment("c1", anchor(), "b", suggestion="new line")), CHANGESET)
    assert "  ```suggestion\n  new line\n  ```\n" in out
    out = render(state(comment("c1", anchor(), "b", suggestion="")), CHANGESET)
    assert "  ```suggestion\n  ```\n" in out
    assert "suggestion" not in render(state(comment("c1", anchor(), "b")), CHANGESET)


def hostile_body():
    return "first line\n# fake heading\n  ## indented heading\n```python\ncode\n```\n~~~\nTitle\n---\n=====\n<script>\n"


def test_hostile_body_cannot_create_heading_or_close_fence():
    out = render(
        state(comment("c1", anchor(), hostile_body(), label="blocking", suggestion="s ``` t")),
        CHANGESET,
    )
    assert headings(out) == ["# Review: Add thing", "## Summary", "## Comments", "### a.py"]
    for ln in out.split("### a.py")[1].splitlines():
        stripped = ln.strip()
        assert not stripped.startswith(("```python", "~~~", "<script>", "# ", "## "))
        assert stripped not in {"---", "====="}
    assert "  ````suggestion\n  s ``` t\n  ````\n" in out
    assert out.count("````suggestion") == 1


def test_hostile_summary_is_defused():
    out = render(state(summary="# Top\n```\n## Comments\n---"), CHANGESET)
    assert headings(out) == ["# Review: Add thing", "## Summary", "## Comments"]
    assert not any(ln.startswith("`") for ln in out.splitlines())


def test_continuation_lines_stay_in_list_item():
    out = render(state(comment("c1", anchor(), "one\n\ntwo\nthree")), CHANGESET)
    assert "- **L1 (new) · nit** — one\n\n  two\n  three\n" in out


def test_crlf_and_nul_normalised():
    out = render(state(comment("c1", anchor(), "a\r\nb\rc\x00")), CHANGESET)
    assert "\r" not in out and "\x00" not in out
    assert "— a\n  b\n  c�\n" in out


def test_title_newlines_collapsed():
    cs = CHANGESET | {"title": "multi\n## line"}
    assert render(state(), cs).splitlines()[0] == "# Review: multi ## line"


def test_write_is_atomic_and_overwrites(tmp_path):
    path = tmp_path / "sub" / "pr-7.md"
    write(state(comment("c1", anchor(), "x")), CHANGESET, path)
    assert path.read_text() == render(state(comment("c1", anchor(), "x")), CHANGESET)
    write(state(), CHANGESET, path)
    assert "_No comments._" in path.read_text()
    assert [p.name for p in path.parent.iterdir()] == ["pr-7.md"]
