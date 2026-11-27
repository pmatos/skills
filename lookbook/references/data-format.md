# Project layout and data formats

```text
<project>/
  lookbook.json        settings for the person and the round
  photos/              front.jpg, threequarter.jpg (one per pose) and face.jpg
  data/
    palette.json       colour and shape analysis
    items.tsv          every product used
    notes.json         size advice and caveats per product
    outfits.json       the outfits of this round
    basics.json        optional shared basics
    ratings/           imported ratings, one file per round
  products/<id>.jpg    product photos (lookbook.py images)
  sheets/<OUTFIT>.jpg  product sheets (lookbook.py prompts)
  prompts/             edit prompts and pending.txt
  tryon/               Codex results and logs
  web/                 resized images for the dashboard
  archive/             earlier rounds and rejected images
  dashboard.html
```

The whole folder is private. Keep it out of any repository that gets pushed.

## lookbook.json

`lookbook.py init` writes the defaults. Fields:

| Field | Meaning |
|---|---|
| `person` | Name shown in the dashboard. Leave it empty to address the reader as "you". |
| `slug` | Key for browser storage. Keep it unique per person and season. |
| `round` | Round number. Raise it for each new round. |
| `title`, `intro` | Dashboard heading and the paragraph below it. |
| `domain` | Zalando shop domain used for product links, such as `en.zalando.de`. |
| `currency` | ISO code for prices, such as `EUR`, `GBP` or `CHF`. |
| `categories` | Category names, in display order. Every outfit's `cat` must be one of them. |
| `poses` | Map from pose name to a sentence that describes the pose. There must be a `photos/<pose>.jpg` for each pose. |
| `keep` | What must stay as in the base photo. |
| `rules` | List of sentences that every try-on prompt adds. |
| `base_note` | One sentence about the base photos, such as "The black socks are replaced by the shoes." |
| `footer` | Where and when prices were read. |
| `previous_round` | Relative link to the archived dashboard of the last round. |

## items.tsv

Tab-separated, with this header row (the columns are separated by tabs):

```text
id  brand  name  colour  price  slug  img
```

`price` is a plain number. `slug` is the product path without the domain. `img` is the CDN path after `/spp-media-p1/`. See `zalando.md`.

The name decides the garment word in the prompt, such as "jumper", "jeans" or "trainers". If a name has no common garment word, add one, for example "Ribbed knit jumper" instead of "Ribbed knit".

## notes.json

```json
{"12": {"size": "40 or 42", "note": "Runs small, reviews say."}}
```

Both fields are optional. The dashboard shows `size` as "order …" and `note` below the product.

## outfits.json

```json
[
  {
    "id": "CA1",
    "cat": "Casual",
    "name": "Teal jumper and dark denim",
    "items": [12, 31],
    "why": "Teal is their strongest colour, and dark wide-leg jeans give a long line.",
    "styling": "Jumper worn loose over the jeans.",
    "basics": true
  }
]
```

- `id` must be unique and must not contain `_`. Use new ids in every round.
- `items` lists products top to toe. Leave out the shared basics. `lookbook.py` adds the basics that appear in photos.
- `basics` is optional. Set it to `true` when the outfit uses the shared basics.

## basics.json

```json
{
  "title": "Worn with every outfit",
  "intro": "Every outfit below goes with these two pieces, so they are bought once.",
  "with": "Worn with the shared trainers. The coat goes on top outside.",
  "items": [
    {"id": 40, "role": "The coat", "why": "Navy goes with every colour in the palette.", "in_photo": false},
    {"id": 41, "role": "The trainers", "why": "Flat, and they work with jeans and satin.", "in_photo": true}
  ],
  "photo": "BASICS_front"
}
```

`in_photo: true` puts the item on every sheet of an outfit that uses the basics. `in_photo: false` keeps it out of the photos, and the prompt then says that no coat or jacket is worn. `photo` is an optional job id whose try-on image shows the basics together.

## palette.json

```json
{
  "summary": "Soft, cool-neutral colouring with low contrast.",
  "shape": "Balanced shoulders and hips. Open necklines and long lines suit them.",
  "best": [{"name": "Teal", "hex": "#1F5F66", "note": "Hero colour"}],
  "neutrals": [{"name": "Soft navy", "hex": "#25324A"}],
  "avoid": "Optic white and pure black next to the face.",
  "rules": "Flats only. Mostly trousers."
}
```

The dashboard uses the first two `best` colours as its accent colours.

## Ratings export

The dashboard's "Save ratings to a file" button downloads:

```json
{
  "schema": "lookbook-ratings/1",
  "slug": "…",
  "round": 1,
  "exported": "2026-11-27T10:00:00.000Z",
  "outfits": {"CA1": {"cat": "Casual", "name": "…", "rating": 5, "fav": true, "note": "…"}}
}
```

`rating` is 0 when the outfit is not rated. `lookbook.py ratings` checks the schema, copies the file to `data/ratings/round<N>.json` and prints a ranking.

Browser storage keys are `lookbook:<slug>:r<round>:…`, so two people or two rounds never share ratings.
