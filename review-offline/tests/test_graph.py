import copy
import json

import pytest
from review_offline.graph import main, validate


def make_doc():
    return {
        "schemaVersion": "1",
        "title": "Batch broadcast sending",
        "summary": "Sends a broadcast with one payload instead of one call per recipient.",
        "lanes": [
            {"id": "ui", "label": "Web UI", "order": 0},
            {"id": "functions", "label": "Cloud Functions", "subtitle": "Node 20", "order": 1},
            {"id": "external", "label": "External", "order": 2},
        ],
        "nodes": [
            {
                "id": "composer",
                "label": "Composer",
                "kind": "ui",
                "delta": "unchanged",
                "lane": "ui",
                "files": [{"path": "src/composer.ts", "start": 1, "end": 20}],
            },
            {
                "id": "send-bulk",
                "label": "sendBulk",
                "kind": "function",
                "delta": "added",
                "lane": "functions",
                "group": "broadcast-lib",
                "subtitle": "(id) => Promise<void>",
                "summary": "Claims the broadcast, builds one payload and posts it.",
                "files": [{"path": "src/send.ts", "start": 1, "end": 142}],
                "badges": ["retry"],
            },
            {
                "id": "postmark",
                "label": "Postmark",
                "kind": "external",
                "delta": "unchanged",
                "lane": "external",
            },
        ],
        "edges": [
            {
                "id": "ui-to-sender",
                "from": "composer",
                "to": "send-bulk",
                "kind": "call",
                "delta": "added",
            },
            {
                "id": "bulk-to-postmark",
                "from": "send-bulk",
                "to": "postmark",
                "kind": "http",
                "delta": "added",
                "label": "POST /email/bulk",
                "emphasis": "hero",
            },
        ],
        "flows": [
            {
                "id": "happy-path",
                "title": "A broadcast is sent",
                "summary": "From click to delivery.",
                "delta": "added",
                "steps": [
                    {
                        "id": "s1",
                        "edge": "ui-to-sender",
                        "caption": "The UI enqueues the broadcast.",
                        "delta": "added",
                    },
                    {
                        "id": "s2",
                        "node": "send-bulk",
                        "caption": "The sender claims it first.",
                        "delta": "added",
                    },
                ],
            }
        ],
        "panels": [
            {
                "id": "control-flow",
                "title": "submit path",
                "kind": "calltree",
                "diff": True,
                "text": " submitForm\n+  expandSkillMention",
            }
        ],
    }


def errors_for(mutate):
    doc = make_doc()
    mutate(doc)
    return validate(doc)


def assert_error(errors, fragment):
    assert any(fragment in e for e in errors), f"{fragment!r} not in {errors}"


def test_valid_full_document():
    assert validate(make_doc()) == []


def test_minimal_document_without_optional_collections():
    doc = make_doc()
    for key in ("edges", "flows", "panels"):
        del doc[key]
    assert validate(doc) == []


def test_root_must_be_object():
    assert validate([]) == ["$: expected object, got array"]


def test_unknown_keys_at_every_level():
    doc = make_doc()
    doc["extra"] = 1
    doc["lanes"][0]["x"] = 1
    doc["nodes"][0]["x"] = 1
    doc["nodes"][1]["files"][0]["x"] = 1
    doc["edges"][0]["x"] = 1
    doc["flows"][0]["x"] = 1
    doc["flows"][0]["steps"][0]["x"] = 1
    doc["panels"][0]["x"] = 1
    errors = validate(doc)
    for path in (
        "extra",
        "lanes[0].x",
        "nodes[0].x",
        "nodes[1].files[0].x",
        "edges[0].x",
        "flows[0].x",
        "flows[0].steps[0].x",
        "panels[0].x",
    ):
        assert_error(errors, f"{path}: unknown key")


def test_missing_required_keys():
    doc = make_doc()
    del doc["title"]
    del doc["nodes"][0]["kind"]
    errors = validate(doc)
    assert_error(errors, "title: missing required key")
    assert_error(errors, "nodes[0].kind: missing required key")


def test_schema_version_checked():
    assert_error(errors_for(lambda d: d.update(schemaVersion="2")), "schemaVersion:")


def test_wrong_types():
    def mutate(d):
        d["title"] = 3
        d["nodes"] = {}
        d["edges"][0]["label"] = ["x"]
        d["lanes"][0]["order"] = "0"
        d["lanes"][1]["order"] = True
        d["panels"][0]["diff"] = "yes"

    errors = errors_for(mutate)
    assert_error(errors, "title: expected string, got number")
    assert_error(errors, "nodes: expected array, got object")
    assert_error(errors, "edges[0].label: expected string, got array")
    assert_error(errors, "lanes[0].order: expected integer, got string")
    assert_error(errors, "lanes[1].order: expected integer, got boolean")
    assert_error(errors, "panels[0].diff: expected boolean, got string")


def test_collection_items_must_be_objects():
    assert_error(errors_for(lambda d: d["nodes"].append("x")), "nodes[3]: expected object")


def test_enum_values():
    def mutate(d):
        d["nodes"][0]["kind"] = "widget"
        d["nodes"][0]["delta"] = "changed"
        d["edges"][0]["kind"] = "smoke"
        d["edges"][0]["emphasis"] = "loud"
        d["panels"][0]["kind"] = "poem"
        d["flows"][0]["steps"][0]["delta"] = "nope"

    errors = errors_for(mutate)
    assert_error(errors, "nodes[0].kind: unknown kind 'widget'")
    assert_error(errors, "nodes[0].delta: unknown delta 'changed' (allowed: added, modified")
    assert_error(errors, "edges[0].kind: unknown kind 'smoke'")
    assert_error(errors, "edges[0].emphasis: unknown emphasis 'loud'")
    assert_error(errors, "panels[0].kind: unknown kind 'poem'")
    assert_error(errors, "flows[0].steps[0].delta: unknown delta 'nope'")


@pytest.mark.parametrize("bad", ["Upper", "-lead", "has space", "", "a/b", "é"])
def test_invalid_id_pattern(bad):
    errors = errors_for(lambda d: d["nodes"][0].update(id=bad))
    assert_error(errors, "nodes[0].id:")


def test_id_pattern_accepts_dots_dashes_underscores():
    def mutate(d):
        d["nodes"][0]["id"] = "a.b_c-d9"
        d["edges"][0]["from"] = "a.b_c-d9"

    assert errors_for(mutate) == []


def test_id_length_limit():
    assert errors_for(lambda d: d["lanes"][0].update(id="a" * 64)) != []
    errors = errors_for(lambda d: d["lanes"][0].update(id="a" * 65))
    assert_error(errors, "lanes[0].id: id too long (65 chars, max 64)")


@pytest.mark.parametrize(
    ("collection", "extra_index"),
    [("lanes", 1), ("nodes", 1), ("edges", 1), ("flows", 0), ("panels", 0)],
)
def test_duplicate_ids(collection, extra_index):
    def mutate(d):
        d[collection].append(copy.deepcopy(d[collection][extra_index]))

    errors = errors_for(mutate)
    last = len(make_doc()[collection])
    assert_error(errors, f"{collection}[{last}].id: duplicate id")


def test_duplicate_step_ids_within_a_flow():
    errors = errors_for(lambda d: d["flows"][0]["steps"][1].update(id="s1"))
    assert_error(errors, "flows[0].steps[1].id: duplicate id 's1'")


def test_same_step_id_in_different_flows_is_fine():
    def mutate(d):
        d["flows"].append(copy.deepcopy(d["flows"][0]))
        d["flows"][1]["id"] = "other"

    assert errors_for(mutate) == []


def test_caps():
    def mutate(d):
        d["lanes"] = [{"id": f"l{i}", "label": "L", "order": i} for i in range(9)]
        d["nodes"] = [
            {"id": f"n{i}", "label": "N", "kind": "app", "delta": "unchanged", "lane": "l0"}
            for i in range(31)
        ]
        d["edges"] = [
            {"id": f"e{i}", "from": "n0", "to": "n1", "kind": "call", "delta": "added"}
            for i in range(65)
        ]
        d["flows"] = [
            {
                "id": f"f{i}",
                "title": "F",
                "delta": "added",
                "steps": [{"id": "s", "node": "n0", "caption": "c", "delta": "added"}],
            }
            for i in range(7)
        ]
        d["panels"] = [
            {"id": f"p{i}", "title": "P", "kind": "filetree", "text": "x"} for i in range(5)
        ]

    errors = errors_for(mutate)
    assert_error(errors, "lanes: too many lanes (9, max 8)")
    assert_error(errors, "nodes: too many nodes (31, max 30)")
    assert_error(errors, "edges: too many edges (65, max 64)")
    assert_error(errors, "flows: too many flows (7, max 6)")
    assert_error(errors, "panels: too many panels (5, max 4)")


def test_caps_at_boundary_are_valid():
    def mutate(d):
        d["lanes"] = [{"id": f"l{i}", "label": "L", "order": i} for i in range(8)]
        d["nodes"] = [
            {"id": f"n{i}", "label": "N", "kind": "app", "delta": "unchanged", "lane": "l0"}
            for i in range(30)
        ]
        d["edges"] = []
        d["flows"] = []
        d["panels"] = []

    assert errors_for(mutate) == []


def test_steps_per_flow_cap():
    def mutate(d):
        d["flows"][0]["steps"] = [
            {"id": f"s{i}", "node": "send-bulk", "caption": "c", "delta": "added"}
            for i in range(13)
        ]

    assert_error(errors_for(mutate), "flows[0].steps: too many steps (13, max 12)")


def test_empty_steps_rejected():
    assert_error(errors_for(lambda d: d["flows"][0].update(steps=[])), "flows[0].steps: must")


def test_node_lane_must_be_declared():
    errors = errors_for(lambda d: d["nodes"][1].update(lane="x"))
    assert_error(errors, "nodes[1].lane: unknown lane 'x' (declared: ui, functions, external)")


def test_edge_endpoints_must_be_declared():
    def mutate(d):
        d["edges"][0]["from"] = "y"
        d["edges"][0]["to"] = "z"

    errors = errors_for(mutate)
    assert_error(errors, "edges[0].from: no node with id 'y'")
    assert_error(errors, "edges[0].to: no node with id 'z'")


def test_step_must_name_exactly_one_target():
    def mutate(d):
        d["flows"][0]["steps"][0]["node"] = "send-bulk"
        del d["flows"][0]["steps"][1]["node"]

    errors = errors_for(mutate)
    assert_error(errors, "flows[0].steps[0]: must name exactly one of 'edge' or 'node'")
    assert_error(errors, "flows[0].steps[1]: must name exactly one of 'edge' or 'node'")


def test_step_targets_must_exist():
    def mutate(d):
        d["flows"][0]["steps"][0]["edge"] = "ghost"
        d["flows"][0]["steps"][1]["node"] = "ghost"

    errors = errors_for(mutate)
    assert_error(errors, "flows[0].steps[0].edge: no edge with id 'ghost'")
    assert_error(errors, "flows[0].steps[1].node: no node with id 'ghost'")


@pytest.mark.parametrize("order", [-1, 65])
def test_lane_order_range(order):
    assert_error(errors_for(lambda d: d["lanes"][0].update(order=order)), "lanes[0].order:")


@pytest.mark.parametrize("order", [0, 64])
def test_lane_order_bounds_valid(order):
    assert errors_for(lambda d: d["lanes"][0].update(order=order)) == []


@pytest.mark.parametrize(
    ("start", "end", "fragment"),
    [
        (0, 5, "files[0].start: must be a positive integer"),
        (1, -2, "files[0].end: must be a positive integer"),
        (10, 5, "files[0]: start (10) must be <= end (5)"),
        ("1", 5, "files[0].start: expected integer, got string"),
        (True, 5, "files[0].start: expected integer, got boolean"),
        (1.5, 5, "files[0].start: expected integer, got number"),
    ],
)
def test_file_ranges(start, end, fragment):
    def mutate(d):
        d["nodes"][1]["files"][0].update(start=start, end=end)

    assert_error(errors_for(mutate), f"nodes[1].{fragment}")


def test_file_range_equal_start_end_valid():
    assert errors_for(lambda d: d["nodes"][1]["files"][0].update(start=7, end=7)) == []


def test_file_start_without_end_rejected():
    def mutate(d):
        del d["nodes"][1]["files"][0]["end"]

    assert_error(errors_for(mutate), "nodes[1].files[0]: start and end must be given together")


def test_file_without_range_is_valid():
    def mutate(d):
        d["nodes"][1]["files"] = [{"path": "src"}]

    assert errors_for(mutate) == []


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "a/../../x", "a\\..\\x", "C:\\x"])
def test_file_path_rejects_absolute_and_traversal_without_root(bad):
    errors = errors_for(lambda d: d["nodes"][1]["files"][0].update(path=bad))
    assert_error(errors, "nodes[1].files[0].path:")


def test_file_path_checked_against_root(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "send.ts").write_text("x")
    doc = make_doc()
    doc["nodes"][0]["files"][0]["path"] = "src/send.ts"
    doc["nodes"][1]["files"][0]["path"] = "src/missing.ts"
    errors = validate(doc, root=tmp_path)
    assert len(errors) == 1
    assert errors[0].startswith("nodes[1].files[0].path: 'src/missing.ts' does not exist")


def test_file_path_not_checked_without_root():
    doc = make_doc()
    doc["nodes"][1]["files"][0]["path"] = "does/not/exist.ts"
    assert validate(doc) == []


def test_file_path_symlink_escaping_root_rejected(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.txt").symlink_to(outside)
    doc = make_doc()
    doc["nodes"][1]["files"][0]["path"] = "link.txt"
    doc["nodes"][0]["files"] = []
    assert_error(validate(doc, root=root), "nodes[1].files[0].path:")


@pytest.mark.parametrize(
    ("setter", "limit"),
    [
        (lambda d, v: d["nodes"][0].update(label=v), 80),
        (lambda d, v: d["lanes"][0].update(label=v), 80),
        (lambda d, v: d["edges"][0].update(label=v), 80),
        (lambda d, v: d.update(title=v), 80),
        (lambda d, v: d["nodes"][0].update(summary=v), 600),
        (lambda d, v: d.update(summary=v), 600),
        (lambda d, v: d["flows"][0]["steps"][0].update(caption=v), 600),
        (lambda d, v: d["flows"][0].update(summary=v), 600),
        (lambda d, v: d["panels"][0].update(text=v), 4000),
    ],
)
def test_text_length_limits(setter, limit):
    ok = make_doc()
    setter(ok, "x" * limit)
    assert validate(ok) == []
    bad = make_doc()
    setter(bad, "x" * (limit + 1))
    errors = validate(bad)
    assert len(errors) == 1
    assert f"too long ({limit + 1} chars, max {limit})" in errors[0]


def test_empty_text_rejected():
    assert_error(errors_for(lambda d: d["nodes"][0].update(label="  ")), "nodes[0].label: must not")


def test_at_most_two_hero_edges():
    def mutate(d):
        d["edges"][0]["emphasis"] = "hero"
        d["edges"].append(
            {
                "id": "third",
                "from": "composer",
                "to": "postmark",
                "kind": "call",
                "delta": "added",
                "emphasis": "hero",
            }
        )

    assert_error(errors_for(mutate), "edges: too many hero edges (3, max 2)")


def test_two_hero_edges_valid():
    assert errors_for(lambda d: d["edges"][0].update(emphasis="hero")) == []


def test_badge_limits():
    def mutate(d):
        d["nodes"][1]["badges"] = [f"b{i}" for i in range(7)]

    assert_error(errors_for(mutate), "nodes[1].badges: too many badges (7, max 6)")
    assert errors_for(lambda d: d["nodes"][1].update(badges=[f"b{i}" for i in range(6)])) == []


@pytest.mark.parametrize("word", ["added", "modified", "removed", "unchanged", "Added"])
def test_badge_may_not_equal_delta_word(word):
    errors = errors_for(lambda d: d["nodes"][1].update(badges=["retry", word]))
    assert_error(errors, "nodes[1].badges[1]:")
    assert_error(errors, "restates the delta")


def test_blast_radius_rule_is_last_error():
    def mutate(d):
        for node in d["nodes"]:
            node["delta"] = "added"
        d["nodes"][0]["lane"] = "nowhere"

    errors = errors_for(mutate)
    assert len(errors) == 2
    assert_error(errors[:1], "nodes[0].lane")
    assert "blast radius" in errors[-1]
    assert "unchanged" in errors[-1]


def test_blast_radius_satisfied_by_modified_delta():
    def mutate(d):
        for node in d["nodes"]:
            node["delta"] = "added"
        d["nodes"][0]["delta"] = "modified"

    assert errors_for(mutate) == []


def test_blast_radius_not_raised_when_no_nodes():
    doc = make_doc()
    doc["nodes"] = []
    doc["edges"] = []
    doc["flows"] = []
    assert validate(doc) == []


def test_all_errors_collected_and_output_capped():
    doc = make_doc()
    doc["nodes"] = [
        {"id": f"n{i}", "label": "N", "kind": "bad", "delta": "bad", "lane": "bad"}
        for i in range(30)
    ]
    doc["edges"] = []
    doc["flows"] = []
    errors = validate(doc)
    assert len(errors) == 50


def test_cap_keeps_blast_radius_error_last():
    doc = make_doc()
    doc["nodes"] = [
        {"id": f"n{i}", "label": "N", "kind": "bad", "delta": "added", "lane": "bad"}
        for i in range(30)
    ]
    doc["edges"] = []
    doc["flows"] = []
    errors = validate(doc)
    assert len(errors) == 50
    assert "blast radius" in errors[-1]


def test_multiple_independent_errors_reported_together():
    def mutate(d):
        d["nodes"][1]["lane"] = "x"
        d["edges"][0]["from"] = "y"
        d["flows"][0]["steps"][0]["edge"] = "z"

    assert len(errors_for(mutate)) == 3


def write_graph(tmp_path, doc):
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(doc))
    return path


def test_cli_ok(tmp_path, capsys):
    path = write_graph(tmp_path, make_doc())
    assert main([str(path)]) == 0
    assert capsys.readouterr().out.strip() == "ok"


def test_cli_errors_one_per_line(tmp_path, capsys):
    doc = make_doc()
    doc["nodes"][1]["lane"] = "x"
    doc["edges"][0]["from"] = "y"
    path = write_graph(tmp_path, doc)
    assert main([str(path)]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("nodes[1].lane: unknown lane 'x'")
    assert lines[1] == "edges[0].from: no node with id 'y'"


def test_cli_invalid_json_reports_line_and_column(tmp_path, capsys):
    path = tmp_path / "graph.json"
    path.write_text('{\n  "a": 1,\n  oops\n}')
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "invalid JSON" in out
    assert "line 3 column 3" in out


def test_cli_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.json")]) == 1
    assert "cannot read" in capsys.readouterr().out


def test_cli_root_option(tmp_path, capsys):
    root = tmp_path / "tree"
    (root / "src").mkdir(parents=True)
    (root / "src" / "composer.ts").write_text("x")
    path = write_graph(tmp_path, make_doc())
    assert main([str(path), "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "nodes[1].files[0].path" in out
    (root / "src" / "send.ts").write_text("x")
    assert main([str(path), "--root", str(root)]) == 0


def test_cli_as_module(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    path = write_graph(tmp_path, make_doc())
    result = subprocess.run(
        [sys.executable, "-m", "review_offline.graph", str(path)],
        cwd=scripts,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_deleted_file_paths_allowed_when_in_changeset(tmp_path):
    doc = json.loads(json.dumps(make_doc()))
    doc["nodes"][0]["files"] = [{"path": "gone/old.py"}]
    assert any("gone/old.py" in e for e in validate(doc, root=tmp_path))
    known = frozenset({"gone/old.py"})
    assert not any("gone/old.py" in e for e in validate(doc, root=tmp_path, known_paths=known))
