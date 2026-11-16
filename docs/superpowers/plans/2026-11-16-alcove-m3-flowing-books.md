# Alcove M3 — EPUB and the Other Formats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read EPUB, MOBI/AZW/AZW3, FB2 and TXT books with text laid out to fit the screen (font, size and margins adjustable), turning with the same paper curl; protected books are named as such. Also: wraparound comic covers show the front first.

**Architecture:** The server turns every "flowing" format into one shape — a *flow book*: an ordered list of chapters (sanitised XHTML body fragments), a table of contents, and its images. EPUB is read directly; MOBI/AZW/AZW3 are unpacked to EPUB once (cached); FB2 and TXT are converted by Alcove. The browser measures each chapter in hidden CSS columns to know how many pages it makes at the current page size and text settings, then gives StPageFlip one leaf per page, filling only nearby leaves. Positions are saved as a *locator* (chapter + fraction through it), so they survive changes in text size, font or screen.

**Tech Stack:** as M2, plus `nh3` (HTML sanitiser, MIT) and `mobi` (Kindle unpacker, GPL-3.0 — Alcove is licensed AGPL-3.0-or-later like Shelf, which is compatible).

**Spec:** `docs/superpowers/specs/2026-11-16-alcove-design.md` ("Rendering pages", "The reader", "Settings and customization")

## Global Constraints

- All M1/M2 constraints hold. PDFium rules don't apply here; every book file is still read-only.
- **Book HTML is untrusted.** Only what `nh3` allows reaches the browser: no scripts, event attributes, forms, iframes, objects, external URLs or `javascript:`; `style` attributes filtered to `text-align, font-style, font-weight, font-variant, text-indent, margin-left, text-decoration, vertical-align`. The book's own stylesheets are not used; Alcove's typography is.
- Resources are served only if listed in the book's manifest, images only (`image/jpeg|png|gif|webp|svg+xml` — SVG served as a download-safe `image/svg+xml` with `Content-Security-Policy: sandbox`).
- Readable formats become `READABLE_PAGES = {pdf, cbz, cbr, cb7}` (M2) and `READABLE_FLOW = {epub, mobi, azw, azw3, fb2, txt}`.
- Locator shape everywhere: `{"chapter": int, "progress": float 0–1}`.
- Existing databases must keep working: new columns are added by a small migration in `db.connect`.

## Review Focus

1. **Hostile EPUB content** (`<script>`, `onerror=`, `<a href="javascript:">`, `<img src="http://tracker">`, CSS `url()` in style attributes, SVG with script): none of it runs or loads. Tests in Task 3.
2. **Text settings or screen changes mid-book** (bigger font on the phone, then the laptop): you stay on the same passage, not the same page number. Test in Task 2 (locator round-trip) and checked in Task 7.
3. **EPUB paths with odd characters** (`OEBPS/Text/ch%201.xhtml`, `../Images/a b.jpg`, unicode names) and links between chapters with anchors: images load and links land on the right page. Tests in Task 3.
4. **Damaged or protected flowing books** (bad zip, missing OPF, Adobe/Kindle DRM): a clear "protected"/"damaged" message, never a blank reader. Tests in Tasks 3–5.
5. **Very long books** (1,000+ page novels, 100+ chapters): opening must not freeze the browser — measuring shows progress and is cached. Checked in Task 7.

---

### Task 0: Wraparound comic covers

**Files:** Modify `src/alcove/pages.py` (`split_plan`), `tests/test_pages.py`

- `split_plan`: when splitting and the **first** source page is a spread, it is a wraparound cover: plan starts with `(0, 1)` (right half, the front) and ends with `(0, 0)` (left half, the back). Everything else unchanged.
- [ ] **Step 1: Failing test** `test_wraparound_cover_front_first_back_last`: CBZ of `[spread(green|red), spread(red|blue), spread(red|blue)]` (front cover half = right) → count 6; page 0 is the right half of scan 0; last page is its left half; pages 1–4 are scans 1–2 in order.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `bash test.sh -q` → pass. **Step 5: Commit** `"Wraparound comic covers: front first, back last"`

### Task 1: Database migration and locators

**Files:** Modify `src/alcove/db.py` (columns + `migrate(con)`), `src/alcove/reading.py`, `tests/test_db.py`, `tests/test_reading.py`

- `progress.locator TEXT` and `bookmarks.locator TEXT` (JSON locator or NULL). `db.migrate(con)` adds any column in `MIGRATIONS = [("progress", "locator", "TEXT"), ("bookmarks", "locator", "TEXT")]` that `PRAGMA table_info` lacks; called from `connect`.
- `save_progress(..., locator: dict | None = None)` stores it; `get_progress` and `in_progress` return `"locator"` (dict or None). `add_bookmark(..., locator=None)`; bookmarks return `"locator"`. A locator is validated: dict with int `chapter ≥ 0` and finite `progress` clamped to 0–1, else `ValueError`.
- [ ] **Step 1: Failing tests:** an old-schema database (create `progress` without `locator`, insert a row) opens and gains the column with the row intact; locator round-trips through progress and bookmarks; bad locators (`{"chapter": -1}`, `{"chapter": 1, "progress": "x"}`) raise.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Locators for flowing books, and a small schema migration"`

### Task 2: The flow book model and EPUB

**Files:** Create `src/alcove/flow.py`, `src/alcove/epub.py`, `tests/test_epub.py`; extend `tests/conftest.py` `make_epub` with `chapters: list[str] | None`, `nav: list[tuple[str, str]] | None`, `images: dict[str, bytes] | None`, `encryption: bool = False`.

**Interfaces:**
- `flow.FlowBook` dataclass: `chapters: list[Chapter]`, `toc: list[TocEntry]`, `resources: dict[str, Resource]` where `Chapter(href: str, title: str)`, `TocEntry(title: str, chapter: int, anchor: str, level: int)`, `Resource(path: str, media_type: str)`; and a loader interface `read_chapter(n) -> str` (raw XHTML) / `read_resource(path) -> bytes`.
- `epub.open_epub(path) -> FlowBook` — container.xml → OPF; spine order (skip `linear="no"` only if it's not the first item); manifest paths resolved relative to the OPF and URL-unquoted; TOC from EPUB 3 `nav[epub:type=toc]` else NCX, nested levels kept, entries mapped to `(chapter, anchor)`; raises `flow.Unreadable("protected")` when `META-INF/encryption.xml` lists any algorithm other than the font-obfuscation ones (`http://www.idpf.org/2008/embedding`, `http://ns.adobe.com/pdf/enc#RC`), `Unreadable("damaged")` for a bad zip / missing OPF / empty spine.
- [ ] **Step 1: Failing tests:** 3-chapter EPUB (spine order differs from file order) → chapters in spine order, titles from nav; nested nav levels; NCX-only EPUB; `%20` and `../Images/` paths resolve; encryption.xml with Adobe DRM → protected; encryption.xml with only font obfuscation → readable; zip without OPF → damaged.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Flow books: EPUB structure, contents and protection"`

### Task 3: Safe chapter HTML

**Files:** Create `src/alcove/sanitize.py`, `tests/test_sanitize.py`; modify `pyproject.toml` (+ `nh3`)

**Interfaces:**
- `sanitize.chapter_html(raw: str, *, chapter_href: str, resolve: Callable[[str], tuple[str, str] | None], image_size: Callable[[str], tuple[int, int] | None], resource_url: Callable[[str], str]) -> str` — returns the `<body>` content only, sanitised (allowed tags: headings, p, div, span, br, hr, em, strong, i, b, u, s, sub, sup, small, blockquote, pre, code, ol, ul, li, dl, dt, dd, table parts, figure, figcaption, img, a, section, aside, header, footer, nav, abbr, cite, q, ruby, rt, rp, svg-free); `id` kept on every element (anchors); `<img src>` → `resource_url(resolved path)` with `width`/`height` from `image_size`, unknown/unlisted images dropped; `<a href="other.xhtml#n2">` → `href="#"` plus `data-chapter`/`data-anchor`; external `http(s)` links kept with `rel="noopener noreferrer" target="_blank"`; everything else per Global Constraints.
- [ ] **Step 1: Failing tests:** every item of Review Focus 1 is stripped (assert substrings absent: `<script`, `onerror`, `javascript:`, `tracker`, `url(`); allowed styles survive (`text-align:center`) and disallowed are dropped (`position:fixed`); an internal link becomes `data-chapter="2" data-anchor="n2"`; image `../Images/a b.jpg` becomes `/api/files/7/res/OEBPS/Images/a%20b.jpg` with `width="60" height="90"`; ids survive.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Safe chapter HTML"`

### Task 4: FB2, TXT and Kindle files

**Files:** Create `src/alcove/fb2.py`, `src/alcove/txt.py`, `src/alcove/kindle.py`, `tests/test_formats_flow.py`; modify `pyproject.toml` (+ `mobi`), `src/alcove/flow.py` (`open_flow(cfg, file_row) -> FlowBook` dispatching by format), `src/alcove/config.py` (`flow_dir = data_dir/"flow"`)

- `fb2.open_fb2(path)`: each top-level `<section>` of the main `<body>` → a chapter (XHTML built from `title`, `p`, `emphasis`, `strong`, `epigraph`, `poem/stanza/v`, `empty-line`, `image l:href="#id"`), TOC from section titles (nested), images from `<binary>` (base64). Also `.fb2.zip`-style? No — `.fb2` only.
- `txt.open_txt(path)`: decode UTF-8, else UTF-16 with BOM, else cp1252; chapters split at lines matching `^(chapter|part|book)\b.*$` (case-insensitive) or `^[IVXLC]+\.?$`; without such lines, chapters of ~40 paragraphs titled "Part 1…"; paragraphs at blank lines.
- `kindle.to_epub(cfg, file_id, path) -> Path`: if the MOBI header's encryption type (offset 12 of record 0's MOBI header → bytes 0x0C–0x0D of PalmDOC header) is non-zero → `Unreadable("protected")`; else unpack with `mobi.extract()` into `flow_dir/{file_id}-{version}/`, use the EPUB it produces (KF8/AZW3) or wrap the HTML it produces (old MOBI) as a one-chapter-per-`<mbp:pagebreak/>` flow book; cached by file version; failures → `Unreadable("damaged")`.
- [ ] **Step 1: Failing tests:** FB2 with 2 sections, a nested subsection, emphasis and an image → 2 chapters, TOC levels, image resource; TXT with "Chapter 1"/"Chapter 2" lines → 2 chapters; TXT without headings and 100 paragraphs → 3 parts; cp1252 TXT decodes "café"; a MOBI file with encryption type 2 (hand-made PalmDOC header) → protected; garbage `.azw3` → damaged. (Real KF8 unpacking is checked manually — no sample to ship.)
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"FB2, plain text and Kindle books"`

### Task 5: Flow API

**Files:** Modify `src/alcove/app.py`, `src/alcove/library.py` (`readable` flag per file in `get_book`), `src/alcove/web/js/home.js` (`canRead` uses it), `tests/test_api.py`

**Routes:**
- `GET /api/files/{id}/flow` → `{"file_id", "format", "version", "chapters": [{"title"}], "toc": [{"title","chapter","anchor","level"}]}`; 415 with reasons as M2.
- `GET /api/files/{id}/chapters/{n}` → `text/html; charset=utf-8` fragment from `sanitize.chapter_html`, `Cache-Control: private, max-age=604800`, header `Content-Security-Policy: default-src 'none'; img-src 'self'` (fragment is inserted by the app, but the header protects direct opens).
- `GET /api/files/{id}/res/{path:path}` → the image with its media type; 404 unless the path is a listed image resource.
- `PUT /api/books/{id}/progress` and bookmarks accept optional `locator`.
- `GET /api/books/{id}` files gain `"readable": "pages" | "flow" | null`.
- [ ] **Step 1: Failing tests:** flow outline of a 3-chapter EPUB; chapter 1 HTML has no `<script>` and image URLs under `/api/files/{id}/res/`; resource route serves an image and 404s for `../../etc/passwd` and for an XHTML path; protected EPUB → 415 `"protected"`; progress PUT with locator round-trips; `readable` values for pdf/epub/docx-free files.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Flow book API"`

### Task 6: The flowing reader

Load `frontend-design:frontend-design` first.

**Files:** Create `src/alcove/web/js/flow.js` (layout engine), modify `src/alcove/web/js/reader.js` (choose pages vs flow by `readable`; shared controls), `style.css`

Decisions:
- **Page box:** wide screens: two pages, each `min((W − 48)/2, H × 0.7)` wide and `H − 40` tall; phones: the full stage. Text area = page box minus margins (narrow 6% / normal 9% / wide 13% each side; top/bottom 7%).
- **Typography:** Literata (`literata`), Georgia stack (`serif`), Instrument Sans (`sans`); size = 18 px × `epub_size`/100 on desktop, 17 px on phones; line-height 1.55; paragraphs indented 1.2em except first after a heading; images `max-width:100%; max-height:` text-area height; headings never split from the next line (`break-after: avoid`).
- **Page colours** follow the reading theme: dark page `#1d1916` / ink `#e3d9cc`; sepia `#f6ecd6` / `#3b2f22`; white `#ffffff` / `#1f1f1f`; black `#000` / `#cfcfcf`.
- **Measuring:** a hidden container sized to the text area with `column-width` = text width, `column-gap` = 2 × side margin, `column-fill: auto`; for each chapter insert its HTML, pages = `ceil(scrollWidth / (textWidth + gap))`, record `id → page` for anchors, remove. Show "Laying out the book… 34%" while measuring; cache `{chapter counts, anchors}` in `sessionStorage` keyed by file version + page box + font + size + margins.
- **Leaves:** one per page; a leaf holds a clipped column container showing chapter *c*, column *k* (`transform: translateX(-k × (textWidth + gap))`). Only leaves within ±3 of the current spread get content; chapter HTML fetched once and cached in memory (LRU of 12 chapters).
- **Locators:** current locator = `{chapter: c, progress: k / pages_in_c}`; opening goes to the saved locator (else page 0); after re-layout (settings change, resize across the two-page threshold) go back to the same locator. Progress PUT sends `page`/`pages` of the global layout plus the locator; `finished` as M2 (last visible page).
- **Links:** `data-chapter`/`data-anchor` clicks go to that chapter's anchor page; external links open in a new tab.
- **Controls:** the M2 controls; Contents uses the flow TOC (chapter + anchor); the reading panel gains Font (Literata / Serif / Sans), Text size (− / + in steps of 10, 80–160) and Margins (narrow / normal / wide), all saved with `PATCH /api/settings` and re-laid out.
- **Scroll mode:** chapters stacked as plain flowing text at the text width (max 38em), locator from the chapter in the middle of the screen.
- **Images:** tapping an image in a flow book opens the M2 zoom view on that image.
- [ ] **Step 1: Build.**
- [ ] **Step 2: Verify in Chromium** against a test books folder (scratch) holding: Calibre's Quick Start Guide EPUB (copied), a public-domain novel EPUB from Project Gutenberg (Alice's Adventures in Wonderland), an FB2 and a TXT made in tests: open each at 1440×900 and 390×844; turn pages; change text size to 140 → same passage still in view; Contents jump; internal link jump; progress saved with locator; reopen lands on the passage; no console errors, no overflow.
- [ ] **Step 3: Run** `bash test.sh -q` → pass. **Step 4: Commit** `"Flowing books in the reader: EPUB, Kindle, FB2 and text"`
