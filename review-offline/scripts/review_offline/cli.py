"""Command line: prepare | validate-graph | serve | cleanup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path

from . import changeset as changeset_mod
from . import graph as graph_mod


def _run_dir_for(slug: str, repo: Path) -> Path:
    repo_id = hashlib.sha1(str(repo).encode("utf-8")).hexdigest()[:8]
    return Path(tempfile.gettempdir()) / "review-offline" / f"{repo_id}-{slug}"


WORKING_TREE_ALIASES = {
    "current-branch",
    "current",
    "branch",
    "this-branch",
    "my-changes",
    "changes",
    "working-tree",
}


def cmd_prepare(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    target = args.target
    if target and target.lower().replace(" ", "-") in WORKING_TREE_ALIASES:
        target = None
    try:
        slug = changeset_mod.slug_for(target, repo)
        run_dir = Path(args.run_dir) if args.run_dir else _run_dir_for(slug, repo)
        run_dir.mkdir(parents=True, exist_ok=True)
        cs = changeset_mod.resolve(target, repo, run_dir)
    except changeset_mod.ChangesetError as exc:
        print(f"prepare failed: {exc}", file=sys.stderr)
        return 1
    if not cs["files"]:
        changeset_mod.cleanup_worktree(repo, run_dir)
        print(f"prepare failed: no changes found for target {cs['target']!r}", file=sys.stderr)
        return 1
    state_path = repo / ".reviews" / f"{cs['slug']}.state.json"
    if args.fresh and state_path.exists():
        state_path.rename(state_path.with_name(state_path.name + ".bak"))
    meta_path = run_dir / "meta.json"
    graph_path = run_dir / "graph.json"
    previous_head = None
    if meta_path.exists():
        previous_head = json.loads(meta_path.read_text(encoding="utf-8")).get("diff_sha")
    diff_sha = hashlib.sha1((run_dir / "prefetch" / "diff.patch").read_bytes()).hexdigest()
    graph_reusable = graph_path.exists() and previous_head == diff_sha
    if graph_path.exists() and not graph_reusable:
        graph_path.unlink()
    meta_path.write_text(
        json.dumps(
            {
                "repo": str(repo),
                "reviews_dir": str(repo / ".reviews"),
                "diff_sha": diff_sha,
            }
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "slug": cs["slug"],
                "target": cs["target"],
                "title": cs["title"],
                "root": cs["root"],
                "base": cs["base"],
                "head": cs["head"],
                "files": [
                    {"path": f["path"], "status": f["status"], "collapsed": f["collapsed"]}
                    for f in cs["files"]
                ],
                "graph_path": str(graph_path),
                "graph_reusable": graph_reusable,
                "resumed": state_path.exists(),
            },
            indent=2,
        )
    )
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    changeset_mod.cleanup_worktree(Path(meta["repo"]), run_dir)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    repo: Path | None = None
    try:
        from .hosts import get_host
        from .passes import Asker, HostService, Passes
        from .server import ReviewServer
        from .store import Store

        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        repo = Path(meta["repo"])
        changeset = json.loads((run_dir / "changeset.json").read_text(encoding="utf-8"))
        graph = json.loads((run_dir / "graph.json").read_text(encoding="utf-8"))
        known = frozenset(f["path"] for f in changeset["files"])
        errors = graph_mod.validate(graph, root=Path(changeset["root"]), known_paths=known)
        if errors:
            raise ValueError("graph.json is invalid:\n" + "\n".join(errors))
        host = get_host(args.host, args.model)
        reviews_dir = Path(meta["reviews_dir"])
        store = Store.open(reviews_dir, changeset["slug"], changeset)
        notes: list[str] = []

        def note(text: str) -> None:
            if text not in notes:
                notes.append(text)

        passes = Passes(host, store, changeset, run_dir, args.effort, on_note=note)
        service = HostService(passes, Asker(host, changeset, run_dir, args.effort))
        app = ReviewServer(
            store=store,
            changeset=changeset,
            graph=graph,
            reviews_dir=reviews_dir,
            service=service,
            host=args.host,
            effort=args.effort,
            notes=notes,
            idle_timeout=args.idle_minutes * 60,
        )
    except Exception as exc:  # noqa: BLE001 - one terminal line for the invoking agent
        if repo is not None:
            changeset_mod.cleanup_worktree(repo, run_dir)
        print(f"REVIEW-ERROR {exc}", flush=True)
        return 1

    def on_signal(_signum, _frame) -> None:
        if app.outcome.kind == "running":
            app.outcome.kind = "suspended"
            app.outcome.path = str(reviews_dir / f"{changeset['slug']}.state.json")
        threading.Thread(target=app.stop, daemon=True).start()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    print(f"LISTENING {app.url}", flush=True)
    try:
        outcome = app.serve()
    except Exception as exc:  # noqa: BLE001
        print(f"REVIEW-ERROR {exc}", flush=True)
        return 1
    finally:
        changeset_mod.cleanup_worktree(repo, run_dir)
    if outcome.kind == "complete":
        print(f"REVIEW-COMPLETE {outcome.path}", flush=True)
    else:
        print(f"REVIEW-SUSPENDED stopped {outcome.path}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="review_offline")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare", help="resolve a changeset into a run dir")
    p.add_argument("target", nargs="?", default=None)
    p.add_argument("--repo", default=os.getcwd())
    p.add_argument("--run-dir", default=None)
    p.add_argument("--fresh", action="store_true", help="set aside any saved review state")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("validate-graph", help="validate a graph.json")
    p.add_argument("path")
    p.add_argument("--root", default=None)
    p.add_argument("--changeset", default=None)
    p.set_defaults(
        func=lambda a: graph_mod.main(
            [a.path]
            + (["--root", a.root] if a.root else [])
            + (["--changeset", a.changeset] if a.changeset else [])
        )
    )

    p = sub.add_parser("serve", help="serve the review page until finished")
    p.add_argument("run_dir")
    p.add_argument("--host", required=True, choices=["claude", "codex", "omp"])
    p.add_argument("--model", default=None)
    p.add_argument("--effort", default="high")
    p.add_argument("--idle-minutes", type=float, default=30.0)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("cleanup", help="remove the worktree of a run dir")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_cleanup)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
