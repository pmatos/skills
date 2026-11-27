# Finding clothes on Zalando

These notes come from a real run on `en.zalando.de`. Other country domains use the same site, but confirm each URL pattern once before relying on it.

## Access

- Use the user's own browser, for example through Claude in Chrome. Open a new tab on the shop's home page and run the JavaScript tool in it.
- Plain HTTP requests (curl, Python) to Zalando pages return HTTP 403. The image CDN `img01.ztat.net` works with plain HTTP, which is how `lookbook.py images` downloads product photos.
- Never sign in for the user, never accept cookie banners beyond the necessary ones, and never touch the cart or wishlist.

## Helpers

Paste the contents of `assets/zalando.js` into the JavaScript tool once per tab. It defines:

| Function | Use |
|---|---|
| `zsearch(path, n)` | Fetches a search or category page and returns up to `n` cards with `slug`, `text` and `img`. |
| `zproduct(slug)` | Loads one product page in a hidden iframe and returns brand, name, colour, sizes in stock, details and image URLs. |
| `zverifyAll(slugs)` | Runs `zproduct` over many slugs one at a time in the background and stores the results. |
| `zresults()` | Returns everything that `zverifyAll` has stored so far. |

The JavaScript tool times out after about 45 seconds. Start `zverifyAll` and return at once, then call `zresults()` later. Results are kept in localStorage, so a reload loses nothing.

## Searching

Filter by size in the path, then add a query:

```text
/women/__size-L/?q=v-neck+wool+jumper
/womens-shoes/__size-40/?q=white+leather+trainers
/men/__size-M/?q=merino+crew+neck
```

- Confirm that the size filter works the first time on a new domain or department: the result count should drop. If it does not, find the size filter in the page's own filter links and copy its URL shape.
- Run many small, specific searches: one per garment, colour and fabric. Broad searches return the same best-sellers again and again.
- Card text holds the current price, including sale prices. The price in the product page data can be the original price. Record the card price and note in `data/notes.json` that sale prices change.

## Checking candidates

1. Collect candidate slugs from several searches.
2. Run `zverifyAll` over them. Keep a product only if the person's size is in `inStock`. A size that is close but not listed is not in stock.
3. Read `details` for material, fit and neckline. These matter for rules like "no tight necklines".
4. Look at the images. Render the candidate images as a grid overlay in the page and take a screenshot, or download them and look at a montage. Colour names such as "dark blue" or "berry" are unreliable, and some products are photographed on a model with other clothes.
5. If a brand runs small or large, or reviews mention a fit problem, write the size advice in `notes.json`, for example "40 or 42; runs small".

## Recording a product

Add one row to `data/items.tsv` for each product that you use:

| Column | From |
|---|---|
| `id` | Any unique number. Keep ids stable once outfits use them. |
| `brand`, `name`, `colour` | `zproduct` result, shortened to read well. |
| `price` | The current price from the search card, as a plain number. |
| `slug` | The product path without the domain or query string. |
| `img` | The part of the main image URL after `/spp-media-p1/`, without the query string. |

Then run `lookbook.py images <dir>`.

## Rate limits

Parallel page loads quickly trigger HTTP 429. Keep a pause of two to three seconds between product pages. If 429 appears, wait a few minutes and lengthen the pause. `zverifyAll` skips slugs that it already read.
