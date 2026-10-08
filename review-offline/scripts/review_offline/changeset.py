"""Resolve a review target into a changeset: parsed diff, base/head, and the tree to read."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

WORKING_TREE = "working-tree"
DIFF_FLAGS = (
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "-M",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)

LOCKFILES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "deno.lock",
        "uv.lock",
        "pixi.lock",
        "poetry.lock",
        "pdm.lock",
        "pipfile.lock",
        "cargo.lock",
        "go.sum",
        "gemfile.lock",
        "composer.lock",
        "mix.lock",
        "pubspec.lock",
        "podfile.lock",
        "cartfile.resolved",
        "flake.lock",
        "gradle.lockfile",
        "packages.lock.json",
        "package.resolved",
    }
)
MINIFIED_SUFFIXES = (".min.js", ".min.mjs", ".min.css")
GENERATED_NAME = re.compile(r"(\.generated\.|\.g\.dart$|_pb2(_grpc)?\.pyi?$|\.pb\.go$)")
VENDORED_DIRS = frozenset(
    {"node_modules", "vendor", "third_party", "dist", "__generated__", "generated", ".yarn"}
)

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_PR_NUMBER_RE = re.compile(r"^(?:pr:)?#?(\d+)$")
_PR_URL_RE = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)(?:[/?#].*)?$")
_UNSAFE_SLUG_CHARS = re.compile(r"[^\w.+@-]")
_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, '"': 34, "\\": 92}
_PR_FIELDS = "number,title,body,url,baseRefName,baseRefOid,headRefName,headRefOid,comments,reviews"

Runner = Callable[[Sequence[str], "str | Path"], "subprocess.CompletedProcess[str]"]


class ChangesetError(RuntimeError):
    pass


def default_runner(argv: Sequence[str], cwd: str | Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"}
    try:
        proc = subprocess.run(
            list(argv),
            cwd=cwd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=300,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ChangesetError(f"command not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ChangesetError(f"command timed out: {shlex.join(argv)}") from exc
    return subprocess.CompletedProcess(
        list(argv),
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def _unquote(token: str) -> str:
    body = (
        token[1:-1] if token.startswith('"') and token.endswith('"') and len(token) > 1 else token
    )
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\" or i + 1 >= len(body):
            out += ch.encode("utf-8")
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in "01234567":
            digits = re.match(r"[0-7]{1,3}", body[i + 1 :])
            assert digits is not None
            out.append(int(digits.group(), 8) & 0xFF)
            i += 1 + len(digits.group())
        elif nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            i += 2
        else:
            out += nxt.encode("utf-8")
            i += 2
    return out.decode("utf-8", "replace")


def _read_quoted(text: str) -> tuple[str, str]:
    i = 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return _unquote(text[: i + 1]), text[i + 1 :].lstrip(" ")
        i += 1
    return _unquote(text), ""


def _strip_prefix(path: str, prefix: str) -> str:
    return path.removeprefix(prefix)


def _split_git_header(rest: str) -> tuple[str, str]:
    if rest.startswith('"'):
        old, tail = _read_quoted(rest)
        new = _read_quoted(tail)[0] if tail.startswith('"') else tail
    elif (quoted := rest.find(' "b/')) != -1:
        old, new = rest[:quoted], _read_quoted(rest[quoted + 1 :])[0]
    else:
        half = (len(rest) - 1) // 2
        if len(rest) % 2 == 1 and rest[half] == " " and rest[2:half] == rest[half + 3 :]:
            old, new = rest[:half], rest[half + 1 :]
        else:
            old, _, new = rest.partition(" b/")
            new = "b/" + new
    return _strip_prefix(old, "a/"), _strip_prefix(new, "b/")


def _header_path(value: str, prefix: str) -> str | None:
    value = value.rstrip("\t")
    if value == "/dev/null":
        return None
    path = _unquote(value) if value.startswith('"') else value
    return _strip_prefix(path, prefix)


def _collapse_reason(path: str) -> str | None:
    parts = path.split("/")
    name = parts[-1].lower()
    if name in LOCKFILES or name.endswith(".lock"):
        return "lockfile"
    if name.endswith(MINIFIED_SUFFIXES):
        return "minified"
    if name.endswith(".map"):
        return "source map"
    if GENERATED_NAME.search(name):
        return "generated"
    if VENDORED_DIRS.intersection(parts[:-1]):
        return "vendored"
    return None


def _new_pending(header_rest: str) -> dict:
    old, new = _split_git_header(header_rest)
    return {
        "header_old": old,
        "header_new": new,
        "minus": None,
        "plus": None,
        "rename_from": None,
        "rename_to": None,
        "is_new": False,
        "is_deleted": False,
        "binary": False,
        "hunks": [],
    }


def _apply_header_line(p: dict, line: str) -> None:
    if line.startswith("new file mode"):
        p["is_new"] = True
    elif line.startswith("deleted file mode"):
        p["is_deleted"] = True
    elif line.startswith("rename from "):
        p["rename_from"] = _unquote(line[12:])
    elif line.startswith("rename to "):
        p["rename_to"] = _unquote(line[10:])
    elif line.startswith("copy from "):
        p["rename_from"] = _unquote(line[10:])
    elif line.startswith("copy to "):
        p["rename_to"] = _unquote(line[8:])
        p["is_new"] = True
    elif line.startswith("--- "):
        p["minus"] = _header_path(line[4:], "a/")
        p["is_new"] = p["is_new"] or p["minus"] is None
    elif line.startswith("+++ "):
        p["plus"] = _header_path(line[4:], "b/")
        p["is_deleted"] = p["is_deleted"] or p["plus"] is None
    elif line.startswith(("Binary files ", "GIT binary patch")):
        p["binary"] = True


def _read_hunk(lines: list[str], i: int, match: re.Match[str], pending: dict) -> int:
    old_count = 1 if match[2] is None else int(match[2])
    new_count = 1 if match[4] is None else int(match[4])
    hunk = {
        "header": lines[i],
        "old_start": int(match[1]),
        "new_start": int(match[3]),
        "lines": [],
    }
    o, n = hunk["old_start"], hunk["new_start"]
    i += 1
    while (old_count > 0 or new_count > 0) and i < len(lines):
        raw = lines[i]
        if raw.startswith("\\"):
            i += 1
            continue
        tag, text = raw[:1], raw[1:]
        if tag == "+" and new_count > 0:
            hunk["lines"].append({"t": "add", "o": None, "n": n, "text": text})
            n += 1
            new_count -= 1
        elif tag == "-" and old_count > 0:
            hunk["lines"].append({"t": "del", "o": o, "n": None, "text": text})
            o += 1
            old_count -= 1
        elif tag in (" ", "") and old_count > 0 and new_count > 0:
            hunk["lines"].append({"t": "ctx", "o": o, "n": n, "text": text})
            o += 1
            n += 1
            old_count -= 1
            new_count -= 1
        else:
            break
        i += 1
    while i < len(lines) and lines[i].startswith("\\"):
        i += 1
    pending["hunks"].append(hunk)
    return i


def _finalize(p: dict) -> dict:
    old_path: str | None = None
    if p["is_new"]:
        status = "added"
        path = p["rename_to"] or p["plus"] or p["header_new"]
    elif p["is_deleted"]:
        status = "deleted"
        path = p["minus"] or p["header_old"]
    elif p["rename_from"] is not None and p["rename_to"] is not None:
        status = "renamed"
        path, old_path = p["rename_to"], p["rename_from"]
    else:
        status = "modified"
        path = p["plus"] or p["minus"] or p["header_new"]
    additions = sum(1 for h in p["hunks"] for line in h["lines"] if line["t"] == "add")
    deletions = sum(1 for h in p["hunks"] for line in h["lines"] if line["t"] == "del")
    reason = _collapse_reason(path)
    return {
        "path": path,
        "old_path": old_path,
        "status": status,
        "binary": p["binary"],
        "additions": additions,
        "deletions": deletions,
        "collapsed": reason is not None,
        "collapse_reason": reason,
        "hunks": p["hunks"],
    }


def parse_diff(text: str) -> list[dict]:
    """Parse `git diff` output into the changeset `files` structure."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    pendings: list[dict] = []
    current: dict | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            current = _new_pending(line[11:])
            pendings.append(current)
            i += 1
            continue
        if current is not None and (match := _HUNK_RE.match(line)):
            i = _read_hunk(lines, i, match, current)
            continue
        if current is not None:
            _apply_header_line(current, line)
        i += 1
    return [_finalize(p) for p in pendings]


class _Git:
    def __init__(self, runner: Runner, repo: Path) -> None:
        self.runner = runner
        self.repo = repo

    def run(self, argv: Sequence[str], cwd: Path | None = None, ok: tuple[int, ...] = (0,)) -> str:
        proc = self.runner(list(argv), cwd or self.repo)
        if proc.returncode not in ok:
            detail = (proc.stderr or "").strip()
            raise ChangesetError(
                f"command failed (exit {proc.returncode}): {shlex.join(argv)}"
                + (f": {detail}" if detail else "")
            )
        return proc.stdout or ""

    def out(self, *args: str, ok: tuple[int, ...] = (0,)) -> str:
        return self.run(["git", "--no-optional-locks", *args], ok=ok)

    def line(self, *args: str) -> str:
        return self.out(*args).strip()

    def try_line(self, *args: str) -> str | None:
        try:
            return self.line(*args) or None
        except ChangesetError:
            return None

    def rev(self, rev: str) -> str | None:
        return self.try_line("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")

    def gh(self, *args: str) -> str:
        return self.run(["gh", *args])


def _sanitize_slug(name: str) -> str:
    return _UNSAFE_SLUG_CHARS.sub("-", name.replace("/", "-"))


def _current_branch(g: _Git) -> str | None:
    return g.try_line("symbolic-ref", "--quiet", "--short", "HEAD")


def _default_branch(g: _Git) -> str | None:
    candidates = []
    if remote_head := g.try_line("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"):
        candidates.append(remote_head)
    candidates += ["origin/main", "origin/master", "main", "master"]
    return next((c for c in candidates if g.rev(c)), None)


def _short_name(ref: str) -> str:
    return ref.removeprefix("origin/")


def _is_branch(g: _Git, name: str) -> bool:
    return any(_ref_exists(g, f"refs/{kind}/{name}") for kind in ("heads", "remotes"))


def _ref_exists(g: _Git, ref: str) -> bool:
    try:
        g.out("show-ref", "--verify", "--quiet", ref)
    except ChangesetError:
        return False
    return True


def _slug_for_rev(g: _Git, rev: str, sha: str) -> str:
    if rev == "HEAD":
        branch = _current_branch(g)
        return _sanitize_slug(branch) if branch else f"head-{sha[:7]}"
    if _is_branch(g, rev):
        return _sanitize_slug(rev)
    return f"head-{sha[:7]}"


def _parse_pr(target: str) -> tuple[int, str, str | None] | None:
    if match := _PR_URL_RE.match(target):
        owner, name, number = match.groups()
        return int(number), target, f"{owner}/{name}"
    if match := _PR_NUMBER_RE.match(target):
        return int(match[1]), match[1], None
    return None


def _split_range(target: str) -> tuple[str, str, bool] | None:
    for sep, three in (("...", True), ("..", False)):
        if sep in target:
            left, _, right = target.partition(sep)
            return left or "HEAD", right or "HEAD", three
    return None


def _classify(g: _Git, repo: Path, target: str | None) -> dict:
    target = (target or "").strip()
    if target in ("", WORKING_TREE):
        return {"kind": "worktree", "target": WORKING_TREE, "pathspec": None}
    if pr := _parse_pr(target):
        number, ref, slug_repo = pr
        return {
            "kind": "pr",
            "target": f"pr:{number}",
            "number": number,
            "ref": ref,
            "repo": slug_repo,
        }
    candidate = Path(target) if Path(target).is_absolute() else repo / target
    if (rng := _split_range(target)) and not candidate.exists():
        left, right, three = rng
        return {"kind": "range", "target": target, "left": left, "right": right, "three": three}
    if g.rev(target):
        return {"kind": "rev", "target": target, "rev": target}
    if candidate.exists():
        try:
            rel = candidate.resolve().relative_to(repo.resolve())
        except ValueError as exc:
            raise ChangesetError(f"path {target!r} is outside the repository {repo}") from exc
        return {"kind": "worktree", "target": target, "pathspec": f":(literal){rel.as_posix()}"}
    raise ChangesetError(
        f"cannot resolve target {target!r}: not a PR, revision, range or existing path"
    )


def _toplevel(runner: Runner, repo: Path) -> Path:
    return Path(_Git(runner, repo).line("rev-parse", "--show-toplevel"))


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]


def _slug(g: _Git, spec: dict) -> str:
    kind = spec["kind"]
    if kind == "pr":
        return f"pr-{spec['number']}"
    if kind == "worktree":
        branch = _current_branch(g)
        base = _sanitize_slug(branch) if branch else f"head-{_require_rev(g, 'HEAD')[:7]}"
        return base if spec["pathspec"] is None else f"{base}-path-{_short_hash(spec['pathspec'])}"
    name = spec["right"] if kind == "range" else spec["rev"]
    base = _slug_for_rev(g, name, _require_rev(g, name))
    return f"{base}-range-{_short_hash(spec['target'])}" if kind == "range" else base


def _require_rev(g: _Git, rev: str) -> str:
    sha = g.rev(rev)
    if sha is None:
        raise ChangesetError(f"cannot resolve revision {rev!r}")
    return sha


def slug_for(target: str | None, repo: Path, *, runner: Runner | None = None) -> str:
    """The run slug for a target, computed before the run dir exists."""
    runner = runner or default_runner
    top = _toplevel(runner, Path(repo))
    g = _Git(runner, top)
    return _slug(g, _classify(g, top, target))


def _is_shallow(g: _Git) -> bool:
    return g.try_line("rev-parse", "--is-shallow-repository") == "true"


def _merge_base(g: _Git, a: str, b: str) -> str:
    base = g.try_line("merge-base", a, b)
    if base is not None:
        return base
    if _is_shallow(g):
        # Shallow checkouts (actions/checkout, bot checkouts) have no common ancestor.
        try:
            g.out("fetch", "--unshallow")
            base = g.try_line("merge-base", a, b)
        except ChangesetError:
            pass
        if base is not None:
            return base
        raise ChangesetError(
            f"no merge base between {a!r} and {b!r}: the clone is shallow and "
            "unshallowing failed; run `git fetch --unshallow` manually"
        )
    raise ChangesetError(f"no merge base between {a!r} and {b!r}")


def _committed_base(g: _Git, head: str) -> tuple[str, str]:
    default = _default_branch(g)
    if default is not None:
        base = _merge_base(g, default, head)
        if base != head:
            return base, _short_name(default)
    parent = g.rev(f"{head}^")
    if parent is not None:
        return parent, f"{head[:7]}^"
    return g.line("hash-object", "-t", "tree", "/dev/null"), "empty tree"


def _diff(g: _Git, *args: str) -> str:
    return g.out("diff", *DIFF_FLAGS, *args)


def _worktree_changes(g: _Git, pathspec: str | None) -> tuple[str, dict]:
    head = _require_rev(g, "HEAD")
    default = _default_branch(g)
    base = _merge_base(g, default, head) if default else head
    suffix = ["--", pathspec] if pathspec else []
    patch = _diff(g, base, *suffix)
    listing = g.out("ls-files", "--others", "--exclude-standard", "-z", *suffix)
    for name in filter(None, listing.split("\0")):
        patch += g.out("diff", *DIFF_FLAGS, "--no-index", "--", "/dev/null", name, ok=(0, 1))
    branch = _current_branch(g)
    where = branch or head[:7]
    title = f"Changes in {pathspec.removeprefix(':(literal)')}" if pathspec else None
    return patch, {
        "title": title or f"Working tree changes on {where}",
        "base": {"sha": base, "ref": _short_name(default) if default else head[:7]},
        "head": {"sha": head, "ref": branch or "HEAD"},
    }


def _rev_changes(g: _Git, rev: str) -> tuple[str, dict]:
    head = _require_rev(g, rev)
    base, base_ref = _committed_base(g, head)
    ref = (_current_branch(g) or "HEAD") if rev == "HEAD" else rev
    return _diff(g, base, head), {
        "title": g.line("log", "-1", "--format=%s", head),
        "base": {"sha": base, "ref": base_ref},
        "head": {"sha": head, "ref": ref},
    }


def _range_changes(g: _Git, spec: dict) -> tuple[str, dict]:
    left = _require_rev(g, spec["left"])
    right = _require_rev(g, spec["right"])
    base = _merge_base(g, left, right) if spec["three"] else left
    return _diff(g, base, right), {
        "title": spec["target"],
        "base": {"sha": base, "ref": spec["left"]},
        "head": {"sha": right, "ref": spec["right"]},
    }


def _json_values(text: str) -> Iterator[object]:
    decoder = json.JSONDecoder()
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        value, i = decoder.raw_decode(text, i)
        yield value


def _login(entry: dict) -> str:
    return (entry.get("author") or entry.get("user") or {}).get("login") or "unknown"


def _format_comments(view: dict, inline: list[dict], inline_error: str | None) -> str:
    out = [f"# Comments on PR #{view['number']}: {view.get('title', '')}", ""]
    for review in view.get("reviews") or []:
        body = (review.get("body") or "").strip()
        state = review.get("state") or "COMMENTED"
        if body or state != "COMMENTED":
            out += [f"## Review by {_login(review)} ({state})", "", body or "(no text)", ""]
    for comment in view.get("comments") or []:
        out += [f"## Comment by {_login(comment)}", "", (comment.get("body") or "").strip(), ""]
    for comment in inline:
        line = comment.get("line") or comment.get("original_line")
        place = f"{comment.get('path', '?')}:{line}" if line else comment.get("path", "?")
        out += [
            f"## Inline comment by {_login(comment)} on {place}",
            "",
            (comment.get("body") or "").strip(),
            "",
        ]
    if inline_error:
        out += [f"(inline review comments could not be fetched: {inline_error})", ""]
    if len(out) == 2:
        out += ["(no comments)", ""]
    return "\n".join(out)


def _fetch_inline_comments(g: _Git, spec: dict) -> tuple[list[dict], str | None]:
    slug = spec["repo"] or "{owner}/{repo}"
    try:
        raw = g.gh("api", f"repos/{slug}/pulls/{spec['number']}/comments", "--paginate")
        values = list(_json_values(raw))
    except (ChangesetError, ValueError) as exc:
        return [], str(exc)
    flat: list[dict] = []
    for value in values:
        flat += value if isinstance(value, list) else [value]
    return [c for c in flat if isinstance(c, dict)], None


def _pr_changes(g: _Git, spec: dict) -> tuple[str, dict, dict[str, str]]:
    try:
        view = json.loads(g.gh("pr", "view", spec["ref"], "--json", _PR_FIELDS))
    except ValueError as exc:
        raise ChangesetError(f"gh pr view returned invalid JSON: {exc}") from exc
    number = spec["number"]
    g.out("fetch", "--refmap=", "origin", "--", f"pull/{number}/head")
    head = g.line("rev-parse", "--verify", "FETCH_HEAD^{commit}")
    if view.get("headRefOid") and view["headRefOid"] != head:
        raise ChangesetError(
            f"origin pull/{number}/head is {head[:7]} but the PR head is "
            f"{view['headRefOid'][:7]}; is origin the PR's repository?"
        )
    tip = view.get("baseRefOid")
    if not (tip and g.rev(tip)):
        g.out("fetch", "--refmap=", "origin", "--", view["baseRefName"])
        tip = g.line("rev-parse", "--verify", "FETCH_HEAD^{commit}")
    base = _merge_base(g, tip, head)
    inline, inline_error = _fetch_inline_comments(g, spec)
    pr_md = f"# {view.get('title', '')}\n\n{view.get('url', '')}\n\n{view.get('body') or ''}\n"
    prefetch = {
        "pr.md": pr_md,
        "pr-comments.md": _format_comments(view, inline, inline_error),
    }
    return (
        _diff(g, base, head),
        {
            "title": view.get("title") or f"PR #{number}",
            "base": {"sha": base, "ref": view.get("baseRefName")},
            "head": {"sha": head, "ref": view.get("headRefName")},
        },
        prefetch,
    )


def _is_checked_out(g: _Git, sha: str) -> bool:
    return g.try_line("rev-parse", "HEAD") == sha and not g.line(
        "status", "--porcelain", "--untracked-files=no"
    )


def _ensure_worktree(g: _Git, run_dir: Path, sha: str) -> Path:
    path = run_dir / "worktree"
    if path.exists():
        existing = _Git(g.runner, path).try_line("rev-parse", "HEAD")
        if existing == sha:
            return path
        cleanup_worktree(g.repo, run_dir, runner=g.runner)
    g.out("worktree", "add", "--detach", str(path), sha)
    return path


def resolve(target: str | None, repo: Path, run_dir: Path, *, runner: Runner | None = None) -> dict:
    """Resolve `target` to a changeset dict and write it, with prefetch files, under `run_dir`."""
    runner = runner or default_runner
    top = _toplevel(runner, Path(repo))
    g = _Git(runner, top)
    run_dir = Path(run_dir).resolve()
    spec = _classify(g, top, target)

    prefetch: dict[str, str] = {}
    if spec["kind"] == "pr":
        patch, meta, prefetch = _pr_changes(g, spec)
    elif spec["kind"] == "worktree":
        patch, meta = _worktree_changes(g, spec["pathspec"])
    elif spec["kind"] == "range":
        patch, meta = _range_changes(g, spec)
    else:
        patch, meta = _rev_changes(g, spec["rev"])

    slug = _slug(g, spec)
    run_dir.mkdir(parents=True, exist_ok=True)
    if spec["kind"] == "worktree" or _is_checked_out(g, meta["head"]["sha"]):
        root = top
    else:
        root = _ensure_worktree(g, run_dir, meta["head"]["sha"])

    changeset = {
        "target": spec["target"],
        "title": meta["title"],
        "slug": slug,
        "base": meta["base"],
        "head": meta["head"],
        "root": str(root),
        "files": parse_diff(patch),
    }

    prefetch_dir = run_dir / "prefetch"
    prefetch_dir.mkdir(exist_ok=True)
    _write(prefetch_dir / "diff.patch", patch)
    for name, content in prefetch.items():
        _write(prefetch_dir / name, content)
    _write(run_dir / "changeset.json", json.dumps(changeset, indent=2, ensure_ascii=False) + "\n")
    return changeset


def _write(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def cleanup_worktree(repo: Path, run_dir: Path, *, runner: Runner | None = None) -> None:
    """Remove `run_dir/worktree` and prune its git metadata; safe to call repeatedly."""
    runner = runner or default_runner
    repo, path = Path(repo), Path(run_dir) / "worktree"
    git = ["git", "--no-optional-locks"]

    def attempt(argv: list[str]) -> None:
        try:
            runner(argv, repo)
        except (ChangesetError, OSError):
            pass

    if not repo.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    if path.exists():
        attempt([*git, "worktree", "remove", "--force", str(path)])
        shutil.rmtree(path, ignore_errors=True)
    attempt([*git, "worktree", "prune"])
