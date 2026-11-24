# Spines in their covers' colours — design

## Why

The stacks show the library as bookcases of spines, but today's spines look "kinda flat and generic":
- They are one muddy colour each: the cover's average, darkened, then boosted with a saturate filter.
- Long titles are cut off with an ellipsis.

The user wants spines that look like real bound books, in colours that resemble the cover, with the whole title readable.

## Goals

- **Look:** each spine looks bound (style A in the mockups), with:
  - cloth texture and rounded shading;
  - two raised ribs near the top and bottom, edged in a trim colour, with a small ✦ ornament;
  - a title label panel.
- **Colour:** the spine takes the cover's main colour. The label takes the cover's second most striking colour (**option 1, chosen by the user**), so each spine carries two of its cover's colours.
- **Title:** the whole title fits. The lettering shrinks for long titles and wraps onto a second or third line where the spine is wide enough.
- **Readability:** lettering and series numbers are readable on every spine, light or dark.

## Non-goals

- The face-out (covers) view, home rows, and book page backgrounds are unchanged. They keep using `cover_color`.
- Spine widths and heights stay as today: width from page count or file size, height varied by the book's id.
- No new fonts. Literata 600 is already shipped (variable 400–700).
- Android Lite and the desktop app get the new look with no work of their own, since both show the web app.

## Anti-goals

- **Slow stacks:** a library of thousands of spines must not open noticeably slower. That rules out measuring each spine's layout in the browser and analysing covers in the browser.
- **Unfinished libraries after updating:** an existing library must not show half its spines in the old style forever.
- **Touching the books:** palettes are made from Loft's stored cover copies, never from the book files.

## Approaches considered

1. **Server picks the palette when it stores a cover; browser fits titles with a canvas (chosen).** Colours are worked out once per cover, in Python with Pillow, which already makes the covers. Title fitting runs in the browser because only the browser knows the font metrics and the spine's size.
   - Cost: a database column and a one-off fill-in for existing books.
2. **Browser picks the palette from the cover thumbnail.** No server change, but every spine needs its cover image downloaded and drawn to a canvas. A 2,000-book shelf would download 2,000 images just to colour the spines. Rejected: slow, and covers are cross-checked per request.
3. **Keep the single average colour and derive the label from it.** Cheap, but it keeps the muddy average the user objected to, and it is option 2's look, not the one chosen.

## Design

### Palette (server)

`covers.spine_palette(img) -> (base, accent)`, two `#rrggbb` strings. The algorithm is the one prototyped and seen in the mockup:

1. Shrink the cover to a 72px-wide thumbnail and quantize it to 8 colours (Pillow median cut).
2. Score each colour by `share × (0.6 + 2.2 × chroma)`, where `chroma = s × (1 − |2l − 1|)` in HLS. A colour that covers a lot and is vivid wins.
3. **base** = the best-scoring colour.
4. **accent** = the best-scoring colour at RGB distance > 70 from base. If there is none (a one-colour cover), accent = base × 0.45, a deep shade of it.

The colours are not darkened or capped. A white cover gives a cream or white spine, true to the book.

**Storage:** in a new `books.spine_colors TEXT` column, as `"#base #accent"`. It is added through `db.MIGRATIONS` and is NULL when there is no cover.

**Where it's set:** every place that sets `cover_color` sets `spine_colors` alongside it:
- the scan's `_set_cover`;
- `editing.set_cover` and `clear_cover`;
- autofill's undo, which clears both.

`store_cover` already has the decoded image, so it computes the palette there. How the two values get back to the callers is left to the plan (a small result type, or a tuple).

**Existing books:** on server start, a background thread fills in `spine_colors` for books that have a cover but no palette.
- It reads `covers/<id>-480.jpg`, Loft's own copy.
- It works in small batches so the database isn't held.
- A book whose cover file is missing or unreadable is skipped without error. It stays on the fallback look until its cover is next stored.
- Until a book is filled in, the browser uses the fallback (below), so nothing looks broken mid-way.

**API:** `book_card` adds `"spine": ["#base", "#accent"]` or `null`. Every list that uses `book_card` gets it, the stacks included.

### Spine (browser, `stacks.js` + `style.css`)

**Colours per spine:**
- `--c` = base.
- `--label` = accent.
- `--letter` = whichever of gilt `#e2c27a`, ink `#1d150e` and paper `#f4ede2` has the highest WCAG contrast on the label.
- `--trim` (rib hairlines, ornament, series number) = gilt, or dark bronze `#4a3a22` when gilt's contrast on the base is under 3:1. This fixes the faint gold numbers on cream spines seen in the mockup.

**Without a palette** (no cover, or not filled in yet):
- base is today's `spineColour(b)`: `cover_color`, else the title-hash colour;
- the label is that colour × 0.45, with gilt or ink letters by contrast.

**Markup inside the existing `<button class="spine">`:**
- two ribs at 8% from the top and 11% from the bottom;
- the ornament;
- the label from 15% to 18% from the bottom, inset 2px from each side;
- the title over the label;
- the series number at the foot.

The reading ribbon (`.is-reading::after`) stays. The `saturate(1.45)` filter goes, because the palette is already true to the cover. Hover still lifts the spine and brightens it slightly.

**Title lettering:** uppercase Literata 600, letter-spacing .05em, line-height 1.12, vertical (`writing-mode: vertical-rl`, `text-orientation: mixed`), centred on the label. The text itself is `spineTitle(b, inSeries)` as today, with the series prefix dropped inside a series.

**Title fitting:** for each spine, the largest size from 12px down to 7px, in 0.5px steps, at which the title fits:
- greedy word-wrap into lines no longer than the label's length minus 12px;
- at most 3 lines;
- `lines × size × 1.12` must be no more than the spine's width minus 5px.

Widths are measured with one shared canvas `measureText`, plus the letter-spacing. Nothing is read back from the layout per spine:
- the label's length comes from the row's height (read once per render), the spine's `--tall` and the label's fixed percentages;
- the width is the spine's own `--w`.

Fitting runs after `document.fonts.ready`. It runs again when the row height changes at the phone breakpoint (one `matchMedia` listener), and when a shelf re-renders.

**When a title can't fit:** a very long title on a very thin spine can fail even at 7px and 3 lines. It is set at 7px and clipped with an ellipsis, as today. The full title stays in the button's `aria-label` and in the pulled-out view.

**Cache:** `sw.js` cache name goes up (`loft-shell-v10`) so installed apps fetch the new CSS and JS.

## Testing

- **Python:** palette on synthetic images:
  - a two-colour image gives those two colours;
  - a one-colour image gives the shade fallback;
  - a white image gives a light base, not a capped dark one.
- **Python:** the store, set, clear and undo paths keep `spine_colors` in step with `cover_color`.
- **Python:** the startup fill-in fills books missing a palette, skips a missing cover file, and leaves filled books alone. `book_card` carries `spine`.
- **JS (node --test):** the fitting function, with a stubbed measurer:
  - a short title stays at 12px on one line;
  - a long title shrinks or wraps;
  - nothing exceeds 3 lines or the width;
  - the 7px fallback.
- **JS (node --test):** the letter and trim colour choice:
  - gilt on dark;
  - ink on light;
  - bronze trim on cream.
- **By eye:** a screenshot of the Assassin's Creed shelf on loft-test, checked against the approved mockup.

## Left to the builder

- How `store_cover` returns the palette alongside the background colour.
- Batch size and pacing of the fill-in thread.
- Exact CSS for the cloth texture and shading. The mockup `spines-a-colours.html` is the reference.
- Whether the fitting helpers live in `stacks.js` or a small `spines.js`. A separate module is easier to test with node.
