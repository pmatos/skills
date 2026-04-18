#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests>=2.31",
#   "beautifulsoup4>=4.12",
#   "tinycss2>=1.2",
# ]
# ///
"""Extract a website's design system into a local directory.

Fetches HTML (or uses a pre-rendered snapshot from --html), parses linked
stylesheets for @font-face rules and :root custom properties, downloads fonts,
favicons, og:image, inline SVGs, and web-manifest icons. Writes manifest.json
and a fact-only README.md next to the downloaded assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import tinycss2
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT = 25
COLOR_RE = re.compile(
    r"^\s*(#[0-9a-fA-F]{3,8}\b|rgb|rgba|hsl|hsla|oklab|oklch|lab|lch|color)\b"
)
COLOR_NAME_RE = re.compile(r"color|fill|stroke|bg|background|border|surface|tint|shade|brand|accent", re.I)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def attr(tag, name: str, default: str = "") -> str:
    """Return a tag attribute as a plain string (BS4 can return lists for multi-valued attrs)."""
    v = tag.get(name)
    if v is None:
        return default
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return str(v)


def attr_opt(tag, name: str) -> str | None:
    v = tag.get(name)
    if v is None:
        return None
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return str(v)


def safe_name(url: str, fallback: str = "asset") -> str:
    path = urlparse(url).path
    name = Path(path).name or fallback
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._-") or fallback
    name = name[:120]
    # Prefix a short hash of the full URL (including query + path segments)
    # so two distinct URLs that share a basename don't overwrite each other.
    digest = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{digest}-{name}"


def fetch(session: requests.Session, url: str) -> requests.Response | None:
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        log(f"  ! fetch failed {url}: {e}")
        return None


def download_binary(session: requests.Session, url: str, dest: Path) -> Path | None:
    r = fetch(session, url)
    if r is None:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def parse_fontface(css_text: str, base_url: str) -> list[dict]:
    fonts: list[dict] = []
    rules = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True)
    for rule in rules:
        if getattr(rule, "at_keyword", None) != "font-face" or rule.content is None:
            continue
        block = "".join(t.serialize() for t in rule.content)
        family_m = re.search(r"font-family\s*:\s*([^;]+)", block)
        weight_m = re.search(r"font-weight\s*:\s*([^;]+)", block)
        style_m = re.search(r"font-style\s*:\s*([^;]+)", block)
        display_m = re.search(r"font-display\s*:\s*([^;]+)", block)
        raw_urls = re.findall(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", block)
        fonts.append({
            "family": (family_m.group(1).strip().strip("'\"") if family_m else None),
            "weight": weight_m.group(1).strip() if weight_m else None,
            "style": style_m.group(1).strip() if style_m else None,
            "display": display_m.group(1).strip() if display_m else None,
            "urls": [urljoin(base_url, u.strip()) for u in raw_urls],
        })
    return fonts


def parse_custom_props(css_text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    rules = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True)
    for rule in rules:
        if getattr(rule, "type", None) != "qualified-rule" or rule.content is None:
            continue
        selector = "".join(t.serialize() for t in rule.prelude).strip()
        if ":root" not in selector and selector not in ("html", ":host"):
            continue
        block = "".join(t.serialize() for t in rule.content)
        for name, value in re.findall(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;]+)", block):
            props[name] = value.strip()
    return props


def collect_imports(css_text: str, base_url: str) -> list[str]:
    pattern = r"@import\s+(?:url\(\s*)?['\"]?([^'\")]+)['\"]?"
    return [urljoin(base_url, u.strip()) for u in re.findall(pattern, css_text)]


def extract(url: str, out: Path, html_override: str | None = None) -> dict:
    for sub in ("fonts", "logos", "images", "images/favicons", "css", "tokens", "source"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = UA

    # Resolve relative resources against the final URL after any redirects, not
    # the originally requested one — otherwise a redirect to a different host or
    # path silently mis-resolves stylesheets, icons, and images.
    if html_override is not None:
        html = html_override
        # In --html mode we already have the rendered HTML from a browser, but
        # we still need the post-redirect URL as the resolution base. HEAD is
        # cheap; accept its `url` even on non-2xx status because many origins
        # reply 405 for HEAD while still having followed the redirect chain.
        try:
            probe = session.head(url, timeout=TIMEOUT, allow_redirects=True)
            base_url = probe.url or url
        except requests.RequestException:
            base_url = url
    else:
        r = fetch(session, url)
        if r is None:
            raise SystemExit(f"Cannot fetch {url}. Use Playwright to render, then pass --html.")
        html = r.text
        base_url = r.url

    (out / "source" / "page.html").write_text(html, encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    manifest: dict = {
        "source_url": url,
        "final_url": base_url,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "title": (soup.title.string.strip() if soup.title and soup.title.string else None),
        "meta": {},
        "open_graph": {},
        "twitter": {},
        "theme_color": None,
        "lang": attr_opt(soup.html, "lang") if soup.html else None,
        "stylesheets": [],
        "fonts": [],
        "custom_properties": {},
        "color_palette": [],
        "favicons": [],
        "logos_inline_svg": [],
        "images": [],
        "manifest_url": None,
        "rendered_with_js": html_override is not None,
    }

    for m in soup.find_all("meta"):
        name = attr(m, "name").strip()
        prop = attr(m, "property").strip()
        content = attr_opt(m, "content")
        if not content:
            continue
        if name == "description":
            manifest["meta"]["description"] = content
        elif name == "theme-color":
            manifest["theme_color"] = content
        elif name == "author":
            manifest["meta"]["author"] = content
        elif name == "generator":
            manifest["meta"]["generator"] = content
        elif name.startswith("twitter:"):
            manifest["twitter"][name] = content
        if prop.startswith("og:"):
            manifest["open_graph"][prop] = content

    # An HTML document may override relative-URL resolution with <base href>.
    # Fall back to the redirect-aware base_url when no <base> tag is present.
    base_tag = soup.find("base")
    base_href = attr_opt(base_tag, "href") if base_tag else None
    doc_base = urljoin(base_url, base_href) if base_href else base_url

    for link in soup.find_all("link"):
        # `rel` is case-insensitive and space-separated in HTML.
        rel_tokens = {t.lower() for t in attr(link, "rel").split() if t}
        href = attr_opt(link, "href")
        if not href:
            continue
        abs_url = urljoin(doc_base, href)
        if "icon" in rel_tokens or "shortcut" in rel_tokens:
            fname = safe_name(abs_url, "favicon.ico")
            dest = out / "images/favicons" / fname
            if download_binary(session, abs_url, dest):
                manifest["favicons"].append({
                    "url": abs_url,
                    "path": str(dest.relative_to(out)),
                    "rel": " ".join(sorted(rel_tokens)),
                    "sizes": attr_opt(link, "sizes"),
                    "type": attr_opt(link, "type"),
                })
        elif "manifest" in rel_tokens:
            manifest["manifest_url"] = abs_url
        elif "stylesheet" in rel_tokens:
            manifest["stylesheets"].append(abs_url)

    css_queue = list(manifest["stylesheets"])
    seen_css: set[str] = set()
    all_css: list[tuple[str, str]] = []

    for inline in soup.find_all("style"):
        if inline.string:
            all_css.append(("<inline>", inline.string))

    while css_queue:
        cu = css_queue.pop(0)
        if cu in seen_css:
            continue
        seen_css.add(cu)
        r = fetch(session, cu)
        if r is None:
            continue
        text = r.text
        # Use the post-redirect URL so @import and @font-face relative paths
        # resolve against the stylesheet's actual location, not the pre-redirect
        # request URL.
        css_base = r.url
        seen_css.add(css_base)
        fname = safe_name(cu, "style.css")
        if not fname.lower().endswith(".css"):
            fname += ".css"
        (out / "css" / fname).write_text(text, encoding="utf-8")
        all_css.append((css_base, text))
        for imp in collect_imports(text, css_base):
            if imp not in seen_css:
                css_queue.append(imp)

    for src, text in all_css:
        base = src if src != "<inline>" else base_url
        manifest["fonts"].extend(parse_fontface(text, base))
        manifest["custom_properties"].update(parse_custom_props(text))

    # URL → local relative path. When the same URL appears in multiple
    # @font-face rules, every rule should still reference the downloaded file.
    font_url_to_path: dict[str, str] = {}
    for f in manifest["fonts"]:
        downloaded: list[str] = []
        urls = sorted(f["urls"], key=lambda u: 0 if u.lower().endswith(".woff2") else 1)
        for fu in urls:
            if fu.startswith("data:"):
                continue
            cached = font_url_to_path.get(fu)
            if cached is not None:
                downloaded.append(cached)
                continue
            fname = safe_name(fu, "font")
            dest = out / "fonts" / fname
            if download_binary(session, fu, dest):
                rel_path = f"fonts/{fname}"
                font_url_to_path[fu] = rel_path
                downloaded.append(rel_path)
        f["local_paths"] = downloaded

    for i, svg in enumerate(soup.find_all("svg")[:15]):
        inner = str(svg)
        digest = hashlib.md5(inner.encode()).hexdigest()[:8]
        fname = f"inline-{i:02d}-{digest}.svg"
        (out / "logos" / fname).write_text(inner, encoding="utf-8")
        manifest["logos_inline_svg"].append({
            "path": f"logos/{fname}",
            "classes": attr_opt(svg, "class"),
            "id": attr_opt(svg, "id"),
            "aria_label": attr_opt(svg, "aria-label"),
            "viewBox": attr_opt(svg, "viewBox"),
        })

    og_img = manifest["open_graph"].get("og:image") or manifest["twitter"].get("twitter:image")
    if og_img:
        abs_og = urljoin(doc_base, og_img)
        fname = safe_name(abs_og, "og-image")
        dest = out / "images" / fname
        if download_binary(session, abs_og, dest):
            manifest["images"].append({
                "source": "og:image",
                "url": abs_og,
                "path": f"images/{fname}",
            })

    if manifest["manifest_url"]:
        r = fetch(session, manifest["manifest_url"])
        if r is not None:
            (out / "source" / "manifest.webmanifest").write_text(r.text, encoding="utf-8")
            # Resolve icon hrefs from the post-redirect manifest URL so a
            # manifest that redirected to a different path/host still yields
            # correct icon URLs.
            manifest_base = r.url
            try:
                wm = r.json()
                for icon in wm.get("icons", []) or []:
                    src_icon = icon.get("src")
                    if not src_icon:
                        continue
                    abs_icon = urljoin(manifest_base, src_icon)
                    fname = safe_name(abs_icon, "icon")
                    dest = out / "images/favicons" / fname
                    if download_binary(session, abs_icon, dest):
                        manifest["favicons"].append({
                            "url": abs_icon,
                            "path": f"images/favicons/{fname}",
                            "rel": "manifest-icon",
                            "sizes": icon.get("sizes"),
                            "type": icon.get("type"),
                        })
            except (ValueError, KeyError):
                pass

    for name, val in manifest["custom_properties"].items():
        if COLOR_NAME_RE.search(name) and COLOR_RE.search(val):
            manifest["color_palette"].append({"name": name, "value": val.strip()})

    if manifest["custom_properties"]:
        lines = [":root {"]
        for k, v in sorted(manifest["custom_properties"].items()):
            lines.append(f"  {k}: {v};")
        lines.append("}")
        (out / "tokens" / "variables.css").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if manifest["fonts"]:
        lines = []
        for f in manifest["fonts"]:
            local = f.get("local_paths") or []
            srcs = [f"url('../{p}')" for p in local] or [f"url('{u}')" for u in f["urls"]]
            fam = f.get("family") or "unknown"
            lines.append("@font-face {")
            lines.append(f"  font-family: '{fam}';")
            if f.get("weight"):
                lines.append(f"  font-weight: {f['weight']};")
            if f.get("style"):
                lines.append(f"  font-style: {f['style']};")
            if f.get("display"):
                lines.append(f"  font-display: {f['display']};")
            lines.append(f"  src: {', '.join(srcs)};")
            lines.append("}")
        (out / "tokens" / "fonts.css").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_readme(out, manifest)
    return manifest


def write_readme(out: Path, m: dict) -> None:
    host = urlparse(m["source_url"]).netloc
    lines: list[str] = []
    title = m["title"] or host
    lines.append(f"# {title} — Design System Extract")
    lines.append("")
    lines.append(f"- **Source**: {m['source_url']}")
    lines.append(f"- **Host**: {host}")
    lines.append(f"- **Extracted**: {m['extracted_at']}")
    if m["lang"]:
        lines.append(f"- **Language**: `{m['lang']}`")
    if m["rendered_with_js"]:
        lines.append("- **Rendered via**: headless browser (JS-rendered page)")
    lines.append("")

    desc = m["meta"].get("description")
    if desc:
        lines.append("## About")
        lines.append("")
        lines.append(f"> {desc}")
        lines.append("")

    if m["theme_color"]:
        lines.append(f"**Theme color:** `{m['theme_color']}`")
        lines.append("")

    if m["color_palette"]:
        lines.append("## Color palette")
        lines.append("")
        lines.append("| Variable | Value |")
        lines.append("|----------|-------|")
        for c in m["color_palette"]:
            lines.append(f"| `{c['name']}` | `{c['value']}` |")
        lines.append("")

    if m["fonts"]:
        lines.append("## Typography")
        lines.append("")
        lines.append("| Family | Weight | Style | Files |")
        lines.append("|--------|--------|-------|-------|")
        for f in m["fonts"]:
            files = ", ".join(f"`{p}`" for p in f.get("local_paths", [])) or "*(not downloaded)*"
            lines.append(
                f"| {f.get('family') or '—'} | {f.get('weight') or '—'} | "
                f"{f.get('style') or '—'} | {files} |"
            )
        lines.append("")

    if m["logos_inline_svg"]:
        lines.append("## Inline SVGs (candidate logos)")
        lines.append("")
        for s in m["logos_inline_svg"]:
            bits = [f"`{s['path']}`"]
            if s.get("aria_label"):
                bits.append(f"aria-label=\"{s['aria_label']}\"")
            if s.get("classes"):
                bits.append(f"class=\"{s['classes']}\"")
            if s.get("viewBox"):
                bits.append(f"viewBox=\"{s['viewBox']}\"")
            lines.append(f"- {' — '.join(bits)}")
        lines.append("")

    if m["favicons"]:
        lines.append("## Favicons / icons")
        lines.append("")
        for fav in m["favicons"]:
            bits = [f"`{fav['path']}`"]
            if fav.get("sizes"):
                bits.append(f"sizes={fav['sizes']}")
            if fav.get("type"):
                bits.append(f"type={fav['type']}")
            bits.append(f"rel={fav['rel']}")
            lines.append(f"- {' — '.join(bits)}")
        lines.append("")

    if m["images"]:
        lines.append("## Images")
        lines.append("")
        for img in m["images"]:
            lines.append(f"- `{img['path']}` (from {img['source']})")
        lines.append("")

    if m["open_graph"]:
        lines.append("## Open Graph metadata")
        lines.append("")
        for k, v in m["open_graph"].items():
            lines.append(f"- `{k}`: {v}")
        lines.append("")

    if m["stylesheets"]:
        lines.append("## Stylesheets captured")
        lines.append("")
        for s in m["stylesheets"]:
            lines.append(f"- {s}")
        lines.append("")

    lines.append("## Directory layout")
    lines.append("")
    lines.append("```")
    lines.append("fonts/       downloaded font files")
    lines.append("logos/       inline SVGs from the page (candidate logos)")
    lines.append("images/      og:image and other page images")
    lines.append("  favicons/  favicons, apple-touch-icons, web-manifest icons")
    lines.append("css/         downloaded stylesheets")
    lines.append("tokens/      variables.css + fonts.css derived from CSS")
    lines.append("source/      raw HTML + web manifest snapshot")
    lines.append("manifest.json  structured record of everything captured")
    lines.append("```")
    lines.append("")
    lines.append(
        "*All content extracted directly from the source page and its linked resources. "
        "Nothing here was inferred from visual inspection.*"
    )

    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="Full https URL to extract from")
    ap.add_argument("--output", required=True, type=Path, help="Target directory (will be created)")
    ap.add_argument("--html", type=Path, default=None,
                    help="Path to a pre-rendered HTML file (from Playwright). Skips requests fetch.")
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    html_override = args.html.read_text(encoding="utf-8") if args.html else None
    manifest = extract(args.url, args.output, html_override=html_override)

    summary = {
        "output": str(args.output),
        "title": manifest["title"],
        "host": urlparse(manifest["source_url"]).netloc,
        "stylesheets": len(manifest["stylesheets"]),
        "fonts": len(manifest["fonts"]),
        "fonts_downloaded": sum(len(f.get("local_paths") or []) for f in manifest["fonts"]),
        "custom_properties": len(manifest["custom_properties"]),
        "color_palette": len(manifest["color_palette"]),
        "favicons": len(manifest["favicons"]),
        "inline_svgs": len(manifest["logos_inline_svg"]),
        "images": len(manifest["images"]),
        "rendered_with_js": manifest["rendered_with_js"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
