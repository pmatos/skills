import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lookbook as lb  # noqa: E402

ITEMS = [
    ("1", "Acme", "Linen shirt", "olive", "49.99"),
    ("2", "Acme", "Wide-leg jeans", "dark blue", "59.95"),
    ("3", "Beta", "Leather trainers", "white", "89.00"),
    ("4", "Beta", "Suede jacket", "brown", "149.00"),
    ("5", "Gamma", "Sheer tights", "black", "9.99"),
]


@pytest.fixture
def project(tmp_path):
    lb.main(["init", str(tmp_path), "--person", "Sam", "--season", "winter"])
    rows = ["\t".join(lb.ITEM_FIELDS)] + ["\t".join([*r, f"slug-{r[0]}.html", ""]) for r in ITEMS]
    (tmp_path / "data/items.tsv").write_text("\n".join(rows) + "\n")
    outfits = [
        {
            "id": "CA1",
            "cat": "Casual",
            "name": "Olive",
            "items": [1, 2],
            "why": "w",
            "styling": "Loose.",
            "basics": True,
        },
        {
            "id": "FE1",
            "cat": "Festive",
            "name": "Night",
            "items": [1, 5, 3],
            "why": "w",
            "styling": "Tucked.",
        },
    ]
    (tmp_path / "data/outfits.json").write_text(json.dumps(outfits))
    basics = {
        "items": [
            {"id": 4, "role": "The coat", "in_photo": False},
            {"id": 3, "role": "The trainers", "in_photo": True},
        ]
    }
    (tmp_path / "data/basics.json").write_text(json.dumps(basics))
    return tmp_path


def test_init_writes_config_with_unique_slug(project):
    cfg = json.loads((project / "lookbook.json").read_text())
    assert cfg["person"] == "Sam"
    assert cfg["slug"] == "sam-s-lookbook-winter"
    assert (project / "photos").is_dir()


def test_init_keeps_existing_config(project):
    cfg = project / "lookbook.json"
    cfg.write_text(json.dumps({"person": "Kept"}))
    lb.main(["init", str(project), "--person", "Other"])
    assert json.loads(cfg.read_text()) == {"person": "Kept"}


def test_garment_words():
    assert lb.garment("High-waist straight jeans") == "jeans"
    assert lb.garment("Retro court trainers") == "trainers"
    assert lb.garment("Long cardigan with pockets") == "cardigan"
    assert lb.garment("Something odd") == "item"


def test_sheet_items_add_only_basics_in_photo(project):
    p = lb.Project(project)
    ca1, fe1 = p.outfits
    assert p.sheet_items(ca1) == [1, 2, 3]
    assert p.sheet_items(fe1) == [1, 5, 3]
    assert p.hides_basics(ca1) and not p.hides_basics(fe1)


def test_edit_prompt_lists_panels_and_rules(project):
    cfg = json.loads((project / "lookbook.json").read_text())
    cfg["rules"] = ["Every top has sleeves."]
    cfg["base_note"] = "The slippers are replaced by the shoes."
    (project / "lookbook.json").write_text(json.dumps(cfg))
    p = lb.Project(project)
    ca1, fe1 = p.outfits
    text = lb.edit_prompt(p, ca1, "front", project / "tryon/CA1_front.png")
    assert "- Panel 3: the trainers — Beta Leather trainers, colour white." in text
    assert "has sleeves" in text and "slippers are replaced" in text
    assert lb.NO_OUTER in text
    assert str(project / "tryon/CA1_front.png") in text
    fe = lb.edit_prompt(p, fe1, "threequarter", project / "x.png")
    assert lb.NO_OUTER not in fe
    assert "tights from the product sheet" in fe
    assert "three-quarter turn" in fe


def test_problems_reports_bad_data(project):
    outfits = json.loads((project / "data/outfits.json").read_text())
    outfits.append(
        {"id": "X_1", "cat": "Nope", "name": "n", "items": [99], "why": "w", "styling": "s"}
    )
    outfits.append(dict(outfits[0]))
    (project / "data/outfits.json").write_text(json.dumps(outfits))
    found = lb.problems(lb.Project(project))
    joined = "\n".join(found)
    assert "item 99 is missing" in joined
    assert "category 'Nope'" in joined
    assert "must not contain '_'" in joined
    assert "CA1: duplicate id" in joined
    assert "photos/face.jpg is missing" in joined


def test_payload_totals_basics_and_links(project):
    payload = lb.build_payload(lb.Project(project), with_images=False)
    ca1, fe1 = payload["outfits"]
    assert ca1["total"] == 109.94
    assert fe1["total"] == 148.98
    assert ca1["items"][0]["url"] == "https://en.zalando.de/slug-1.html"
    caps = payload["basics"]["capsule"]
    assert caps == {"outfits": 1, "count": 4, "sum": 347.94}
    assert payload["config"]["slug"] == "sam-s-lookbook-winter"
    assert payload["basics"]["photo"] is None


def test_render_escapes_script_end(project):
    p = lb.Project(project)
    payload = lb.build_payload(p, with_images=False)
    payload["outfits"][0]["why"] = "</script><b>x"
    html = lb.render(payload)
    assert "/*__DATA__*/" not in html
    assert "</script><b>" not in html
    assert '"slug": "sam-s-lookbook-winter"' in html


def test_jobs_cover_every_pose(project):
    assert lb.Project(project).jobs({"FE1"}) == ["FE1_front", "FE1_threequarter"]


def test_ratings_import(project, tmp_path_factory, capsys):
    export = {
        "schema": "lookbook-ratings/1",
        "slug": "sam-s-lookbook-winter",
        "round": 1,
        "outfits": {
            "CA1": {"cat": "Casual", "name": "Olive", "rating": 2, "fav": False, "note": ""},
            "FE1": {"cat": "Festive", "name": "Night", "rating": 5, "fav": True, "note": "Love it"},
        },
    }
    f = tmp_path_factory.mktemp("dl") / "ratings.json"
    f.write_text(json.dumps(export))
    lb.main(["ratings", str(project), str(f)])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("FE1") and "Love it" in out[0]
    assert (project / "data/ratings/round1.json").exists()


def test_ratings_rejects_other_files(project, tmp_path_factory):
    f = tmp_path_factory.mktemp("dl") / "x.json"
    f.write_text("{}")
    with pytest.raises(SystemExit, match="not a lookbook ratings export"):
        lb.main(["ratings", str(project), str(f)])


def test_hidden_basics_outfit_shows_everything_but_stays_off_the_dashboard(project):
    outfits = json.loads((project / "data/outfits.json").read_text())
    outfits.append(
        {
            "id": "BASICS",
            "items": [1, 2],
            "styling": "Jacket worn open.",
            "hidden": True,
            "show_basics": True,
        }
    )
    (project / "data/outfits.json").write_text(json.dumps(outfits))
    p = lb.Project(project)
    hidden = p.outfits[-1]
    assert p.sheet_items(hidden) == [1, 2, 4, 3]
    assert not p.hides_basics(hidden)
    assert lb.NO_OUTER not in lb.edit_prompt(p, hidden, "front", project / "x.png")
    assert not [x for x in lb.problems(p) if "BASICS" in x]
    payload = lb.build_payload(p, with_images=False)
    assert [o["id"] for o in payload["outfits"]] == ["CA1", "FE1"]
    assert payload["basics"]["capsule"]["outfits"] == 1


def test_tryon_without_pending_list_explains(project, monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _: "/usr/bin/codex")
    with pytest.raises(SystemExit, match="Run `prompts` first"):
        lb.main(["tryon", str(project)])
