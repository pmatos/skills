---
name: extract-design-system
description: Extract the design system (fonts, logos, colors, CSS tokens, favicons, OG assets) from a public website URL into a fresh local git repo with a fact-only README. Use when the user wants to "extract a design system", "steal a design", "pull fonts and colors from a site", "scrape design tokens", "build a design-system repo from a URL", or prepare assets to upload to claude.ai/design.
user-invocable: true
---

# Extract Design System

Turn a public URL into a local git repo full of that site's real design assets and tokens. Only capture what is actually in the page and its linked resources — never invent colors, fonts, or brand facts from visual inspection.

## Inputs to collect

1. **URL** — the page to extract from. Require a full `https://...`.
2. **Parent directory** — where to create the repo. Default: `~/design-systems/`. Ask; do not assume.
3. **Repo name** — derive from the host (e.g. `example.com` → `example-com`). Offer the default, let the user override.

Confirm all three before running anything.

## Workflow

### Step 1 — Try WebFetch for a first look

Use `WebFetch` on the URL and ask it to return: page title, meta description, and any mentions of brand or site name. This is cheap and gives you enough to confirm the target is what the user expects. If WebFetch is blocked, skip to Step 2 without retrying.

### Step 2 — Run the extractor

```bash
mkdir -p "<parent>/<repo-name>"
uv run /home/pmatos/dev/skills/extract-design-system/scripts/extract.py \
  "<url>" --output "<parent>/<repo-name>"
```

The script uses `requests` + `beautifulsoup4` + `tinycss2` to:

- Fetch the HTML and every linked stylesheet (following `@import` one level).
- Parse `@font-face` rules and download each font file into `fonts/`.
- Extract `:root` / `html` CSS custom properties into `tokens/variables.css`.
- Download favicons, Apple touch icons, and web-manifest icons into `images/favicons/`.
- Save inline `<svg>` blocks (likely logos) into `logos/`.
- Download the Open Graph image into `images/`.
- Snapshot the raw HTML into `source/page.html`.
- Write a machine-readable `manifest.json` and a fact-only `README.md`.

On success it prints a JSON summary (fonts, stylesheets, favicons, inline SVGs, custom-property counts).

### Step 3 — Fallback chain if the page is JS-rendered

If the summary shows near-zero CSS/fonts/SVGs, the site is likely a JS SPA. Render it with a real browser and re-run with `--html`:

**3a. Playwright CLI** (preferred fallback):

```bash
playwright install chromium  # only if not yet installed
cat > /tmp/render.js <<'EOF'
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ userAgent:
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36' });
  await p.goto(process.argv[2], { waitUntil: 'networkidle', timeout: 60000 });
  process.stdout.write(await p.content());
  await b.close();
})();
EOF
node /tmp/render.js "<url>" > /tmp/rendered.html
```

**3b. MCP Playwright tools** (if Node/Playwright CLI fails): use `mcp__plugin_playwright_playwright__browser_navigate`, then `mcp__plugin_playwright_playwright__browser_evaluate` with `() => document.documentElement.outerHTML` to capture HTML. Write it to `/tmp/rendered.html`.

**3c. claude-in-chrome** (last resort): load the tool with `ToolSearch select:mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__get_page_text`, navigate, then use `javascript_tool` to read `document.documentElement.outerHTML`.

Then re-run the extractor with the rendered HTML:

```bash
uv run /home/pmatos/dev/skills/extract-design-system/scripts/extract.py \
  "<url>" --output "<parent>/<repo-name>" --html /tmp/rendered.html
```

### Step 4 — Initialize git and commit

```bash
cd "<parent>/<repo-name>"
git init -q
git add -A
git commit -q -m "Initial extraction from <url>"
```

Report the repo path, a one-line summary of what was captured, and any obvious gaps (e.g. zero fonts — probably means a JS-rendered site; rerun with Step 3).

## Ground rules

- Only record facts present in the page or its linked resources. Never guess colors from visual inspection.
- If a field is missing (no `og:image`, no theme color, no `@font-face`), leave it out of the README — do not invent.
- Respect robots.txt and Terms of Service. If the user asks to extract from a site that disallows scraping, surface this and wait for confirmation.
- The script is idempotent: re-running into the same directory overwrites `manifest.json` and `README.md` and re-downloads assets.

## Output layout

```
<repo-name>/
├── README.md           # fact-only summary
├── manifest.json       # structured extraction record
├── fonts/              # downloaded font files
├── logos/              # inline SVGs (candidate logos)
├── images/             # og:image and other page images
│   └── favicons/       # favicons + apple-touch + web-manifest icons
├── css/                # downloaded stylesheets
├── tokens/
│   ├── variables.css   # extracted :root custom properties
│   └── fonts.css       # rewritten @font-face rules pointing to local files
└── source/
    ├── page.html       # raw/rendered HTML snapshot
    └── manifest.webmanifest  # if the site exposes one
```
