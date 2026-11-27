#!/usr/bin/env python3
"""Build a personal lookbook: product sheets, try-on prompts, Codex edits and the dashboard.

Every command takes the project directory first. Run `lookbook.py <command> --help` for details.
Needs ImageMagick 7 (`magick`) for images and the Codex CLI (`codex`) for try-on photos.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "dashboard_template.html"
CDN = "https://img01.ztat.net/article/spp-media-p1/{img}?imwidth=800"
ITEM_FIELDS = ["id", "brand", "name", "colour", "price", "slug", "img"]

DEFAULT_CONFIG = {
    "person": "",
    "slug": "",
    "round": 1,
    "title": "",
    "intro": "",
    "domain": "en.zalando.de",
    "currency": "EUR",
    "categories": ["Casual", "Smart casual", "Sporty", "Festive"],
    "poses": {
        "front": "They stand facing the camera, as in image 1.",
        "threequarter": "They stand in a three-quarter turn, as in image 1.",
    },
    "keep": (
        "their face, expression, hair, skin, body shape and proportions, pose, hands, "
        "jewellery, and the background"
    ),
    "rules": [],
    "base_note": "",
    "footer": "",
    "previous_round": "",
}

GARMENT = [
    ("tights", "tights"),
    ("jumpsuit", "jumpsuit"),
    ("dress", "dress"),
    ("skirt", "skirt"),
    ("blazer", "blazer"),
    ("gilet", "gilet"),
    ("vest", "vest"),
    ("parka", "parka"),
    ("puffer", "puffer jacket"),
    ("coat", "coat"),
    ("jacket", "jacket"),
    ("hoodie", "hoodie"),
    ("cardigan", "cardigan"),
    ("fleece", "fleece jacket"),
    ("blouse", "blouse"),
    ("shirt", "shirt"),
    ("sweatshirt", "sweatshirt"),
    ("jumper", "jumper"),
    ("pullover", "jumper"),
    ("sweater", "jumper"),
    ("top", "top"),
    ("jeans", "jeans"),
    ("joggers", "jogging trousers"),
    ("leggings", "leggings"),
    ("shorts", "shorts"),
    ("pants", "trousers"),
    ("trousers", "trousers"),
    ("boots", "boots"),
    ("bootie", "ankle boots"),
    ("trainers", "trainers"),
    ("sneakers", "trainers"),
    ("loafers", "loafers"),
    ("ballet", "ballet flats"),
    ("flats", "flat shoes"),
    ("sandals", "sandals"),
    ("shoes", "shoes"),
    ("scarf", "scarf"),
    ("bag", "bag"),
]

EDIT_PROMPT = """Use your image generation tool in EDIT mode. Attached image 1 is a real photo of a person; use it as the base image to edit. Attached image 2 is a close-up of their face for reference. Attached image 3 is a product sheet with numbered panels; each panel is one exact product.

Edit ONLY their clothes and shoes. Keep everything else from image 1 exactly as it is: {keep}. {pose} Do not slim them, do not change their face, do not move the camera.

Dress them in these exact products. Reproduce colour, fabric, cut, length and neckline faithfully, and ignore any other clothes shown in the panels:
{lines}
How it is worn: {styling}
{rules}

Output one photorealistic image with the same framing and aspect ratio as image 1.
Pass the three attached images directly to the image generation tool. Do not create any other files.
When the image is generated, copy the final PNG file to exactly this path: {out}
Reply with just the output path when done."""

NO_OUTER = (
    "They wear NO coat and NO jacket: the outfit is shown indoors, "
    "and the top layer is the one listed above."
)


class LookbookError(Exception):
    pass


def garment(name: str) -> str:
    n = name.lower()
    for key, label in GARMENT:
        if key in n:
            return label
    return "item"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "lookbook"


class Project:
    def __init__(self, root: Path):
        self.root = root.resolve()
        cfg_path = self.root / "lookbook.json"
        if not cfg_path.exists():
            raise LookbookError(f"{cfg_path} not found. Run `lookbook.py init` first.")
        self.config = {**DEFAULT_CONFIG, **json.loads(cfg_path.read_text())}
        if not self.config["slug"]:
            self.config["slug"] = slugify(self.config["title"] or self.config["person"])
        self.items = self._items()
        self.outfits = self._json("data/outfits.json", [])
        self.notes = self._json("data/notes.json", {})
        self.basics = self._json("data/basics.json", {"items": []})
        self.palette = self._json("data/palette.json", {})

    def _json(self, rel, default):
        p = self.root / rel
        return json.loads(p.read_text()) if p.exists() else default

    def _items(self) -> dict[str, dict]:
        p = self.root / "data/items.tsv"
        if not p.exists():
            return {}
        with p.open(newline="") as f:
            return {r["id"]: r for r in csv.DictReader(f, delimiter="\t")}

    def path(self, *parts) -> Path:
        return self.root.joinpath(*parts)

    def item(self, iid) -> dict:
        try:
            return self.items[str(iid)]
        except KeyError:
            raise LookbookError(f"item {iid} is used but missing from data/items.tsv") from None

    def sheet_items(self, outfit: dict) -> list:
        basics = self.basics.get("items", [])
        if outfit.get("show_basics"):
            extra = [b["id"] for b in basics]
        elif outfit.get("basics"):
            extra = [b["id"] for b in basics if b.get("in_photo")]
        else:
            extra = []
        return list(outfit["items"]) + [i for i in extra if i not in outfit["items"]]

    def hides_basics(self, outfit: dict) -> bool:
        if outfit.get("show_basics"):
            return False
        return bool(outfit.get("basics")) and any(
            not b.get("in_photo") for b in self.basics.get("items", [])
        )

    def jobs(self, outfit_ids=None) -> list[str]:
        ids = [o["id"] for o in self.outfits if not outfit_ids or o["id"] in outfit_ids]
        return [f"{oid}_{pose}" for oid in ids for pose in self.config["poses"]]


def problems(p: Project) -> list[str]:
    out = []
    cats = set(p.config["categories"])
    seen = set()
    for o in p.outfits:
        required = (
            ("id", "items", "styling")
            if o.get("hidden")
            else ("id", "cat", "name", "items", "why", "styling")
        )
        for key in required:
            if key not in o:
                out.append(f"outfit {o.get('id', '?')}: missing '{key}'")
        oid = o.get("id")
        if oid in seen:
            out.append(f"outfit {oid}: duplicate id")
        seen.add(oid)
        if not o.get("hidden") and o.get("cat") not in cats:
            out.append(f"outfit {oid}: category '{o.get('cat')}' is not in lookbook.json")
        if "_" in str(oid):
            out.append(f"outfit {oid}: ids must not contain '_'")
        for iid in o.get("items", []):
            if str(iid) not in p.items:
                out.append(f"outfit {oid}: item {iid} is missing from data/items.tsv")
    for b in p.basics.get("items", []):
        if str(b.get("id")) not in p.items:
            out.append(f"basics: item {b.get('id')} is missing from data/items.tsv")
    for iid, it in p.items.items():
        try:
            float(it["price"])
        except (TypeError, ValueError):
            out.append(f"item {iid}: price '{it['price']}' is not a number")
    for pose in p.config["poses"]:
        if not p.path("photos", f"{pose}.jpg").exists():
            out.append(f"photos/{pose}.jpg is missing (one base photo per pose)")
    if not p.path("photos", "face.jpg").exists():
        out.append("photos/face.jpg is missing (a close-up crop of the face)")
    return out


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def image_size(path: Path) -> tuple[int, int]:
    w, h = run(["magick", "identify", "-format", "%w %h", f"{path}[0]"]).stdout.split()
    return int(w), int(h)


def magick_resize(src: Path, dst: Path, size: str, quality: int) -> None:
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["magick", str(src), "-resize", size, "-strip", "-quality", str(quality), str(dst)])


def cmd_init(args) -> None:
    root = Path(args.dir)
    for d in ("photos", "data/ratings", "products", "sheets", "prompts", "tryon", "archive"):
        (root / d).mkdir(parents=True, exist_ok=True)
    cfg = root / "lookbook.json"
    if not cfg.exists():
        person = args.person or "My"
        conf = {**DEFAULT_CONFIG, "person": args.person, "domain": args.domain}
        conf["title"] = f"{person}'s lookbook" if args.person else "My lookbook"
        conf["slug"] = (
            slugify(f"{conf['title']}-{args.season}") if args.season else slugify(conf["title"])
        )
        cfg.write_text(json.dumps(conf, indent=1, ensure_ascii=False) + "\n")
    tsv = root / "data/items.tsv"
    if not tsv.exists():
        tsv.write_text("\t".join(ITEM_FIELDS) + "\n")
    for rel, empty in (("data/outfits.json", []), ("data/notes.json", {})):
        if not (root / rel).exists():
            (root / rel).write_text(json.dumps(empty) + "\n")
    print(
        f"Project ready at {root.resolve()}. Put base photos in photos/<pose>.jpg and photos/face.jpg."
    )


def cmd_check(args) -> None:
    p = Project(Path(args.dir))
    found = problems(p)
    for line in found:
        print("PROBLEM", line)
    missing = sorted(
        {str(i) for o in p.outfits for i in p.sheet_items(o)}
        - {f.stem for f in p.path("products").glob("*.jpg")}
    )
    if missing:
        print("NO IMAGE for items:", ", ".join(missing), "(run `images`)")
    print(f"{len(p.outfits)} outfits, {len(p.items)} items, {len(found)} problems")
    if found:
        sys.exit(1)


def cmd_images(args) -> None:
    p = Project(Path(args.dir))
    p.path("products").mkdir(exist_ok=True)
    got = 0
    for iid, it in p.items.items():
        dst = p.path("products", f"{iid}.jpg")
        if dst.exists() or not it.get("img"):
            continue
        req = urllib.request.Request(CDN.format(img=it["img"]), headers={"User-Agent": "lookbook"})
        with urllib.request.urlopen(req, timeout=30) as r, dst.open("wb") as f:
            shutil.copyfileobj(r, f)
        got += 1
    print(got, "product images downloaded")


def outfit_lines(p: Project, outfit: dict) -> str:
    out = []
    for k, iid in enumerate(p.sheet_items(outfit)):
        it = p.item(iid)
        out.append(
            f"- Panel {k + 1}: the {garment(it['name'])} — {it['brand']} {it['name']}, colour {it['colour']}."
        )
    return "\n".join(out)


def edit_prompt(p: Project, outfit: dict, pose: str, out: Path) -> str:
    rules = list(p.config["rules"])
    if p.config["base_note"]:
        rules.append(p.config["base_note"])
    if any("tights" in p.item(i)["name"].lower() for i in outfit["items"]):
        rules.append("The legs show the tights from the product sheet.")
    if p.hides_basics(outfit):
        rules.append(NO_OUTER)
    return EDIT_PROMPT.format(
        keep=p.config["keep"],
        pose=p.config["poses"][pose],
        lines=outfit_lines(p, outfit),
        styling=outfit["styling"],
        rules=" ".join(rules),
        out=out,
    )


def build_sheet(p: Project, outfit: dict) -> Path:
    files = [p.path("products", f"{i}.jpg") for i in p.sheet_items(outfit)]
    for f in files:
        if not f.exists():
            raise LookbookError(f"{f} is missing. Run `images` first.")
    dst = p.path("sheets", f"{outfit['id']}.jpg")
    if dst.exists() and all(dst.stat().st_mtime >= f.stat().st_mtime for f in files):
        return dst
    args = []
    for k, f in enumerate(files):
        args += ["-label", str(k + 1), str(f)]
    dst.parent.mkdir(exist_ok=True)
    run(
        ["magick", "montage", *args, "-tile", f"{len(files)}x1", "-geometry", "420x620+8+8"]
        + ["-pointsize", "40", "-background", "white", str(dst)]
    )
    return dst


def cmd_prompts(args) -> None:
    p = Project(Path(args.dir))
    found = [x for x in problems(p) if not x.startswith("photos/")]
    if found:
        raise LookbookError("fix these first:\n  " + "\n  ".join(found))
    p.path("prompts").mkdir(exist_ok=True)
    pending = []
    for o in p.outfits:
        if args.ids and o["id"] not in args.ids:
            continue
        build_sheet(p, o)
        for pose in p.config["poses"]:
            jid = f"{o['id']}_{pose}"
            out = p.path("tryon", f"{jid}.png")
            p.path("prompts", f"{jid}.txt").write_text(edit_prompt(p, o, pose, out))
            if not out.exists():
                pending.append(jid)
    p.path("prompts", "pending.txt").write_text("".join(j + "\n" for j in pending))
    print(len(pending), "try-on jobs pending:", " ".join(pending))


def codex_job(p: Project, jid: str) -> str:
    oid, pose = jid.rsplit("_", 1)
    out = p.path("tryon", f"{jid}.png")
    if out.exists():
        return f"SKIP {jid}"
    prompt = p.path("prompts", f"{jid}.txt")
    if not prompt.exists():
        return f"NOPROMPT {jid} (run `prompts`)"
    cmd = ["codex", "exec", "--skip-git-repo-check", "-C", str(p.root), "-s", "workspace-write"]
    for img in (
        p.path("photos", f"{pose}.jpg"),
        p.path("photos", "face.jpg"),
        p.path("sheets", f"{oid}.jpg"),
    ):
        cmd += ["-i", str(img)]
    cmd += ["--", prompt.read_text()]
    with p.path("tryon", f"{jid}.log").open("w") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return f"OK {jid}" if out.exists() else f"MISSING {jid} (see tryon/{jid}.log)"


def cmd_tryon(args) -> None:
    p = Project(Path(args.dir))
    if not shutil.which("codex"):
        raise LookbookError("the Codex CLI (`codex`) is not on PATH")
    pending = p.path("prompts", "pending.txt")
    if not args.jobs and not pending.exists():
        raise LookbookError(
            "no jobs given and prompts/pending.txt is missing. Run `prompts` first."
        )
    jobs = args.jobs or pending.read_text().split()
    p.path("tryon").mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for line in pool.map(lambda j: codex_job(p, j), jobs):
            print(line, flush=True)


def cmd_reject(args) -> None:
    p = Project(Path(args.dir))
    dst = p.path("archive", "rejected")
    dst.mkdir(parents=True, exist_ok=True)
    for jid in args.jobs:
        for ext in ("png", "log"):
            src = p.path("tryon", f"{jid}.{ext}")
            if src.exists():
                n = len(list(dst.glob(f"{jid}*.{ext}")))
                src.rename(dst / f"{jid}{'-' + str(n) if n else ''}.{ext}")
        print("moved", jid, "to archive/rejected")


def item_payload(p: Project, iid) -> dict:
    it = p.item(iid)
    src = p.path("products", f"{iid}.jpg")
    if src.exists():
        magick_resize(src, p.path("web", "items", f"{iid}.jpg"), "320x480>", 80)
    n = p.notes.get(str(iid), {})
    return {
        "id": iid,
        "brand": it["brand"],
        "name": it["name"],
        "colour": it["colour"],
        "price": float(it["price"]),
        "url": f"https://{p.config['domain']}/{it['slug']}",
        "img": f"web/items/{iid}.jpg",
        "size": n.get("size", ""),
        "note": n.get("note", ""),
    }


def look_payload(p: Project, jid: str, base: tuple[int, int] | None):
    src = p.path("tryon", f"{jid}.png")
    if not src.exists():
        return None
    w, h = image_size(src)
    if base and abs((w / h) / (base[0] / base[1]) - 1) > 0.12:
        print(
            f"skipping {src.name}: its shape {w}x{h} does not match the base photo", file=sys.stderr
        )
        return None
    rel = f"web/looks/{jid}.jpg"
    magick_resize(src, p.path(rel), "1000x2000>", 84)
    return {"src": rel, "w": w, "h": h}


def build_payload(p: Project, with_images: bool = True) -> dict:
    poses = p.config["poses"]
    bases = {}
    for pose in poses:
        bp = p.path("photos", f"{pose}.jpg")
        bases[pose] = image_size(bp) if with_images and bp.exists() else None
    outfits = []
    for o in p.outfits:
        if o.get("hidden"):
            continue
        looks = []
        for pose in poses:
            lk = look_payload(p, f"{o['id']}_{pose}", bases[pose]) if with_images else None
            if lk:
                looks.append({**lk, "pose": pose.replace("threequarter", "three-quarter")})
        its = [item_payload(p, i) for i in o["items"]]
        outfits.append(
            {**o, "looks": looks, "items": its, "total": round(sum(i["price"] for i in its), 2)}
        )
    basics = None
    if p.basics.get("items"):
        b_items = [
            {**item_payload(p, b["id"]), "role": b.get("role", ""), "why": b.get("why", "")}
            for b in p.basics["items"]
        ]
        cap = {i["id"]: i["price"] for o in outfits if o.get("basics") for i in o["items"]}
        cap.update({b["id"]: b["price"] for b in b_items})
        photo = p.basics.get("photo")
        basics = {
            "title": p.basics.get("title", "Worn with every outfit"),
            "intro": p.basics.get("intro", ""),
            "with": p.basics.get("with", "Worn with the shared basics."),
            "items": b_items,
            "photo": look_payload(p, photo, bases.get(photo.rsplit("_", 1)[-1]))
            if photo and with_images
            else None,
            "capsule": {
                "outfits": sum(1 for o in outfits if o.get("basics")),
                "count": len(cap),
                "sum": round(sum(cap.values()), 2),
            },
        }
    cfg = {
        k: p.config[k]
        for k in (
            "person",
            "slug",
            "round",
            "title",
            "intro",
            "domain",
            "currency",
            "footer",
            "previous_round",
        )
    }
    cfg["categories"] = p.config["categories"]
    return {"config": cfg, "palette": p.palette, "outfits": outfits, "basics": basics}


def render(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text()
    if "/*__DATA__*/null" not in html:
        raise LookbookError("the dashboard template has no /*__DATA__*/null marker")
    return html.replace("/*__DATA__*/null", data)


def cmd_dashboard(args) -> None:
    p = Project(Path(args.dir))
    found = [x for x in problems(p) if not x.startswith("photos/")]
    if found:
        raise LookbookError("fix these first:\n  " + "\n  ".join(found))
    payload = build_payload(p)
    out = p.path("dashboard.html")
    out.write_text(render(payload))
    n = sum(len(o["looks"]) for o in payload["outfits"])
    print(f"{out} written: {len(payload['outfits'])} outfits, {n} photos")


def load_ratings(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("schema") != "lookbook-ratings/1":
        raise LookbookError(f"{path} is not a lookbook ratings export")
    return data


def cmd_ratings(args) -> None:
    p = Project(Path(args.dir))
    data = load_ratings(Path(args.file))
    if data.get("slug") != p.config["slug"]:
        print(
            f"warning: export is for '{data.get('slug')}', this project is '{p.config['slug']}'",
            file=sys.stderr,
        )
    dst = p.path("data", "ratings", f"round{data.get('round', p.config['round'])}.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if Path(args.file).resolve() != dst.resolve():
        shutil.copyfile(args.file, dst)
    rows = sorted(data["outfits"].items(), key=lambda kv: -(kv[1].get("rating") or 0))
    for oid, r in rows:
        fav = " fav" if r.get("fav") else ""
        note = f"  note: {r['note']}" if r.get("note") else ""
        print(
            f"{oid:6} {r.get('rating') or '-'}★{fav:4} {r.get('cat', '')}: {r.get('name', '')}{note}"
        )
    print("saved to", dst)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create a project folder")
    s.add_argument("dir")
    s.add_argument("--person", default="", help="display name used in the dashboard")
    s.add_argument("--season", default="", help="added to the storage slug, e.g. winter-2026")
    s.add_argument("--domain", default="en.zalando.de", help="Zalando shop domain")
    s.set_defaults(fn=cmd_init)

    for name, fn, hlp in (
        ("check", cmd_check, "validate the data files"),
        ("images", cmd_images, "download missing product images from the Zalando CDN"),
        ("dashboard", cmd_dashboard, "build dashboard.html"),
    ):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("dir")
        s.set_defaults(fn=fn)

    s = sub.add_parser("prompts", help="build product sheets and try-on prompts")
    s.add_argument("dir")
    s.add_argument("ids", nargs="*", help="only these outfit ids")
    s.set_defaults(fn=cmd_prompts)

    s = sub.add_parser("tryon", help="run Codex edits for pending or named jobs")
    s.add_argument("dir")
    s.add_argument("jobs", nargs="*", help="job ids like CA1_front (default: prompts/pending.txt)")
    s.add_argument("--parallel", type=int, default=4)
    s.set_defaults(fn=cmd_tryon)

    s = sub.add_parser("reject", help="move try-on outputs to archive/rejected so they are redone")
    s.add_argument("dir")
    s.add_argument("jobs", nargs="+")
    s.set_defaults(fn=cmd_reject)

    s = sub.add_parser("ratings", help="import a ratings export from the dashboard")
    s.add_argument("dir")
    s.add_argument("file")
    s.set_defaults(fn=cmd_ratings)

    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except LookbookError as e:
        sys.exit(f"lookbook: {e}")
    except subprocess.CalledProcessError as e:
        sys.exit(f"lookbook: {' '.join(e.cmd[:2])} failed: {e.stderr.strip()}")


if __name__ == "__main__":
    main()
