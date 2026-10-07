"""Strict validator for the review-offline graph document (`graph.json`)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

SCHEMA_VERSION = "1"
ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
ID_MAX = 64
MAX_ERRORS = 50

DELTAS = ("added", "modified", "removed", "unchanged")
NODE_KINDS = (
    "service",
    "app",
    "module",
    "function",
    "route",
    "job",
    "queue",
    "datastore",
    "cache",
    "external",
    "ui",
    "config",
    "test",
    "package",
    "other",
)
EDGE_KINDS = ("call", "http", "rpc", "event", "queue", "data", "dependency", "render", "other")
EMPHASES = ("normal", "hero", "muted")
PANEL_KINDS = ("calltree", "pseudocode", "filetree")

CAPS = {"lanes": 8, "nodes": 30, "edges": 64, "flows": 6, "panels": 4}
MAX_STEPS = 12
MAX_HEROES = 2
MAX_BADGES = 6
MAX_BADGE_LEN = 40
MAX_LABEL = 80
MAX_PROSE = 600
MAX_PANEL_TEXT = 4000
MAX_ORDER = 64

TOP_REQUIRED = ("schemaVersion", "title", "summary", "lanes", "nodes")
TOP_OPTIONAL = ("edges", "flows", "panels")


class _Errors:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, path: str, message: str) -> None:
        self.items.append(f"{path}: {message}")


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _check_keys(
    errs: _Errors, obj: dict, path: str, required: tuple[str, ...], optional: tuple[str, ...]
) -> None:
    for key in required:
        if key not in obj:
            errs.add(_join(path, key), "missing required key")
    known = set(required) | set(optional)
    for key in obj:
        if key not in known:
            errs.add(_join(path, str(key)), "unknown key")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text(errs: _Errors, obj: dict, key: str, path: str, limit: int) -> str | None:
    if key not in obj:
        return None
    value = obj[key]
    here = _join(path, key)
    if not isinstance(value, str):
        errs.add(here, f"expected string, got {_type_name(value)}")
        return None
    if not value.strip():
        errs.add(here, "must not be empty")
        return None
    if len(value) > limit:
        errs.add(here, f"too long ({len(value)} chars, max {limit})")
    return value


def _enum(
    errs: _Errors, obj: dict, key: str, path: str, allowed: tuple[str, ...] | list[str]
) -> str | None:
    if key not in obj:
        return None
    value = obj[key]
    here = _join(path, key)
    if not isinstance(value, str):
        errs.add(here, f"expected string, got {_type_name(value)}")
        return None
    if value not in allowed:
        errs.add(here, f"unknown {key} {value!r} (allowed: {', '.join(allowed)})")
        return None
    return value


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    return "number"


def _id_ok(errs: _Errors, value: object, path: str) -> str | None:
    if not isinstance(value, str):
        errs.add(path, f"expected string, got {_type_name(value)}")
        return None
    if len(value) > ID_MAX:
        errs.add(path, f"id too long ({len(value)} chars, max {ID_MAX})")
        return None
    if not ID_RE.fullmatch(value):
        errs.add(path, f"invalid id {value!r} (must match ^[a-z0-9][a-z0-9._-]*$)")
        return None
    return value


def _items(errs: _Errors, doc: dict, key: str) -> list[tuple[int, dict]]:
    """Objects of a collection with their indexes; reports shape and cap errors."""
    if key not in doc:
        return []
    value = doc[key]
    if not isinstance(value, list):
        errs.add(key, f"expected array, got {_type_name(value)}")
        return []
    if len(value) > CAPS[key]:
        errs.add(key, f"too many {key} ({len(value)}, max {CAPS[key]})")
    out = []
    for index, item in enumerate(value):
        if isinstance(item, dict):
            out.append((index, item))
        else:
            errs.add(f"{key}[{index}]", f"expected object, got {_type_name(item)}")
    return out


def _unique_id(errs: _Errors, item: dict, path: str, seen: dict[str, str]) -> str | None:
    if "id" not in item:
        return None
    value = _id_ok(errs, item["id"], f"{path}.id")
    if value is None:
        return None
    if value in seen:
        errs.add(f"{path}.id", f"duplicate id {value!r} (first used at {seen[value]})")
        return value
    seen[value] = path
    return value


def _path_problem(raw: str) -> str | None:
    if PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
        return "absolute paths are not allowed"
    if raw.startswith(("/", "\\")):
        return "absolute paths are not allowed"
    parts = re.split(r"[\\/]", raw)
    if ".." in parts:
        return "'..' path traversal is not allowed"
    return None


def _check_files(
    errs: _Errors, node: dict, path: str, root: Path | None, known: frozenset[str]
) -> None:
    if "files" not in node:
        return
    files = node["files"]
    here = f"{path}.files"
    if not isinstance(files, list):
        errs.add(here, f"expected array, got {_type_name(files)}")
        return
    for index, entry in enumerate(files):
        fpath = f"{here}[{index}]"
        if not isinstance(entry, dict):
            errs.add(fpath, f"expected object, got {_type_name(entry)}")
            continue
        _check_keys(errs, entry, fpath, ("path",), ("start", "end"))
        raw = entry.get("path")
        if "path" in entry:
            if not isinstance(raw, str) or not raw:
                errs.add(f"{fpath}.path", "expected non-empty string")
            else:
                problem = _path_problem(raw)
                if problem:
                    errs.add(f"{fpath}.path", problem)
                elif root is not None and raw not in known and not _exists_under(root, raw):
                    errs.add(f"{fpath}.path", f"{raw!r} does not exist under root {root}")
        bounds: dict[str, int] = {}
        for key in ("start", "end"):
            if key not in entry:
                continue
            value = entry[key]
            if not _is_int(value):
                errs.add(f"{fpath}.{key}", f"expected integer, got {_type_name(value)}")
            elif value < 1:
                errs.add(f"{fpath}.{key}", f"must be a positive integer, got {value}")
            else:
                bounds[key] = value
        if ("start" in entry) != ("end" in entry):
            errs.add(fpath, "start and end must be given together")
        elif len(bounds) == 2 and bounds["start"] > bounds["end"]:
            errs.add(fpath, f"start ({bounds['start']}) must be <= end ({bounds['end']})")


def _exists_under(root: Path, raw: str) -> bool:
    candidate = root / raw
    if not candidate.exists():
        return False
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _check_badges(errs: _Errors, node: dict, path: str) -> None:
    if "badges" not in node:
        return
    badges = node["badges"]
    here = f"{path}.badges"
    if not isinstance(badges, list):
        errs.add(here, f"expected array, got {_type_name(badges)}")
        return
    if len(badges) > MAX_BADGES:
        errs.add(here, f"too many badges ({len(badges)}, max {MAX_BADGES})")
    for index, badge in enumerate(badges):
        bpath = f"{here}[{index}]"
        if not isinstance(badge, str) or not badge.strip():
            errs.add(bpath, "expected non-empty string")
        elif len(badge) > MAX_BADGE_LEN:
            errs.add(bpath, f"too long ({len(badge)} chars, max {MAX_BADGE_LEN})")
        elif badge.strip().lower() in DELTAS:
            errs.add(bpath, f"badge {badge!r} restates the delta; the page draws it for you")


def _check_lanes(errs: _Errors, doc: dict) -> list[str]:
    seen: dict[str, str] = {}
    for index, lane in _items(errs, doc, "lanes"):
        path = f"lanes[{index}]"
        _check_keys(errs, lane, path, ("id", "label", "order"), ("subtitle",))
        _unique_id(errs, lane, path, seen)
        _text(errs, lane, "label", path, MAX_LABEL)
        _text(errs, lane, "subtitle", path, MAX_LABEL)
        if "order" in lane:
            order = lane["order"]
            if not _is_int(order):
                errs.add(f"{path}.order", f"expected integer, got {_type_name(order)}")
            elif not 0 <= order <= MAX_ORDER:
                errs.add(f"{path}.order", f"must be between 0 and {MAX_ORDER}, got {order}")
    return list(seen)


def _check_nodes(
    errs: _Errors, doc: dict, lanes: list[str], root: Path | None, known: frozenset[str]
) -> list[str]:
    seen: dict[str, str] = {}
    required = ("id", "label", "kind", "delta", "lane")
    optional = ("group", "subtitle", "summary", "files", "badges")
    for index, node in _items(errs, doc, "nodes"):
        path = f"nodes[{index}]"
        _check_keys(errs, node, path, required, optional)
        _unique_id(errs, node, path, seen)
        _text(errs, node, "label", path, MAX_LABEL)
        _text(errs, node, "subtitle", path, MAX_LABEL)
        _text(errs, node, "group", path, MAX_LABEL)
        _text(errs, node, "summary", path, MAX_PROSE)
        _enum(errs, node, "kind", path, NODE_KINDS)
        _enum(errs, node, "delta", path, DELTAS)
        if "lane" in node:
            lane = node["lane"]
            if not isinstance(lane, str):
                errs.add(f"{path}.lane", f"expected string, got {_type_name(lane)}")
            elif lane not in lanes:
                declared = ", ".join(lanes) if lanes else "none"
                errs.add(f"{path}.lane", f"unknown lane {lane!r} (declared: {declared})")
        _check_files(errs, node, path, root, known)
        _check_badges(errs, node, path)
    return list(seen)


def _check_edges(errs: _Errors, doc: dict, node_ids: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    heroes = 0
    for index, edge in _items(errs, doc, "edges"):
        path = f"edges[{index}]"
        _check_keys(errs, edge, path, ("id", "from", "to", "kind", "delta"), ("label", "emphasis"))
        _unique_id(errs, edge, path, seen)
        _text(errs, edge, "label", path, MAX_LABEL)
        _enum(errs, edge, "kind", path, EDGE_KINDS)
        _enum(errs, edge, "delta", path, DELTAS)
        if _enum(errs, edge, "emphasis", path, EMPHASES) == "hero":
            heroes += 1
        for end in ("from", "to"):
            if end not in edge:
                continue
            value = edge[end]
            if not isinstance(value, str):
                errs.add(f"{path}.{end}", f"expected string, got {_type_name(value)}")
            elif value not in node_ids:
                errs.add(f"{path}.{end}", f"no node with id {value!r}")
    if heroes > MAX_HEROES:
        errs.add("edges", f"too many hero edges ({heroes}, max {MAX_HEROES})")
    return list(seen)


def _check_steps(
    errs: _Errors, flow: dict, path: str, node_ids: list[str], edge_ids: list[str]
) -> None:
    if "steps" not in flow:
        return
    steps = flow["steps"]
    here = f"{path}.steps"
    if not isinstance(steps, list):
        errs.add(here, f"expected array, got {_type_name(steps)}")
        return
    if not steps:
        errs.add(here, "must contain at least one step")
    if len(steps) > MAX_STEPS:
        errs.add(here, f"too many steps ({len(steps)}, max {MAX_STEPS})")
    seen: dict[str, str] = {}
    for index, step in enumerate(steps):
        spath = f"{here}[{index}]"
        if not isinstance(step, dict):
            errs.add(spath, f"expected object, got {_type_name(step)}")
            continue
        _check_keys(errs, step, spath, ("id", "caption", "delta"), ("edge", "node"))
        _unique_id(errs, step, spath, seen)
        _text(errs, step, "caption", spath, MAX_PROSE)
        _enum(errs, step, "delta", spath, DELTAS)
        has_edge, has_node = "edge" in step, "node" in step
        if has_edge == has_node:
            errs.add(spath, "must name exactly one of 'edge' or 'node'")
        for key, ids in (("edge", edge_ids), ("node", node_ids)):
            if key not in step:
                continue
            value = step[key]
            if not isinstance(value, str):
                errs.add(f"{spath}.{key}", f"expected string, got {_type_name(value)}")
            elif value not in ids:
                errs.add(f"{spath}.{key}", f"no {key} with id {value!r}")


def _check_flows(errs: _Errors, doc: dict, node_ids: list[str], edge_ids: list[str]) -> None:
    seen: dict[str, str] = {}
    for index, flow in _items(errs, doc, "flows"):
        path = f"flows[{index}]"
        _check_keys(errs, flow, path, ("id", "title", "delta", "steps"), ("summary",))
        _unique_id(errs, flow, path, seen)
        _text(errs, flow, "title", path, MAX_LABEL)
        _text(errs, flow, "summary", path, MAX_PROSE)
        _enum(errs, flow, "delta", path, DELTAS)
        _check_steps(errs, flow, path, node_ids, edge_ids)


def _check_panels(errs: _Errors, doc: dict) -> None:
    seen: dict[str, str] = {}
    for index, panel in _items(errs, doc, "panels"):
        path = f"panels[{index}]"
        _check_keys(errs, panel, path, ("id", "title", "kind", "text"), ("diff",))
        _unique_id(errs, panel, path, seen)
        _text(errs, panel, "title", path, MAX_LABEL)
        _text(errs, panel, "text", path, MAX_PANEL_TEXT)
        _enum(errs, panel, "kind", path, PANEL_KINDS)
        if "diff" in panel and not isinstance(panel["diff"], bool):
            errs.add(f"{path}.diff", f"expected boolean, got {_type_name(panel['diff'])}")


def _blast_radius_problem(doc: dict) -> str | None:
    nodes = [n for n in doc.get("nodes", []) if isinstance(n, dict)]
    if not nodes:
        return None
    deltas: list[object] = [n.get("delta") for n in nodes]
    for key in ("edges", "flows"):
        for item in doc.get(key, []) if isinstance(doc.get(key), list) else []:
            if not isinstance(item, dict):
                continue
            deltas.append(item.get("delta"))
            steps = item.get("steps")
            if isinstance(steps, list):
                deltas.extend(s.get("delta") for s in steps if isinstance(s, dict))
    if all(d == "added" for d in deltas) and not any(n.get("delta") == "unchanged" for n in nodes):
        return (
            "blast radius missing: every delta is 'added' and no node is 'unchanged'. "
            "Add the unchanged neighbouring code the change touches so a reader can place it"
        )
    return None


def validate(
    doc: object, *, root: Path | None = None, known_paths: frozenset[str] = frozenset()
) -> list[str]:
    """Return error strings for a graph document; an empty list means valid."""
    if not isinstance(doc, dict):
        return [f"$: expected object, got {_type_name(doc)}"]
    errs = _Errors()
    _check_keys(errs, doc, "", TOP_REQUIRED, TOP_OPTIONAL)
    if "schemaVersion" in doc and doc["schemaVersion"] != SCHEMA_VERSION:
        errs.add("schemaVersion", f"expected {SCHEMA_VERSION!r}, got {doc['schemaVersion']!r}")
    _text(errs, doc, "title", "", MAX_LABEL)
    _text(errs, doc, "summary", "", MAX_PROSE)
    lanes = _check_lanes(errs, doc)
    node_ids = _check_nodes(errs, doc, lanes, root, known_paths)
    edge_ids = _check_edges(errs, doc, node_ids)
    _check_flows(errs, doc, node_ids, edge_ids)
    _check_panels(errs, doc)
    items = errs.items
    blast = _blast_radius_problem(doc)
    if blast:
        return [*items[: MAX_ERRORS - 1], f"nodes: {blast}"]
    return items[:MAX_ERRORS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m review_offline.graph", description="Validate a graph.json document."
    )
    parser.add_argument("graph", type=Path)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--changeset", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        text = args.graph.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read {args.graph}: {exc.strerror or exc}")
        return 1
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}")
        return 1
    known = frozenset()
    if args.changeset:
        known = frozenset(f["path"] for f in json.loads(args.changeset.read_text())["files"])
    errors = validate(doc, root=args.root, known_paths=known)
    if errors:
        print("\n".join(errors))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
