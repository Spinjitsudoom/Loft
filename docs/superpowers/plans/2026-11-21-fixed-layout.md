# Fixed-Layout Books Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EPUB and Kindle books that declare a fixed layout are read as pages, each exactly as designed (pictures, fonts, positions), scaled to the screen, in the page-curl reader comics use.

**Architecture:** `epub.py` detects fixed layout and page sizes into a new `FlowBook.fixed`; the flow outline route reports it. For such books the existing chapter route returns a cleaned, self-contained page document (new module `fixedpage.py`: book CSS inlined and cleaned with `tinycss2`, markup cleaned with `nh3`, every reference rewritten to the book's own resources). The resource route also serves fonts. In the browser a `FixedReader` (new `web/js/fixed.js`, extends the comics `Reader`) shows each page in a sandboxed, script-less iframe scaled to its leaf; zoom gains a page-frame mode. Downloads keep working through the flowing-book path (chapters plus the `/res/` files they name).

**Tech Stack:** Python 3.14, FastAPI, nh3, tinycss2 (new), plain ES modules, StPageFlip.

**Spec:** `docs/superpowers/specs/2026-11-21-fixed-layout-design.md`

## Global Constraints

- Fixed layout when the OPF metadata has `<meta property="rendition:layout">pre-paginated</meta>`, or `<meta name="fixed-layout" content="true"/>`. Nothing at scan time.
- Page size order: the page's `<meta name="viewport" content="width=…, height=…">`; else OPF `rendition:viewport` (`width=…, height=…`) or `<meta name="original-resolution" content="WxH"/>`; else an SVG page's `viewBox`; else `[1000, 1500]` (2:3). Never zero, negative or non-numeric.
- Outline `GET /api/files/{id}/flow` adds, only for fixed books, `"fixed": {"sizes": [[w, h], …], "spread": bool}` (one size per chapter; `spread` false only when `rendition:spread` is `none`) and `"rtl": bool` (spine `page-progression-direction="rtl"`).
- A fixed page's document carries `Content-Security-Policy: default-src 'none'; img-src 'self' blob: data:; font-src 'self' blob: data:; style-src 'unsafe-inline'` both as a response header and as a `<meta http-equiv>` first in its `<head>`.
- In the reader each page iframe has `sandbox="allow-same-origin"` (never `allow-scripts`), `pointer-events: none`, and its document set through `srcdoc`.
- CSS `url(…)`: kept only when it resolves (relative to the stylesheet it's in, or to the page for `<style>` and `style=""`) to a picture or font inside the book, rewritten to `/api/files/{id}/res/<path>`; otherwise the declaration is dropped. No `@import` of anything outside the book; no `expression`, `behavior`, `-moz-binding`, `javascript:`.
- Flowing (reflowable) books render exactly as before; their chapter HTML is unchanged.
- Fonts served by `/res/`: `.otf` `font/otf`, `.ttf` `font/ttf`, `.woff` `font/woff`, `.woff2` `font/woff2` (also the OPF's `application/vnd.ms-opentype`, `application/font-woff`, `application/x-font-ttf`, `application/x-font-otf`), with `X-Content-Type-Options: nosniff`.
- Copy: plain, sentence case, curly apostrophes (’) in user-facing text.
- Keep the local test server (`loft-test` user service, port 4545, loft-dev library) working: restart it after Python changes; `uv sync` the venv after adding `tinycss2`.
- Commit only when the user asks.

## Review Focus

1. A page's CSS tries to reach outside the book: `url(http://…)`, protocol-relative `url(//…)`, an escaped `u\rl(…)`, `@import url(https://…)`, a remote `@font-face src` → nothing outside survives. (Task 2: `test_css_never_reaches_outside_the_book`.)
2. A page carries `<script>`, `onload=`, `<iframe>`, `<object>`, `<embed>`, `<form>`, `<meta http-equiv="refresh">`, `<base href>`, `<link>` to a remote sheet, `javascript:` links → none survive. (Task 2: `test_nothing_that_runs_or_leaves_survives`.)
3. Pages without a viewport → sizes fall back in order, never zero. (Task 1: `test_page_sizes_fall_back_in_order`.)
4. A position saved while the book was read as flowing text (`locator.chapter`, or `page` out of 1001) → reopens on the right page. (Task 4: `startPage` in `tests/js/fixed.test.mjs`.)
5. CSS paths relative to the stylesheet (`../Fonts/x.otf` from `OEBPS/Styles/a.css`, as in *Wedding Crashers*) resolve against the stylesheet, not the page. (Task 2: `test_css_urls_resolve_against_their_stylesheet`.)

---

### Task 1: Detecting fixed layout and page sizes

**Files:**
- Modify: `src/loft/flow.py` (add `FixedLayout`, `FlowBook.fixed`), `src/loft/epub.py` (`_structure`), `src/loft/app.py` (`flow_outline`)
- Test: `tests/test_fixed_layout.py` (new; holds a `fixed_epub(path, *, pages, css=None, fonts=None, images=None, metadata="", spine_attrs="", item_props=None)` helper that writes a minimal EPUB 3: `pages` is `[(href, body_html, viewport or None)]`, each page linking every stylesheet in `css`)

**Interfaces:**
- Produces: `@dataclass FixedLayout: sizes: list[tuple[int, int]]; spread: bool = True; rtl: bool = False` in `flow.py`; `FlowBook.fixed: FixedLayout | None = None`; outline JSON as in Global Constraints.

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_fixed_layout_book_is_found_with_its_page_sizes(tmp_path): ...
    # metadata '<meta property="rendition:layout">pre-paginated</meta>', two pages with viewports
    # "width=706, height=1024" → open_epub(...).fixed.sizes == [(706, 1024), (706, 1024)], spread True, rtl False

def test_the_kindle_way_of_saying_it_counts_too(tmp_path): ...
    # metadata '<meta name="fixed-layout" content="true"/><meta name="original-resolution" content="600x800"/>',
    # pages without viewports → fixed.sizes == [(600, 800), (600, 800)]

def test_page_sizes_fall_back_in_order(tmp_path): ...
    # rendition:viewport "width=500, height=700" in metadata; page 1 has its own viewport 400x600,
    # page 2 none, → [(400, 600), (500, 700)]; with no book viewport, a page holding
    # <svg viewBox="0 0 1299 1886"> → (1299, 1886), and a page with nothing → (1000, 1500)

def test_spreads_and_direction_come_from_the_book(tmp_path): ...
    # rendition:spread none → spread False; <spine page-progression-direction="rtl"> → rtl True

def test_flowing_books_are_not_fixed(make_rich_epub, tmp_path): ...
    # open_epub(...).fixed is None

def test_the_outline_says_so(client, tmp_path): ...
    # a fixed book added to the library (cfg books dir + scan): GET /api/files/{id}/flow has
    # fixed == {"sizes": [[706, 1024], ...], "spread": True} and rtl False; a flowing book's outline has no "fixed"
```

- [ ] **Step 2: Run them to verify they fail** — `bash test.sh -q tests/test_fixed_layout.py` → FAIL (`FlowBook` has no `fixed`).
- [ ] **Step 3: Implement** — read the OPF metadata `meta` elements (`property` and `name` forms) in `_structure`; for each fixed page, parse its viewport `meta` with a regex on `width\s*=\s*(\d+)` / `height\s*=\s*(\d+)` (pages are read through the zip already open), then the fallbacks. Kindle AZW3 needs nothing extra: it unpacks to an EPUB that `open_epub` reads.
- [ ] **Step 4: Run them to verify they pass** — `bash test.sh -q` → all pass.
- [ ] **Step 5: Commit** — `git commit -m "Fixed-layout books are recognised, with their page sizes"`

### Task 2: A fixed page, cleaned and self-contained

**Files:**
- Create: `src/loft/fixedpage.py`
- Modify: `src/loft/app.py` (`flow_chapter`: when `book.fixed`, return `page_document(...)` with the CSP header), `pyproject.toml` + `uv.lock` (`tinycss2>=1.4`; `uv lock`, then `uv sync` into `~/.local/share/loft/venv`)
- Test: `tests/test_fixed_layout.py`

**Interfaces:**
- Consumes: Task 1's `FlowBook.fixed`.
- Produces: `page_document(raw: str, *, base: str, book: FlowBook, resource_url: Callable[[str], str]) -> str` — a whole `<!doctype html>` document; `CSP: str` (the policy in Global Constraints); `fonts(book) -> dict[str, Resource]` helper for Task 3 (the book's font resources by path).

- [ ] **Step 1: Write the failing tests** (each on a `fixed_epub` built for it, rendered with `resource_url=lambda p: f"/api/files/1/res/{p}"`):

```python
def test_a_page_keeps_its_look(tmp_path): ...
    # Wedding-Crashers-like page: body id="page0003" class="odd book-type-fixed", a linked sheet with
    # "#page0003 .image-container {background: url(../Images/p.jpeg) no-repeat}" and
    # "@font-face {font-family: T; src: url(../Fonts/t.otf)}", divs with ids and classes, text.
    # The document: starts "<!doctype html>", has the CSP meta first in <head>, <body id="page0003"
    # class="odd book-type-fixed">, the div ids/classes and text, "url(/api/files/1/res/OEBPS/Images/p.jpeg)"
    # and "url(/api/files/1/res/OEBPS/Fonts/t.otf)".

def test_css_urls_resolve_against_their_stylesheet(tmp_path): ...
    # the sheet at OEBPS/Styles/a.css names ../Fonts/t.otf → OEBPS/Fonts/t.otf; a <style> in the page at
    # OEBPS/Text/p.xhtml naming ../Images/p.jpeg → OEBPS/Images/p.jpeg; a style="" attribute likewise.

def test_css_never_reaches_outside_the_book(tmp_path): ...
    # declarations with url(http://x/a.png), url(//x/a.png), u\\rl(http://x/a.png), url("javascript:alert(1)"),
    # @import url(https://x/s.css), @font-face src: url(https://x/f.woff), expression(alert(1)),
    # behavior: url(x.htc), -moz-binding: url(x.xml), and url(../Images/missing.png) (not in the book):
    # none of "http", "//x", "javascript", "expression", "behavior", "binding", "missing" in the document.
    # An @import of a sheet inside the book is inlined (its rule appears).

def test_nothing_that_runs_or_leaves_survives(tmp_path): ...
    # <script>, <img onerror=…>, <body onload=…>, <iframe>, <object>, <embed>, <form>, <input>,
    # <meta http-equiv="refresh">, <base href>, <link rel="stylesheet" href="https://x/s.css">,
    # <a href="javascript:…">, <svg><script>: none of "script", "onerror", "onload", "iframe", "object",
    # "embed", "<form", "<input", "refresh", "<base", "https://x", "javascript" in the document.

def test_svg_pictures_are_kept(tmp_path): ...
    # <svg viewBox="0 0 1299 1886"><image width="1299" height="1886" xlink:href="../Images/c.jpeg"/></svg>
    # → the document keeps <svg> with its viewBox and an <image> whose href is /api/files/1/res/OEBPS/Images/c.jpeg

def test_the_chapter_route_sends_fixed_pages_whole(client, tmp_path): ...
    # GET /api/files/{id}/chapters/0 of a fixed book → 200, text/html, header Content-Security-Policy == CSP,
    # body starts "<!doctype html>"; a flowing book's chapter is unchanged (no "<!doctype", same as before)
```

- [ ] **Step 2: Run them to verify they fail** — `bash test.sh -q tests/test_fixed_layout.py` → FAIL (no module `loft.fixedpage`).
- [ ] **Step 3: Implement `fixedpage.py`** — Collect the page's CSS in order (each `<link rel="stylesheet">` to a sheet in the book, then `<style>` blocks), parse each with `tinycss2.parse_stylesheet` and rebuild it keeping only rules whose `url` tokens and `url()` functions resolve (against that sheet's path via `FlowBook.resolve`) to a picture or font in the book; resolve `@import` inside the book (depth ≤ 3, no repeats), drop the rest; drop any declaration whose serialized value contains `expression`, `javascript:`, `behavior`, `-moz-binding`. Clean `style=""` attributes the same way (as declaration lists). Clean the body with `nh3`: the flowing `TAGS` plus `svg`, `g`, `image`, `rect`, `path`, `circle`, `ellipse`, `line`, `polygon`, `polyline`, `defs`, `use`, `text`, `tspan`; attributes `id`, `class`, `style` on all, `viewBox`, `preserveAspectRatio`, `width`, `height`, `x`, `y`, `transform`, `fill`, `d`, `points`, `href`, `xlink:href` on SVG; image `src`/`href`s rewritten first by Loft's rewriter approach (`FlowBook.resolve` + `book.images()`); links to other pages become plain text (`<span>`). Keep the body's `id` and `class`. Assemble `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="…"><meta charset="utf-8"><style>…</style></head><body …>…</body></html>`.
- [ ] **Step 4: Run them to verify they pass** — `bash test.sh -q` → all pass; `node --test tests/js/` → all pass.
- [ ] **Step 5: Commit** — `git commit -m "Fixed-layout pages are sent whole, cleaned, with only the book's own pictures and fonts"`

### Task 3: Fonts from the book

**Files:**
- Modify: `src/loft/app.py` (`flow_resource`), `src/loft/flow.py` (font media types)
- Test: `tests/test_fixed_layout.py`

**Interfaces:**
- Consumes: Task 2's `fonts(book)`.
- Produces: `/api/files/{id}/res/<font path>` → the font, its media type from Global Constraints, `nosniff`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_fonts_in_the_book_are_served(client, tmp_path): ...
    # fixed book with OEBPS/Fonts/t.otf (media-type application/vnd.ms-opentype) → GET …/res/OEBPS/Fonts/t.otf
    # 200, content-type font/otf, X-Content-Type-Options nosniff, the bytes; a .woff2 → font/woff2.

def test_other_files_still_are_not(client, tmp_path): ...
    # …/res/OEBPS/Text/p1.xhtml and …/res/OEBPS/Styles/a.css → 404
```

- [ ] **Step 2: Fail** — `bash test.sh -q tests/test_fixed_layout.py` → the font test FAILS (404).
- [ ] **Step 3: Implement** — serve `book.images()` or `fonts(book)`, the font's media type normalised by extension.
- [ ] **Step 4: Pass** — `bash test.sh -q` → all pass. Restart `loft-test` (`systemctl --user restart loft-test`) and check it answers `/api/ping`.
- [ ] **Step 5: Commit** — `git commit -m "Book fonts can be loaded by fixed-layout pages"`

### Task 4: The fixed-layout reader

**Files:**
- Create: `src/loft/web/js/fixed.js` — `class FixedReader extends Reader`; pure exports `startPage(progress, count) -> number` and `pageScale([w, h], [boxW, boxH]) -> number` (fit inside, never above what fills the box)
- Modify: `src/loft/web/js/reader.js` (`registerFixedReader(cls)`; in `renderReader`, a flowing file whose outline has `fixed` uses it; the comics `Reader` keeps its image path), `src/loft/web/js/zoom.js` (optional `frame: { size: (i) => [w, h], fill: (i, el) => Promise<void> }` used instead of an image), `src/loft/web/js/main.js` (`import "./fixed.js"`), `src/loft/web/sw.js` (cache `fixed.js`; `CACHE = "loft-shell-v6"`), `src/loft/web/style.css` (`.fixed-page`, `.fixed-page iframe`)
- Test: `tests/js/fixed.test.mjs` (node), then a browser run (below)

**Interfaces:**
- Consumes: outline `fixed` and `rtl` (Task 1); page documents from `/api/files/{id}/chapters/{n}?v=…` or `offline.chapterText(bookId, fileId, n)` (Task 2); fonts (Task 3).
- Produces: `FixedReader` with `count` = page count, `m.sizes` = `fixed.sizes`, `rtl` from the outline, progress `{file_id, page, pages: count, locator: {chapter: page}}`, bookmarks by page.

- [ ] **Step 1: Write the failing node tests** in `tests/js/fixed.test.mjs`:

```js
test("a place saved while read as flowing text finds its page", () => {
  assert.equal(startPage({ page: 12, pages: 139 }, 139), 12);                 // saved here
  assert.equal(startPage({ page: 500, pages: 1001, locator: { chapter: 40 } }, 139), 40);
  assert.equal(startPage({ page: 500, pages: 1001 }, 139), 69);                // half way
  assert.equal(startPage({ page: 900, pages: 139 }, 139), 138);                // never past the end
  assert.equal(startPage(null, 139), 0);
});
test("pages fit their space", () => {
  assert.equal(pageScale([706, 1024], [353, 512]), 0.5);
  assert.equal(pageScale([706, 1024], [706, 2000]), 1);
  assert.ok(Math.abs(pageScale([1000, 1500], [400, 900]) - 0.4) < 1e-9);
});
```

- [ ] **Step 2: Fail** — `node --test tests/js/` → FAIL (no module `fixed.js`).
- [ ] **Step 3: Implement** — `FixedReader`: leaves (and Scroll mode's pages) hold `<div class="fixed-page"><iframe sandbox="allow-same-origin" tabindex="-1" aria-label="Page N"></iframe></div>`, the iframe at its page's own size, `transform: scale(pageScale(...))` from the top left of its leaf; `loadNear` fetches page documents for pages within `NEAR` (`fetch` with credentials, or `offline.chapterText` for a downloaded book) and sets `srcdoc`; pages further than `3 * NEAR` are emptied (`srcdoc = ""`); a resize rescales. Zoom opens with `frame` so the current page shows alone, larger. `open(start, progress)` uses `startPage`. The rest (bookmarks, contents from the outline's `toc` with `chapter` as the page, discussion, settings) is the comics reader's.
- [ ] **Step 4: Pass** — `node --test tests/js/` and `bash test.sh -q` → all pass.
- [ ] **Step 5: Browser check** (Playwright + `/usr/bin/chromium-browser`, scratchpad `e2e/`, not committed) on a throwaway Loft whose books folder holds a copy of *Wedding Crashers* (`/var/mnt/smb-g/EBooks/Geronimo Stilton/Wedding Crashers/*.azw3`) and a flowing EPUB:
  - the book opens as pages: page 5's iframe shows "Dear mouse friends" and its picture (the iframe document has a loaded image of non-zero size), in the book's font (`document.fonts` in the frame has the book's family loaded);
  - two pages side by side on a wide window, one on a phone width; the cover alone;
  - next/previous by keys and taps; Scroll mode shows a column of pages; zoom opens and closes;
  - progress saved and restored on reopening; a bookmark lands on its page;
  - no request leaves the server's origin (Playwright `page.on("request")`); no script runs in a frame (a page with `<script>` in a test book changes nothing); no console errors;
  - the flowing EPUB reads as before;
  - screenshots at 1280 px and 412 px.
- [ ] **Step 6:** Restart `loft-test`; open *Wedding Crashers* there (port 4545) in the browser run too.
- [ ] **Step 7: Commit** — `git commit -m "Fixed-layout books read as pages, as their designers laid them out"`

### Task 5: Reading them offline

**Files:**
- Modify (only if the check fails): `src/loft/web/js/offline.js`
- Test: the browser run

**Interfaces:**
- Consumes: Task 4's reader with `this.stored`; `offline.download(book)` keeps chapters and every `/api/files/{id}/res/…` they name (fonts included, as they're named in the page's `<style>`).

- [ ] **Step 1: Browser check** — download *Wedding Crashers* from its page; go offline (`context.set_offline(True)`); reopen it: pages show their pictures and text from the device (no network requests), fonts load from `blob:` URLs.
- [ ] **Step 2:** If anything is missing, fix it in `offline.js` with the browser check as the failing test, then rerun.
- [ ] **Step 3: Commit** (if changed) — `git commit -m "Fixed-layout books read offline"`

### Task 6: Docs

**Files:** `README.md` (Reading: fixed-layout books), `CHANGELOG.md` ("Unreleased"). `whatsnew.json` gets its entry when the release is numbered.

- [ ] **Step 1:** Write them. **Step 2:** `bash test.sh -q` → all pass. **Step 3: Commit** — `git commit -m "Docs: fixed-layout books"`
