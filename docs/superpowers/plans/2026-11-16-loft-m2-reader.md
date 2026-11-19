# Loft M2 — Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read PDFs and comics in the browser with paper-curl page turning, zoom, chapters, bookmarks and progress that follows you between devices; "Continue reading" on the home screen; and each person's settings (account, reading, look).

**Architecture:** The server turns pages into JPEGs on demand (PDF via pypdfium2 behind one process-wide lock; comics straight from the archive) and caches them in the data dir. A per-file "manifest" (page count, page sizes, chapters) is computed once and stored. Progress, bookmarks and settings are per user in SQLite. The web reader uses StPageFlip (vendored, MIT) in HTML mode with only nearby pages' images loaded; zoom happens in a separate pan-and-zoom view so it never fights the page flipping.

**Tech Stack:** as M1, plus `py7zr` (CB7) and `rarfile` (CBR; uses `unrar`, `unar`, `7z` or `bsdtar` on the server), and StPageFlip 2.0.7 (`page-flip`, MIT) vendored to `src/loft/web/vendor/`.

**Spec:** `docs/superpowers/specs/2026-11-16-loft-design.md` (sections "The reader", "Settings and customization", "The library (screens)")

## Global Constraints

- Everything in M1's Global Constraints still holds (read-only books folders, no runtime internet, palette, auth on every route, `bash test.sh`).
- PDFium is not thread-safe: **every** pypdfium2 call (filemeta, covers, pages) runs under `loft.pdfium.LOCK`.
- Page image widths are snapped to `PAGE_WIDTHS = (600, 900, 1200, 1800, 2400)`; no rendered page exceeds 16 million pixels.
- Comic archives are recognised by their first bytes, not their extension (`PK\x03\x04` zip, `Rar!\x1a\x07` rar, `7z\xbc\xaf\x27\x1c` 7z) — mislabelled CBZ/CBR files are common.
- Settings are validated against fixed choices; an unknown key or value is a 400 with a message naming it.
- Reader copy: sentence case, plain verbs, no all-caps labels.

## Review Focus

1. **Mixed page sizes in one PDF** (a cover at a different size, landscape spreads in a comic): pages must not be stretched — each page keeps its aspect ratio, letterboxed in the book's page box. Test in Task 2 (sizes per page) and checked by screenshot in Task 6.
2. **A file changed or replaced while someone is reading it** (rescan bumps its mtime): the manifest and cached pages must refresh, not serve the old book's pages. Test in Task 2.
3. **Progress from two devices**: the newer save wins; an older save arriving late (phone back online) must not move you backwards. Test in Task 4.
4. **Out-of-range and hostile page requests** (`/pages/-1`, `/pages/99999`, `w=99999`, a file id of a non-readable format): 404/415, never a crash or a giant render. Test in Task 5.
5. **Encrypted or damaged PDFs opened in the reader**: a clear message ("This book is protected and can't be opened here" / "This file is damaged"), not a blank reader. Test in Task 5; message checked in Task 6.

---

## File Structure

```
src/loft/pdfium.py       LOCK, open_pdf() context manager
src/loft/comics.py       open_archive(), page_names(), read_member()
src/loft/pages.py        manifest(), render_page(), prune_page_cache(), PAGE_WIDTHS
src/loft/settings.py     DEFAULTS, CHOICES, get_settings(), update_settings()
src/loft/reading.py      save_progress(), get_progress(), in_progress(), bookmarks CRUD
src/loft/library.py      (modify) home() uses progress + settings; get_book() adds progress
src/loft/auth.py         (modify) change_password(), sign_out_everywhere()
src/loft/app.py          (modify) new routes
src/loft/web/vendor/page-flip.browser.js + LICENSE-page-flip.txt
src/loft/web/js/reader.js   the reader screen
src/loft/web/js/zoom.js     pan-and-zoom view
src/loft/web/js/settings.js your settings screen
src/loft/web/js/prefs.js    load settings, apply look (accent, cover size, titles)
```

---

### Task 1: Comic archives and the PDFium lock

**Files:**
- Create: `src/loft/pdfium.py`, `src/loft/comics.py`, `tests/test_comics.py`
- Modify: `pyproject.toml` (+ `py7zr`, `rarfile`), `src/loft/filemeta.py`, `src/loft/covers.py` (use `open_pdf` and `comics`), `tests/conftest.py` (fixture `make_cb7(path)`; `make_cbz(path, name_order=..., colours=...)` reused)

**Interfaces:**
- Produces `pdfium.LOCK: threading.RLock`; `pdfium.open_pdf(path) -> ContextManager[PdfDocument]` (acquires LOCK for the whole block, closes the doc).
- Produces `comics.archive_kind(path) -> "zip" | "rar" | "7z" | None` (by magic bytes); `comics.page_names(path) -> list[str]` (image members, natural order, skipping `__MACOSX/` and dotfiles); `comics.read_member(path, name) -> bytes`. Raise `comics.ComicError` for unreadable archives (including "no RAR tool installed").
- `covers.extract_cover` handles `cbz`, `cbr`, `cb7` through `comics` (first page).

- [ ] **Step 1: Failing tests:** `archive_kind` returns `"zip"` for a CBZ, `"7z"` for a CB7, and `"zip"` for a zip saved as `x.cbr` (mislabelled); `page_names` of a CBZ with `page10.png, page2.png, page1.png, __MACOSX/._page1.png, .DS_Store` → `["page1.png", "page2.png", "page10.png"]`; same for a CB7; `read_member` returns the PNG bytes; garbage file → `ComicError`; `extract_cover` on the mislabelled `.cbr` returns page 1. CBR made by a real RAR tool is not available in tests — a test using `rarfile` against a RAR archive is skipped unless `tests/data/sample.cbr` exists.
- [ ] **Step 2: Run** `bash test.sh tests/test_comics.py -q` → FAIL.
- [ ] **Step 3: Implement** `pdfium.py`, `comics.py`; switch `filemeta._pdf` and `covers._pdf_cover` to `open_pdf`; covers use `comics`.
- [ ] **Step 4: Run** `bash test.sh -q` → all pass.
- [ ] **Step 5: Commit** `"Comic archives by content, and one lock around PDFium"`

### Task 2: Pages — manifest and rendering

**Files:**
- Create: `src/loft/pages.py`, `tests/test_pages.py`
- Modify: `src/loft/db.py` (table `page_info(file_id INTEGER PRIMARY KEY REFERENCES book_files(id) ON DELETE CASCADE, mtime REAL, count INTEGER, sizes TEXT, toc TEXT)`), `src/loft/config.py` (`page_cache_mb: int = 2048`, property `page_dir = data_dir/"pages"`), `src/loft/scanner.py` (call `prune_page_cache(cfg)` after each scan in `Scanner._loop`)

**Interfaces:**
- Produces `READABLE = {"pdf", "cbz", "cbr", "cb7"}` (M2).
- Produces `manifest(cfg, file_id) -> dict`: `{"file_id", "format", "count", "sizes": [[w, h], ...] /* points or pixels, per page */, "toc": [{"title", "page", "level"}], "version": int(mtime)}`. Stored in `page_info`; recomputed when `book_files.mtime` differs from the stored one. Raises `pages.Unreadable(kind)` with `kind` in `"format" | "protected" | "damaged"`; `LookupError` for an unknown file id.
  - PDF: count, every page's size via `get_page_size`, TOC from `get_toc()` (`page` from `get_dest().get_index()`, skip entries without a destination).
  - Comics: count = `len(page_names)`, sizes from `PIL.Image.open(BytesIO(...)).size` (reads headers), `toc = []`.
- Produces `render_page(cfg, file_id, index, width) -> Path` — snaps `width` to the nearest of `PAGE_WIDTHS` (ties go up), caps at 16 MP, writes `page_dir/{file_id}-{version}/{index}-{w}.jpg` (JPEG q88, RGB) if missing, deletes `page_dir/{file_id}-*` folders of older versions, returns the path. `IndexError` when `index` is out of range. Comics are never upscaled (an image narrower than `w` is stored at its own width).
- Produces `prune_page_cache(cfg)` — if the page cache is over `page_cache_mb`, delete least-recently-modified files until it's at 80%.

- [ ] **Step 1: Failing tests:** a 3-page PDF with pages 300×450, 600×450, 300×450 and a two-level outline → `count == 3`, `sizes == [[300, 450], [600, 450], [300, 450]]`, toc titles/pages/levels; a CBZ manifest has its pages' pixel sizes; `render_page(..., 1, 1000)` → a JPEG 1200 wide (snap) with height 900 (aspect kept); a second call doesn't re-render (mtime of the JPEG unchanged); `render_page(..., 5, 900)` → `IndexError`; a CBZ page 60 px wide rendered at 600 → 60 wide; **file replaced** (rewrite the PDF with 2 pages, bump mtime, update `book_files.mtime`) → manifest `count == 2` and the old cache folder is gone after the next render; encrypted PDF → `Unreadable("protected")`; zero-byte PDF → `Unreadable("damaged")`; EPUB file id → `Unreadable("format")`; `prune_page_cache` with `page_cache_mb=0` empties the cache.
- [ ] **Step 2: Run** `bash test.sh tests/test_pages.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `bash test.sh -q` → pass.
- [ ] **Step 5: Commit** `"Pages: book manifests and page images on demand"`

### Task 3: Your settings and your account

**Files:**
- Create: `src/loft/settings.py`, `tests/test_settings.py`
- Modify: `src/loft/db.py` (table `user_settings(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, data TEXT NOT NULL)`), `src/loft/auth.py`, `tests/test_auth.py`

**Interfaces:**
- Produces `settings.DEFAULTS`:
  ```python
  {"reading": {"mode": "pages", "theme": "dark", "turn_speed": "normal", "spread": True, "left_handed": False,
               "epub_font": "literata", "epub_size": 100, "epub_margins": "normal"},
   "look": {"accent": "brass", "cover_size": "medium", "cover_titles": True,
            "home_rows": [{"kind": "continue", "visible": True}, {"kind": "recent", "visible": True},
                          {"kind": "series", "visible": True}, {"kind": "genres", "visible": True}]}}
  ```
  and `settings.CHOICES`: `mode ∈ {pages, scroll}`, `theme ∈ {dark, sepia, white, black}`, `turn_speed ∈ {gentle, normal, quick, off}`, `spread`/`left_handed`/`cover_titles` bool, `epub_font ∈ {literata, serif, sans}`, `epub_size` int 80–160, `epub_margins ∈ {narrow, normal, wide}`, `accent ∈ {brass, sage, dusk, rose, lilac}`, `cover_size ∈ {small, medium, large}`, `home_rows` = the four kinds, each exactly once, any order, `visible` bool.
- Produces `get_settings(cfg, user_id) -> dict` (stored values over defaults; unknown stored keys dropped) and `update_settings(cfg, user_id, patch: dict) -> dict` (deep-merge one level: `{"reading": {"theme": "sepia"}}`; raises `ValueError("Unknown setting reading.colour")` / `ValueError("reading.theme can't be 'pink'")`).
- Produces `auth.change_password(cfg, user_id, current, new) -> User` (raises `ValueError("Your current password isn't right")`; bumps version → other devices signed out; returns the user with the new version so the caller can re-issue this device's cookie) and `auth.sign_out_everywhere(cfg, user_id) -> User` (bumps version).

- [ ] **Step 1: Failing tests:** defaults for a new user; patch one key keeps the rest; bad key / bad value / `epub_size` 300 / `home_rows` with a duplicate kind → `ValueError` with the key in the message; settings removed when the user is deleted; `change_password` with the wrong current password raises and leaves the old one working; with the right one the old token stops working and a token for the returned user works; `sign_out_everywhere` invalidates existing tokens.
- [ ] **Step 2: Run** `bash test.sh tests/test_settings.py tests/test_auth.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `bash test.sh -q` → pass.
- [ ] **Step 5: Commit** `"Your settings, password change and signing out everywhere"`

### Task 4: Progress, bookmarks and "Continue reading"

**Files:**
- Create: `src/loft/reading.py`, `tests/test_reading.py`
- Modify: `src/loft/db.py` (tables below), `src/loft/library.py` (`home(cfg, user)` and `get_book(cfg, book_id, user=None)`), `tests/test_library.py`

Tables:
- `progress(user_id REFERENCES users ON DELETE CASCADE, book_id REFERENCES books ON DELETE CASCADE, file_id INTEGER, page INTEGER, pages INTEGER, position REAL, finished INTEGER, updated_at REAL, PRIMARY KEY(user_id, book_id))`
- `bookmarks(id INTEGER PRIMARY KEY, user_id REFERENCES users ON DELETE CASCADE, book_id REFERENCES books ON DELETE CASCADE, file_id INTEGER, page INTEGER, note TEXT NOT NULL DEFAULT '', created_at REAL)`

**Interfaces:**
- Produces `save_progress(cfg, user_id, book_id, *, file_id, page, pages, at: float | None = None) -> dict` — `position = page / max(1, pages - 1)` clamped 0–1, `finished = page >= pages - 1`; `at` is when the reader was on that page (client clock, defaults to now); **a save with `at` older than the stored `updated_at` is ignored** and the stored row is returned.
- Produces `get_progress(cfg, user_id, book_id) -> dict | None` (`{"file_id","page","pages","position","finished","updated_at"}`) and `in_progress(cfg, user_id, limit=20) -> list[(card, progress)]` (unfinished, most recent first).
- Produces `list_bookmarks(cfg, user_id, book_id) -> list[dict]` (`{"id","file_id","page","note","created_at"}`, by page), `add_bookmark(cfg, user_id, book_id, *, file_id, page, note="") -> dict`, `delete_bookmark(cfg, user_id, bookmark_id) -> bool` (only your own).
- `library.home(cfg, user)` now returns `{"hero": card | None, "hero_kind": "continue" | "new", "hero_progress": progress | None, "rows": [...]}`: hero = most recent unfinished book if any (`"continue"`), else newest (`"new"`). A row `{"title": "Continue reading", "kind": "continue", "value": None, "books": [card + "progress"]}` appears when there are ≥ 2 unfinished books. Rows follow the user's `look.home_rows` order; hidden kinds are left out (`genres` = the tag rows; hiding `continue` hides the row but the hero still continues).
- `library.get_book(cfg, id, user)` adds `"progress": get_progress(...)` (None without a user).

- [ ] **Step 1: Failing tests:** save then get; page 587 of 588 → `finished`; late older save ignored (`at` earlier) and newer one applied; `in_progress` excludes finished and orders by recency; bookmarks add/list/delete and another user can't delete yours; home hero becomes the in-progress book with `hero_kind == "continue"`; "Continue reading" row only with ≥ 2; `home_rows` order `[genres, recent, series, continue]` reorders rows; hiding `recent` removes it; deleting a book removes its progress.
- [ ] **Step 2: Run** `bash test.sh tests/test_reading.py tests/test_library.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `bash test.sh -q` → pass.
- [ ] **Step 5: Commit** `"Reading progress, bookmarks and Continue reading"`

### Task 5: Reader and settings API

**Files:**
- Modify: `src/loft/app.py`, `tests/conftest.py` (the `app_lib` library gains a 3-page PDF with an outline and an encrypted PDF), `tests/test_api.py`

**Interfaces (routes):**
- `GET /api/files/{file_id}/manifest` → manifest; 404 unknown; 415 `{"detail": ..., "reason": "format"|"protected"|"damaged"}` for unreadable (detail copy: format → "This kind of book can't be read here yet; download it instead.", protected → "This book is protected and can't be opened here.", damaged → "This file is damaged and can't be opened.").
- `GET /api/files/{file_id}/pages/{index}?w=1200` → JPEG, `Cache-Control: private, max-age=604800`; 404 for a bad index (negative included); `w` clamped to 600–2400 before snapping.
- `GET /api/books/{id}` now includes `progress` for the signed-in user.
- `PUT /api/books/{id}/progress {file_id, page, pages, at?}` → progress. `file_id` must belong to the book (400 otherwise).
- `GET/POST /api/books/{id}/bookmarks`, `DELETE /api/bookmarks/{id}` (404 if not yours).
- `GET /api/settings`, `PATCH /api/settings` (400 with the `ValueError` message).
- `POST /api/me/password {current, new}` → re-issues this device's cookie; `POST /api/me/signout-everywhere` → re-issues this device's cookie too (you stay signed in here).

- [ ] **Step 1: Failing tests:** manifest of the outline PDF; page 0 at `w=99999` is 2400 wide; `/pages/-1` and `/pages/3` → 404; EPUB file → 415 `reason == "format"`; encrypted → 415 `"protected"`; progress PUT then `GET /api/books/{id}` shows it; progress with another book's `file_id` → 400; bookmarks round trip and a member can't delete the admin's; `PATCH /api/settings {"reading": {"theme": "pink"}}` → 400 mentioning `reading.theme`; password change keeps this client signed in but an old bearer token fails; signout-everywhere likewise.
- [ ] **Step 2: Run** `bash test.sh tests/test_api.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `bash test.sh -q` → pass.
- [ ] **Step 5: Commit** `"Reader, progress, bookmark and settings API"`

### Task 6: The reader

Load `frontend-design:frontend-design` first. The look: the open book sits on the dark room background, lit like the hero; controls are quiet until called.

**Files:**
- Create: `src/loft/web/vendor/page-flip.browser.js` (from `https://cdn.jsdelivr.net/npm/page-flip@2.0.7/dist/js/page-flip.browser.js`), `src/loft/web/vendor/LICENSE-page-flip.txt`, `src/loft/web/js/reader.js`, `src/loft/web/js/zoom.js`
- Modify: `src/loft/web/index.html` (vendor script before `main.js`), `js/main.js` (route `#/read/:bookId?file=&page=` renders full screen without the top bar), `style.css`

Behaviour (decisions the implementer can't infer):
- **Layout:** page box aspect = the most common page aspect in the manifest; each page is a `<div class="page">` with an `<img>` that uses `object-fit: contain` (mixed sizes letterboxed). StPageFlip options: `size: "stretch"`, `showCover: true`, `usePortrait: true`, `drawShadow: true`, `maxShadowOpacity: 0.5`, `mobileScrollSupport: false`, `disableFlipByClick: true`, `flippingTime` gentle 1000 / normal 700 / quick 420 / off 1 ms. When `spread` is off, the container is limited to one page's width (forces single pages).
- **Only nearby images load:** `src` set for pages within ±4 of the current spread (`w` = device-pixel width of one page, rounded up to a `PAGE_WIDTHS` step); others keep an empty `src` and the generated-cover-style placeholder colour.
- **Turning pages:** drag/swipe (StPageFlip); taps: outer 30% of the width on the right goes forward, left goes back (swapped when `left_handed`), middle 40% toggles the controls; arrow keys, PageUp/PageDown, Space; `Esc` closes panels then the reader.
- **Controls (middle tap):** top: back (to the book page), title, Contents, Bookmark this page (filled when bookmarked), reading settings (theme, turn speed, two pages, left-handed — saved with `PATCH /api/settings`). Bottom: a scrubber (`<input type=range>`) showing "Page 212 of 588" while dragging, jumping on release via `turnToPage`. Panels slide over the page from the side.
- **Contents panel:** the PDF outline (indent by level) or, without one, a page list every 10 pages; the bookmarks list under it.
- **Zoom:** double-tap/double-click a page, pinch on a touchscreen, or ctrl+wheel opens `zoom.js` over the reader: the current page at 2400 w, pan with drag, pinch/wheel zoom 1×–5×, buttons Back to book, previous/next page (keeping the zoom and jumping to the page's top-left). Pinching back below 1× closes it.
- **Scroll mode** (`mode == "scroll"`): no StPageFlip; a vertical column of pages at the page box width, images lazy via IntersectionObserver; current page = the one crossing the middle of the screen.
- **Progress:** on every page change, debounce 1.5 s then `PUT /progress` with `at = Date.now()/1000`; on `pagehide`/`visibilitychange→hidden` send immediately with `fetch(..., {keepalive: true})`. Opens at `?page=` if given, else the saved page.
- **Themes:** the room around the book: dark `#14110f`, sepia `#efe4cf` (ink `#3b2f22`), white `#fafafa`, black `#000`. Page images are never recoloured.
- **Unreadable books:** the 415 `detail` shown on a centred card with "Back to the book" and "Download".

- [ ] **Step 1: Vendor** StPageFlip and its MIT licence text.
- [ ] **Step 2: Build** `reader.js`, `zoom.js`, styles.
- [ ] **Step 3: Verify in Chromium** (CDP script, signed-in cookie) against the real library: open "It" at 1440×900 → two pages side by side; press ArrowRight 3× → progress saved (`GET /api/books/{id}` shows page 6 or 7); 390×844 → one page; open "Assassin's Creed: Uprising #1" (comic) → pages render; middle tap shows controls; screenshot each; no console errors.
- [ ] **Step 4: Run** `bash test.sh -q` → pass.
- [ ] **Step 5: Commit** `"The paper-curl reader"`

### Task 7: Read buttons, Continue reading, your settings screen, the look

**Files:**
- Create: `src/loft/web/js/settings.js`, `src/loft/web/js/prefs.js`
- Modify: `js/main.js` (route `#/settings`; top bar gets a person button → settings), `js/home.js`, `js/book.js`, `style.css`

Behaviour:
- **Book page:** primary button "Read" (or "Continue from page 212" when there's progress, or "Read again" when finished) → `#/read/{id}`; Download buttons stay, secondary. Books whose format isn't readable yet show only Download.
- **Home hero:** when `hero_kind == "continue"`: label "Continue reading" (serif italic, accent), a progress line (thin bar + "Page 212 of 588"), button "Continue". The "Continue reading" row shows a thin progress bar under each cover.
- **Your settings screen (`#/settings`):** sections Account (change password: current + new + "Change password"; "Sign out on other devices"), Reading (the reading settings above as segmented controls/switches), Look (accent swatches; cover size; titles under covers; home rows list with show/hide switches and up/down buttons). Every change saves on its own (`PATCH`) with a quiet "Saved" note; no Save button.
- **Look applied everywhere** (`prefs.js`, run at start and after changes): `--brass` from accent (brass `#c9a27a`, sage `#a3b78f`, dusk `#97a9cc`, rose `#d39b9e`, lilac `#b8a0d0`); `--cover-w` small 108 / medium 132 / large 160 (phones: 88 / 104 / 124); `body.no-cover-titles` hides titles under covers.
- [ ] **Step 1: Build** the above.
- [ ] **Step 2: Verify in Chromium:** book page shows "Read"; after Task 6's reading, home hero says "Continue reading"; settings screen at 1440 and 390 wide; switching accent to sage recolours the buttons; hiding "Recently added" removes the row; no horizontal overflow.
- [ ] **Step 3: Run** `bash test.sh -q` → pass.
- [ ] **Step 4: Commit** `"Continue reading, Read buttons and your settings"`
