# Alcove M4 — Managing the Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The admin runs the library from Alcove instead of Calibre: edit any book on its page, add books by dropping files, fill details and covers from Open Library, manage people and folders, and see a library check of what needs attention. Everyone gets shelves.

**Architecture:** Admin edits are stored in Alcove's database and the fields they touch are *locked*, so later scans (file changes, Calibre changes) never overwrite them; book files are never rewritten. Uploads land in a draft folder in the data dir, are read for details, reviewed, then moved into a books folder as `Author/Title/file` and recorded at once (the scanner later sees an unchanged file). Library settings live in the database (`meta` key `library`) and override `config.toml` once saved. The library check is computed on request from the books table, a `file_checks` table filled after each scan, and the last scan's report.

**Tech Stack:** as M3. No new dependencies: uploads are streamed as the raw request body (no multipart), Open Library is called with `urllib`.

**Spec:** `docs/superpowers/specs/2026-11-16-alcove-design.md` ("Books in and out", "Settings and customization", "Getting book details without Calibre", "People")

## Global Constraints

- Existing book files are never changed, renamed or deleted. The only write into a books folder is saving an upload, as a new file.
- Every M4 route that changes the library is admin-only (`admin_user`); shelves are per person (`current_user`) and never see another person's shelves.
- Existing databases keep working: new columns via `db.MIGRATIONS`, new tables via `CREATE TABLE IF NOT EXISTS`.
- Online lookups send only title, author and ISBN to `openlibrary.org`, never while `online_lookups` is off; the server only downloads covers from `https://covers.openlibrary.org/`.
- `.txt` files stay hidden unless the admin turns on plain-text files.
- There is always at least one admin.
- Copy: plain sentence-case words, no apologies; errors say what happened and what to do.

## Review Focus

1. **A rescan after an edit** (the file is touched, or Calibre's `metadata.db` changes): the admin's details and chosen cover stay. Test in Task 3.
2. **Upload names that try to escape or collide** (`../../x.epub`, `CON.pdf`, `a:b?.epub`, 300-character names, an existing `Author/Title/file`): the file stays inside the chosen books folder and never overwrites anything. Test in Task 6.
3. **A books folder Alcove can't write to** (the SMB share is read-only): saving says so and names the folder, and the draft stays so it can be retried. Test in Task 6.
4. **Taking away the last admin** (unmaking or removing them, including yourself): refused; a removed or demoted person's sessions stop working. Test in Task 2.
5. **Open Library down, slow or odd** (timeout, HTML error page, missing fields, description as `{"value": …}`), and lookups turned off: a clear message, the form still works by hand, nothing is sent. Test in Task 5.

---

### Task 1: Schema, library settings and the scanner's report

**Files:** Modify `src/alcove/db.py`, `src/alcove/scanner.py`, `src/alcove/app.py`; create `src/alcove/libsettings.py`, `tests/test_libsettings.py`; extend `tests/test_db.py`, `tests/test_scanner.py`

**Interfaces:**
- Produces: columns `books.locked TEXT NOT NULL DEFAULT '[]'` (JSON list of field names the admin set), `book_files.layout TEXT` (JSON `{"split": bool|null, "wraparound": bool|null}`), `book_files.layout_rev INTEGER NOT NULL DEFAULT 0`; tables `shelves(id, user_id, name, kind 'want'|'own', created_at, UNIQUE(user_id, name COLLATE NOCASE))`, `shelf_books(shelf_id, book_id, added_at, PRIMARY KEY(shelf_id, book_id))` (both cascade), `check_ignored(kind, key, PRIMARY KEY(kind, key))`, `file_checks(file_id PRIMARY KEY → book_files ON DELETE CASCADE, mtime REAL, status TEXT 'ok'|'damaged'|'protected')`.
- `libsettings.get_library(cfg) -> dict` → `{"name": str, "books_dirs": [str], "upload_dir": str, "scan_interval_minutes": int, "allow_txt": bool, "online_lookups": bool}`; defaults: `""`, `cfg.books_dirs`, first books dir, `cfg.scan_interval_minutes`, `False`, `True`. Stored (only changed keys) as JSON in `meta` key `library`.
- `libsettings.update_library(cfg, patch: dict) -> dict` — ValueError naming the field for: unknown key; name over 40 characters (stripped); `books_dirs` not a list of 1–10 absolute paths to existing readable folders (duplicates dropped); `upload_dir` not one of `books_dirs`; interval outside 5–1440; non-bool switches. Removing a folder from `books_dirs` deletes its `book_files` and any book left without files, at once (the scanner itself never removes a folder's books just because the folder isn't listed — a config typo must not wipe progress). If `upload_dir` is no longer listed it falls back to the first.
- `libsettings.books_dirs(cfg) -> list[Path]`, `libsettings.allow_txt(cfg) -> bool`.
- Scanner: `scan()` walks `libsettings.books_dirs(cfg)` with `format_of(..., allow_txt=libsettings.allow_txt(cfg))`; `Scanner` waits `get_library(cfg)["scan_interval_minutes"]`; `_write_book` and `_set_cover` skip locked fields (`title` also covers `sort_title`, `authors` covers `author_sort`, `cover` covers the cover image) when updating an existing book; `scan()` stores a report in `meta` key `last_scan`: `{"at": float, "added", "updated", "removed", "unreachable": [root], "unreadable": [path], "calibre_missing": [path]}` (`calibre_missing` = files Calibre lists under the root that aren't on disk, outside unreadable folders). `scanner.last_report(cfg) -> dict | None`.
- `GET /api/status` gains `"name"`; `GET/PATCH /api/library` (admin) wrap the two functions (400 on ValueError); `GET /api/scan` gains `"report"`.
- [ ] **Step 1: Failing tests:** an old database (books table without `locked`) opens with the column added; defaults reflect config; saving `name` round-trips and `/api/status` shows it unauthenticated; each invalid value above is refused with its field named; turning `allow_txt` on makes a `.txt` file appear on the next scan and off makes it go; removing a folder removes its books immediately while a books dir missing from `config.toml` alone removes nothing; the scan report lists an unreadable subfolder and a Calibre file that isn't on disk.
- [ ] **Steps 2–5:** run → FAIL, implement, run `bash test.sh -q` → pass, commit `"Library settings: name, folders, plain text, lookups; the scan reports what it couldn't read"`

### Task 2: People

**Files:** Modify `src/alcove/auth.py`, `src/alcove/app.py`, `tests/test_auth.py`, `tests/test_api.py`

**Interfaces:**
- `auth.set_admin(cfg, user_id, admin: bool) -> User` — bumps `version` (signs them out, so a demoted admin's open session can't keep admin rights); ValueError `"There has to be at least one admin"` when it would leave none. `auth.delete_user` raises the same when removing the last admin.
- Routes (admin): `PATCH /api/users/{id}` `{"admin": bool}`; `POST /api/users/{id}/password` `{"password"}` (uses `set_password`, signs them out); `DELETE /api/users/{id}` (still refuses yourself). If you change your own admin flag the response re-signs you in like `/api/me/password`.
- [ ] **Step 1: Failing tests:** make `sam` admin then unmake; unmaking the only admin → 400 with the message; removing the last admin → refused; a member can't call any of these (403); reset password → sam's old token gets 401 and the new password works; after demotion sam's old token gets 401.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"People: make or unmake admin, reset passwords, never no admin"`

### Task 3: Editing a book's details and cover

**Files:** Create `src/alcove/editing.py`, `tests/test_editing.py`; modify `src/alcove/app.py`, `src/alcove/library.py`, `tests/test_api.py`

**Interfaces:**
- `editing.FIELDS = ("title", "authors", "series", "series_index", "description", "publisher", "published", "language", "tags")`.
- `editing.clean_details(patch: dict, *, require: bool = False) -> dict` — validates and tidies: strings stripped, whitespace collapsed (description keeps paragraph breaks); title 1–500 chars; authors list of 1–20 non-empty names (≤ 200 chars each), duplicates dropped; tags ≤ 50 of ≤ 60 chars; series ≤ 300; `series_index` finite number 0–100000 or null (null when series empty); description ≤ 20000; `published` `""` or `YYYY`, `YYYY-MM`, `YYYY-MM-DD` (a valid date); language ≤ 20; unknown key → ValueError naming it. `require=True` also needs a title and at least one author ("Fill in the title and at least one author").
- `editing.edit_book(cfg, book_id, patch) -> None` — writes the cleaned fields (+ `sort_title`, `author_sort`, `updated_at`, the search index) and adds them to `locked`. LookupError if no book.
- `editing.set_cover(cfg, book_id, image: bytes) -> None` — refuses non-images, over 20 MB, over 50 megapixels (ValueError "That isn't a picture Alcove can use"); stores it, locks `cover`. `editing.clear_cover(cfg, book_id)` — no cover (the generated one shows), locked.
- Routes (admin): `PATCH /api/books/{id}` → the book as `GET` returns it; `PUT /api/books/{id}/cover` with the image as the raw body; `DELETE /api/books/{id}/cover`.
- `library.book_card` gains `"cover_v": int(updated_at)`; `cover.js` adds `&v=` to cover URLs so a new cover shows at once.
- [ ] **Step 1: Failing tests:** edit title/authors/series → `GET` and search show the new values; `sort_title` drops "The"; each invalid value refused with its field named; `require=True` without authors refused; **Review Focus 1:** edit a loose PDF's title and set a cover, touch the file (new mtime) and rescan → title and cover stay while an unlocked field (publisher from the file) still updates; same for a Calibre book after `metadata.db` changes; a member gets 403; a text file as cover → 400.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Edit a book's details and cover; scans keep what the admin set"`

### Task 4: Page layout switches for scans

**Files:** Modify `src/alcove/pages.py`, `src/alcove/library.py`, `src/alcove/app.py`, `tests/test_pages.py`, `tests/test_api.py`

**Interfaces:**
- `pages.split_plan(sizes, scanned=True, *, split: bool | None = None, wraparound: bool | None = None)` — `split=None` is today's rule; `True` splits every spread page whatever the count or text layer; `False` never splits. `wraparound=None` is today's rule (first page a spread while splitting); `False` keeps a first spread in reading order (left, right); `True` is the same as auto (it only applies when the first page is a spread).
- `manifest` reads `book_files.layout`; its `version` becomes `int(mtime) + layout_rev` (so page URLs and the page cache change when the layout does).
- `pages.set_layout(cfg, file_id, split, wraparound) -> dict` — stores, bumps `layout_rev`, drops the file's `page_info` row; returns the new manifest. ValueError for formats other than pdf/cbz/cbr/cb7.
- Route (admin): `PATCH /api/files/{id}/layout` `{"split": true|false|null, "wraparound": true|false|null}`. `GET /api/books/{id}` files gain `"layout": {"split", "wraparound"}` for page-image formats.
- [ ] **Step 1: Failing tests:** a comic with 1 of 4 pages a spread → auto: 4 pages, `split=True`: 5; all-spread comic with `split=False` → not split; wraparound comic with `wraparound=False` → page 0 is the left half of scan 0; changing the layout changes `version`; an EPUB file → 400.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Per-book switches for two-page scans and wraparound covers"`

### Task 5: Open Library

**Files:** Create `src/alcove/openlibrary.py`, `tests/test_openlibrary.py`; modify `src/alcove/filemeta.py` (`FileMeta.isbn` from an EPUB `dc:identifier` that is a valid ISBN-10/13), `src/alcove/app.py`

**Interfaces:**
- `openlibrary.LookupFailed(Exception)` (message for people); `openlibrary.LookupsOff(LookupFailed)` ("Online lookups are turned off in Library settings").
- `openlibrary.search(cfg, *, title="", author="", isbn="") -> list[dict]` — up to 6 candidates `{"key", "title", "authors", "published", "publisher", "language", "tags", "isbn", "cover_url"}`; ISBN first (`/search.json?isbn=`), else `title`+`author`; `fields=key,title,author_name,first_publish_year,publisher,language,subject,isbn,cover_i`; `tags` = first 8 subjects; `cover_url` = `https://covers.openlibrary.org/b/id/{cover_i}-L.jpg?default=false` or null; missing fields → empty values.
- `openlibrary.description(cfg, key: str) -> str` — `key` must match `^/works/OL\d+W$`; text of the work's `description` (string or `{"value"}`), else `""`.
- `openlibrary.fetch_cover(cfg, url: str) -> bytes` — only `https://covers.openlibrary.org/` URLs (ValueError otherwise), ≤ 10 MB.
- All network through one `_get(url, limit) -> bytes` (urllib, 10 s timeout, `User-Agent: Alcove/0.1 (self-hosted ebook library)`); any network/HTTP/JSON error → `LookupFailed("Open Library didn’t answer; try again in a moment, or fill the details in by hand")`. Each call checks `get_library(cfg)["online_lookups"]` first.
- Routes (admin): `GET /api/lookup?title=&author=&isbn=`; `GET /api/lookup/description?key=`; `POST /api/books/{id}/cover/lookup` `{"url"}` → fetch then `editing.set_cover`. `LookupsOff` → 403, `LookupFailed` → 502, bad URL/key → 400.
- [ ] **Step 1: Failing tests** (monkeypatch `openlibrary._get`): search maps a full doc and a doc missing everything but the title; ISBN is used when given; description handles string, `{"value"}` and absent; **Review Focus 5:** `_get` raising timeout / returning HTML → `LookupFailed`; lookups off → `LookupsOff` and `_get` never called; `fetch_cover("http://169.254.169.254/x")` and `https://evil.example/` → ValueError without calling `_get`; EPUB with `urn:isbn:9780141439518` → `FileMeta.isbn`.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Open Library lookups for details and covers"`

### Task 6: Adding books

**Files:** Create `src/alcove/uploads.py`, `tests/test_uploads.py`; modify `src/alcove/app.py`, `src/alcove/scanner.py` (`Scanner._loop` also calls `uploads.prune_drafts`)

**Interfaces:**
- `uploads.MAX_UPLOAD = 2 * 1024**3`; drafts live in `cfg.data_dir / "uploads" / token`; tokens are `secrets.token_urlsafe(16)` and must match `^[A-Za-z0-9_-]{22}$` everywhere (LookupError otherwise).
- `uploads.start(cfg, filename: str, chunks: Iterable[bytes]) -> dict` — refuses files that aren't books (`format_of` with the library's txt switch: "Alcove can’t read .docx files"), empty or over `MAX_UPLOAD` (partial file removed); reads `read_file_meta` + `extract_cover`; returns the draft `{"token", "filename", "format", "size", "details": {FIELDS…}, "isbn", "has_cover", "same_as": [book cards with the same title and first author]}`.
- `uploads.draft_cover(cfg, token) -> Path | None`, `uploads.discard(cfg, token)`, `uploads.prune_drafts(cfg, max_age=2 days)`.
- `uploads.safe_name(text: str, fallback: str) -> str` — removes `/ \ : * ? " < > |` and control characters, collapses whitespace, strips leading/trailing dots and spaces, cuts to 80 characters, appends `_` to Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1–9`, `LPT1–9`, case-insensitive, with or without extension); empty → fallback.
- `uploads.save(cfg, token, details: dict, *, cover_url: str | None = None) -> int` — `editing.clean_details(details, require=True)`; destination `upload_dir / safe_name(first author) / safe_name(title) / safe_name(original stem) + .ext`, resolved and checked to be inside `upload_dir`; if it exists, ` (2)`, ` (3)`… before the extension; moved with `shutil.move`; on OSError → ValueError `"Alcove can’t save into {upload_dir}: {reason}. Check that the folder can be written to."` with the draft kept. Then records the book (`_write_book`, all of `FIELDS` locked, `added_at` now), its file row (root = `upload_dir`, size and mtime from the saved file) and its cover (`cover_url` via `openlibrary.fetch_cover`, else the file's own); deletes the draft; returns the book id.
- Routes (admin): `PUT /api/uploads?name=…` (raw body streamed to disk, 413 when too big); `GET /api/uploads/{token}/cover`; `POST /api/uploads/{token}/save` `{"details", "cover_url"}` → `{"book_id"}`; `DELETE /api/uploads/{token}`.
- [ ] **Step 1: Failing tests:** upload an EPUB → draft details from the file and `has_cover`; save → file at `books/A/Tale/Tale.epub`, book visible with locked details, then a scan reports nothing added or updated; `.docx` → 400; missing author on save → 400 and draft kept; **Review Focus 2:** `safe_name` cases (`../../x`, `CON`, `con.txt`, `a:b?`, 300 chars, `""`), a save whose author is `..` stays inside the folder, a second identical save becomes `Tale (2).epub`; **Review Focus 3:** `upload_dir` made read-only (`chmod 0o500`, skipped if running as root) → 400 naming the folder and the draft still saves after `chmod` back; a bad token → 404; drafts older than 2 days are pruned.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Add books: upload, review the details, save into the books folder"`

### Task 7: Shelves

**Files:** Create `src/alcove/shelves.py`, `tests/test_shelves.py`; modify `src/alcove/library.py`, `src/alcove/settings.py`, `src/alcove/app.py`, `tests/test_settings.py`

**Interfaces:**
- `shelves.list_shelves(cfg, user_id) -> list[dict]` `[{"id", "name", "kind", "count"}]` — "Want to read" (`kind "want"`, created on first call) first, then own shelves by name.
- `create(cfg, user_id, name) -> dict`, `rename(cfg, user_id, shelf_id, name)`, `delete(cfg, user_id, shelf_id)`, `add(cfg, user_id, shelf_id, book_id)`, `remove(...)`, `for_book(cfg, user_id, book_id) -> list[int]`. Names 1–40 characters, unique per person ignoring case ("You already have a shelf called …"); "Want to read" can't be renamed or deleted; another person's shelf → LookupError (404).
- `library.list_books(..., user=None)` gains kinds `shelf` (value = shelf id, the person's own) and `finished` (books whose progress is finished). `library.get_book` gains `"shelves": [ids]`.
- Home: `settings.HOME_ROW_KINDS` gains `"shelves"` (after `continue`); one row per non-empty shelf, then "Finished" (kind `finished`) if any. `get_settings` keeps a stored `home_rows` from before this kind existed by appending the missing kinds (visible) instead of dropping the person's order.
- Routes (`current_user`): `GET/POST /api/shelves`, `PATCH/DELETE /api/shelves/{id}`, `PUT/DELETE /api/shelves/{id}/books/{book_id}`.
- [ ] **Step 1: Failing tests:** Want to read exists and comes first; create/rename/delete; duplicate name refused; sam can't see or add to admin's shelf (404); shelf and finished lists; a home row per shelf; stored old `home_rows` (4 kinds, `recent` hidden) still has `recent` hidden plus `shelves` visible.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Shelves: Want to read, your own shelves, Finished"`

### Task 8: The library check

**Files:** Create `src/alcove/check.py`, `tests/test_check.py`; modify `src/alcove/scanner.py` (after each scan: `check.check_files(cfg)`), `src/alcove/library.py` (`merge_books`), `src/alcove/app.py`

**Interfaces:**
- `check.check_files(cfg) -> None` — for each readable file whose `file_checks` row is missing or has an old mtime: `pages.manifest` or `flowbooks.open_flow`; records `ok`, or the `Unreadable` kind (`damaged`/`protected`); other exceptions → `damaged`.
- `check.problems(cfg) -> dict` → `{"items": [...], "ignored": int, "last_scan": report|None}`; items `{"kind", "key", "title", ...}` in this order of kinds, ignored ones left out:
  - `damaged`, `protected` (key file id; `book` card, `format`);
  - `unreachable_folder`, `unreadable_folder`, `calibre_missing` (key the path) from the last scan report;
  - `no_cover`, `no_author` (key book id; `book`);
  - `filename_title` (key book id) — a non-Calibre book whose `title` isn't locked and equals `title_from_filename` of its first file;
  - `duplicate` (key the sorted book ids joined by `,`; `books`) — same title (case-folded, punctuation and leading article dropped), same authors (case-folded, sorted), same series and number;
  - `series_gap` (key the series; `missing: [int]`, `books`) — series with ≥ 2 books and whole-number indices, missing numbers between 1 and the highest (at most 50 listed).
- `check.ignore(cfg, kind, key)`, `check.unignore(cfg, kind, key)`, `check.list_ignored(cfg)`.
- `library.merge_books(cfg, into: int, other: int) -> None` — moves `other`'s files, shelf entries, bookmarks and progress (keeping the newer progress if both have one) to `into`, deletes `other`, locks every field of `into` plus its cover (so Calibre can't split them again).
- Routes (admin): `GET /api/check`; `POST/DELETE /api/check/ignored` `{"kind", "key"}`; `GET /api/check/ignored`; `POST /api/books/{id}/merge` `{"other"}`.
- [ ] **Step 1: Failing tests:** the encrypted PDF shows as `protected` after a scan; a truncated PDF as `damaged`; a book with no cover and no author appears under both; "Who's #1? odd" (title from filename) is listed and disappears after editing its title; two PDFs "The Tale"/"tale" by "A" are a duplicate; series #1, #2, #4, #6 → missing `[3, 5]`; ignoring removes an item and raises `ignored`; unignore brings it back; merge leaves one book with two files and the other's progress; a member gets 403.
- [ ] **Steps 2–5:** run → FAIL, implement, run → pass, commit `"Library check: what needs attention, with ignore and merge"`

### Task 9: The screens

Load `frontend-design:frontend-design` first. Same dark, warm look as M1–M3; admin screens use the existing `.page.narrow` / `.panel` patterns, never a generic admin-table look.

**Files:** Modify `src/alcove/web/js/book.js`, `admin.js`, `main.js`, `home.js`, `grid.js`, `settings.js`, `cover.js`, `login.js`, `index.html` (icons: edit, plus, check, shelf), `style.css`; create `src/alcove/web/js/edit.js` (book editing), `add.js` (adding books), `check.js` (library check), `shelfmenu.js`

Decisions:
- **Top bar:** the library name (or "Alcove") as the brand and in the sign-in page and `document.title`. Admins get an "Add books" icon next to the gear.
- **Book page, everyone:** a "Shelves" button opens a small menu of the person's shelves with ticks, plus "New shelf…".
- **Book page, admin:** "Edit" turns the title, authors, series and number, description, publisher, published, language and tags into fields in place (same layout, inputs styled like the text they replace); Save / Cancel; errors under the field the server named. Beside the cover: "Change cover" → upload a picture, "Find covers online" (Open Library candidates as a row of covers to pick), or "No cover". "Fill from Open Library" lists candidates (cover, title, author, year); picking one fills only empty fields, and fetches its description if the description is empty. For page-image books: "Two pages per scan: Automatic / Split / Don't split" and "Wraparound cover: Automatic / Front first / As scanned". `#/book/ID?edit=1` opens in edit mode, `?edit=cover` opens straight to covers.
- **Add books (`#/add`):** a large drop area (and a file picker) taking many files; each upload shows progress, then a review card: cover, details pre-filled (fields as on the book page; title and author marked as needed), "Fill from Open Library", a note if it looks like a book already in the library (link), Save / Discard. Saved cards collapse to "Added — Open book".
- **Library settings (`#/admin`):** sections People (make/unmake admin, reset password with a one-time field, remove; you can't remove yourself), Books folders (list with remove, add a path, which folder uploads go into, scan every N minutes, Rescan now, last scan's result and time), Library (name, plain-text files switch with the warning that a notes or passwords file would show up, online lookups switch noting what is sent), and a link to the library check with its count. Removing a folder asks first and says its books and everyone's progress in them go.
- **Library check (`#/check`):** groups by kind with a plain heading and count; each item shows the book (small cover, title) and one or two direct fixes: Edit / Find a cover (book page in edit mode), Merge into this one / Keep both, Ignore, Download (damaged/protected); a "Show ignored" toggle with Unignore. Empty state: "Nothing needs attention."
- **Shelves:** home shows the shelf rows (Your settings' row list gains "Your shelves"); `#/all?kind=shelf&value=ID` and `kind=finished` grids; shelves can be renamed or deleted from their grid page.
- [ ] **Step 1: Build.**
- [ ] **Step 2: Verify in Chromium** (scratch data dir and a scratch books folder copied from the test fixtures plus a few real files; never the real share): edit a book's title and cover and see it on the home row at once; Open Library fill (live) on one book; add an EPUB and a PDF by upload and find them in Recently added; split/wraparound switch on a comic; people actions; add/remove a folder; library check with an ignore and a merge; shelves on the book page and home; at 1440×900 and 390×844, no console errors, no sideways overflow.
- [ ] **Step 3: Run** `bash test.sh -q` → pass. **Step 4: Commit** `"Adding, editing and checking the library in the app; shelves"`

### Task 10: Design doc

**Files:** Modify `docs/superpowers/specs/2026-11-16-alcove-design.md` — mark M4 done; add to "Calls made without asking": edits lock fields against later scans; library settings in the database override `config.toml` once saved; removing a folder in settings drops its books and progress, a folder missing from config does not; uploads limited to 2 GB and go into a chosen books folder; duplicates are merged into one book rather than removed (files are never deleted); series gaps count from #1; "Finished" is the books you finished, not a shelf you fill. Commit `"Design: M4 done, and the calls it made"`.
