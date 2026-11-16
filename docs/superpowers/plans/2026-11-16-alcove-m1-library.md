# Alcove M1 — Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running Alcove server that scans the books folder (importing Calibre's details), signs people in, and shows the "cover wall" library, book pages and search in the browser.

**Architecture:** A FastAPI app (`alcove.app.create_app(cfg)`) over a SQLite database in the data dir. A scanner walks the books folders, reads Calibre's `metadata.db` read-only and each file's own details, and records one book per Calibre entry or per loose file. Covers are extracted once into the data dir. The web app is plain JS modules served from `src/alcove/web/`, hash-routed.

**Tech Stack:** Python 3.14+, FastAPI, uvicorn, SQLite (FTS5), itsdangerous, Pillow, pypdfium2; tests with pytest + httpx (TestClient) + pypdf (to make test PDFs).

**Spec:** `docs/superpowers/specs/2026-11-16-alcove-design.md`

## Global Constraints

- Python `>=3.14`; packaged with `uv` (`uv_build`), console script `alcove = "alcove:main"`.
- The venv lives on local disk: `UV_PROJECT_ENVIRONMENT=$HOME/.local/share/alcove/venv`, `UV_LINK_MODE=copy` (the NAS share can't hold a venv). `run.sh` starts the server; `test.sh` runs pytest — both set those two variables.
- Default port **4545**, host `0.0.0.0`. Data dir default `~/.local/share/alcove` (Linux/macOS), `%LOCALAPPDATA%\Alcove` (Windows).
- **The books folders are read-only to Alcove in M1.** Nothing under a books folder is created, renamed or written. Calibre's `metadata.db` is opened with `?mode=ro&immutable=1`.
- Book formats (and only these) are shown: `epub, pdf, cbz, cbr, cb7, mobi, azw, azw3, fb2, txt`. Everything else (docx, opf, jpg, db, json…) is ignored.
- The web app makes **no requests to the internet at runtime** (fonts and libraries are vendored under `src/alcove/web/`).
- Look: dark warm palette — background `#14110f`, raised surface `#1f1a17`, line `#2a2420`, text `#e8e0d6`, muted `#9a8f84`, accent `#c9a27a`. Covers first.
- Every API route except `/api/setup`, `/api/login` and `/api/status` requires a signed-in user; admin-only routes return 403 for members.

## Review Focus

1. **Books share unreachable during a scan** (SMB mount dropped, folder missing or empty listing): a reasonable person expects their library to still be there afterwards — the scan must not remove books under a root that is missing or unreadable. Test in Task 5.
2. **Junk embedded titles in loose PDFs** ("Microsoft Word - report.doc", "untitled", "Untitled1", blank, or just the filename): expected to show a clean title from the filename instead. Test in Task 3.
3. **Calibre descriptions are HTML** (122 books have them; could contain `<script>`, links, inline styles): expected to read as plain paragraphs and never execute anything. Test in Task 4 (sanitise) and Task 8 (API returns text, not HTML).
4. **Damaged, encrypted or zero-byte book files**: expected to still appear (title from filename, generated cover), and the scan carries on. Test in Task 5.
5. **File and cover requests by id only**: odd filenames (`#`, quotes, `?`, unicode, `..`) must work, and no request can read a path that isn't a registered book file. Test in Task 8.

---

## File Structure

```
pyproject.toml  .python-version  run.sh  test.sh  config.example.toml  .gitignore
src/alcove/__init__.py      main(): load config, start uvicorn
src/alcove/__main__.py      python -m alcove
src/alcove/config.py        Config dataclass, load_config()
src/alcove/db.py            schema, connect(), session()
src/alcove/formats.py       BOOK_FORMATS, format_of()
src/alcove/filemeta.py      read_file_meta(): details from the file itself, title cleaning
src/alcove/calibre.py       read_calibre(): Calibre metadata.db → CalibreBook by file path; html_to_text()
src/alcove/covers.py        extract_cover(), store_cover(), cover_path()
src/alcove/scanner.py       scan(), Scanner background thread
src/alcove/auth.py          users, passwords, sessions (adapted from Shelf's auth.py)
src/alcove/library.py       queries: home(), list_books(), get_book(), search()
src/alcove/app.py           create_app(): routes + static web app
src/alcove/web/             index.html, style.css, fonts/, icons/, js/*.js
tests/conftest.py          fixtures: cfg, make_pdf, make_epub, make_cbz, make_calibre_db, client
tests/test_*.py
```

---

### Task 1: Project skeleton and config

**Files:**
- Create: `pyproject.toml`, `.python-version` (`3.14`), `run.sh`, `test.sh`, `config.example.toml`, `src/alcove/__init__.py`, `src/alcove/__main__.py`, `src/alcove/config.py`, `tests/test_config.py`
- Modify: `.gitignore` (already ignores `config.toml`, `/data/`)

**Interfaces:**
- Produces: `Config` dataclass with fields `books_dirs: list[Path]`, `data_dir: Path`, `host: str = "0.0.0.0"`, `port: int = 4545`, `scan_interval_minutes: int = 10`, `secret_key: str = ""`; properties `db_path` (`data_dir/"alcove.db"`), `cover_dir` (`data_dir/"covers"`). `load_config(path: Path | None = None) -> Config` — reads TOML (default `./config.toml`, missing file = defaults); env overrides `ALCOVE_BOOKS_DIRS` (paths separated by `os.pathsep`), `ALCOVE_DATA_DIR`, `ALCOVE_PORT`. `~` expanded in paths. If `secret_key` is empty, one is generated and persisted to `data_dir/secret_key` (reused next start).
- Produces: `alcove.main()` — `load_config()`, creates data dir, `uvicorn.run(create_app(cfg), host, port)`.

Dependencies: `fastapi`, `uvicorn[standard]`, `itsdangerous`, `pillow`, `pypdfium2`. Dev group: `pytest`, `httpx`, `pypdf`.

- [ ] **Step 1: Write the failing tests** in `tests/test_config.py`:
  - `test_defaults_without_file`: `load_config(tmp_path/"none.toml")` → `port == 4545`, `books_dirs == []`.
  - `test_reads_toml`: file with `books_dirs = ["~/Books"]`, `port = 5000` → `books_dirs == [Path.home()/"Books"]`, `port == 5000`.
  - `test_env_overrides`: `monkeypatch.setenv("ALCOVE_BOOKS_DIRS", f"/a{os.pathsep}/b")` → `books_dirs == [Path("/a"), Path("/b")]`.
  - `test_secret_key_persists`: two `load_config` calls with the same `ALCOVE_DATA_DIR` give the same non-empty `secret_key`.
- [ ] **Step 2: Run** `./test.sh tests/test_config.py -v` → FAIL (`ModuleNotFoundError: alcove`).
- [ ] **Step 3: Implement** the files above. `config.example.toml` documents every field with a one-line comment; example books dir `/var/mnt/smb-g/EBooks`.
- [ ] **Step 4: Run** `./test.sh tests/test_config.py -v` → 4 passed.
- [ ] **Step 5: Commit** `git add -A && git commit -m "Alcove skeleton: config, run and test scripts"`

### Task 2: Database and formats

**Files:**
- Create: `src/alcove/db.py`, `src/alcove/formats.py`, `tests/test_formats.py`, `tests/test_db.py`

**Interfaces:**
- Produces `formats.BOOK_FORMATS: dict[str, str]` mapping lower-case extension (no dot) → format name (`"epub"`, `"pdf"`, `"cbz"`, `"cbr"`, `"cb7"`, `"mobi"`, `"azw"`, `"azw3"`, `"fb2"`, `"txt"`); `format_of(path: Path) -> str | None`.
- Produces `db.connect(path: Path) -> sqlite3.Connection` (WAL, `row_factory = sqlite3.Row`, foreign keys on, schema created) and `db.session(path) ` context manager (commit on success, rollback on error, close).
- Schema (later tasks rely on these exact names):
  - `users(id, username UNIQUE COLLATE NOCASE, password_hash, admin INTEGER, version INTEGER DEFAULT 1, created_at REAL)`
  - `books(id, title, sort_title, authors TEXT /*JSON list*/, author_sort, series, series_index REAL, description TEXT /*plain text*/, publisher, published TEXT, language, tags TEXT /*JSON list*/, calibre_id INTEGER, cover_color TEXT, has_cover INTEGER DEFAULT 0, added_at REAL, updated_at REAL)`
  - `book_files(id, book_id REFERENCES books ON DELETE CASCADE, path TEXT UNIQUE, format, size INTEGER, mtime REAL, root TEXT)` — `root` is the books dir it was found under.
  - `books_fts` — FTS5, `content=''`-less simple table `(title, authors, series, tags)`, `tokenize='unicode61 remove_diacritics 2'`, rowid = `books.id`.
  - `meta(key PRIMARY KEY, value)` — e.g. `calibre_mtime:<root>`.

- [ ] **Step 1: Write failing tests:** `test_format_of` — `format_of(Path("A/B.PDF")) == "pdf"`, `"x.cbr" → "cbr"`, `"x.azw3" → "azw3"`, and `None` for `x.docx`, `metadata.opf`, `cover.jpg`, `metadata.db`, `noext`. `test_schema_created` — `connect(tmp/"f.db")` then each table name above exists in `sqlite_master`; deleting a book deletes its `book_files` rows.
- [ ] **Step 2: Run** `./test.sh tests/test_formats.py tests/test_db.py -v` → FAIL.
- [ ] **Step 3: Implement** `formats.py` and `db.py`.
- [ ] **Step 4: Run** → all pass.
- [ ] **Step 5: Commit** `"Database schema and book formats"`

### Task 3: Details from the file itself

**Files:**
- Create: `src/alcove/filemeta.py`, `tests/conftest.py` (fixtures `make_pdf`, `make_epub`, `make_cbz`), `tests/test_filemeta.py`

**Interfaces:**
- Produces `FileMeta` dataclass: `title: str`, `authors: list[str]`, `description: str = ""`, `language: str = ""`, `published: str = ""`, `publisher: str = ""`, `series: str = ""`, `series_index: float | None = None`, `encrypted: bool = False`.
- Produces `read_file_meta(path: Path, fmt: str) -> FileMeta` — never raises (any error → title from filename, `authors=[]`).
- Produces `title_from_filename(path: Path) -> str` and `is_junk_title(title: str, path: Path) -> bool`.
- Test fixtures (conftest): `make_pdf(path, *, title=None, author=None, pages=1, encrypt=False)` via pypdf; `make_epub(path, *, title, author, cover: bytes | None = None, series=None, series_index=None)` — zip with `mimetype`, `META-INF/container.xml`, OPF (Dublin Core + `calibre:series` meta + cover manifest item), one XHTML; `make_cbz(path, pages=3)` — zip of PNGs named `page10.png, page2.png, page1.png` (out of order on purpose).

Rules:
- PDF: `/Title`, `/Author` (split on `;`, `&`, ` and `), via pypdfium2 `get_metadata_dict()`; encrypted/unreadable → `encrypted=True` when the password error is the cause.
- EPUB: parse `META-INF/container.xml` → OPF; `dc:title`, every `dc:creator`, `dc:description` (through `calibre.html_to_text` — import lazily; Task 4 defines it, so write Task 3 with a local plain-text fallback and switch to it in Task 4), `dc:language`, `dc:date`, `dc:publisher`, `calibre:series`/`calibre:series_index`, or EPUB3 `belongs-to-collection`/`group-position`.
- Other formats in M1: filename only.
- `title_from_filename`: stem; drop a trailing `" - <author>"` (Calibre's `Title - Author` naming); `_` between words → `": "` when followed by a space (Calibre writes `:` as `_`), other `_` → space; collapse whitespace.
- `is_junk_title`: empty/whitespace; starts with `Microsoft Word - `; matches `^untitled\d*$` (case-insensitive); equals the file's stem; ends in a file extension (`.doc`, `.docx`, `.pdf`, `.indd`, `.qxd`).

- [ ] **Step 1: Write failing tests:**
  - `test_pdf_title_author`: `make_pdf(title="The Long Road", author="A. Marlow; B. Field")` → `title == "The Long Road"`, `authors == ["A. Marlow", "B. Field"]`.
  - `test_pdf_junk_title_uses_filename` (parametrised over `"Microsoft Word - draft.doc"`, `"untitled"`, `"Untitled1"`, `"   "`): file `Fernwood - J. Okafor.pdf` → `title == "Fernwood"`.
  - `test_calibre_style_filename`: `title_from_filename(Path("Assassin's Creed_ Uprising #1 - Alex Paknadel.pdf")) == "Assassin's Creed: Uprising #1"`.
  - `test_epub_details`: `make_epub(title="Tide Line", author="J. Okafor", series="Coast", series_index=2)` → those values, `series_index == 2.0`.
  - `test_broken_files_never_raise`: zero-byte `x.pdf`, garbage-bytes `y.epub` → `FileMeta` with filename titles.
  - `test_encrypted_pdf_flagged`: `make_pdf(encrypt=True)` → `encrypted is True`.
- [ ] **Step 2: Run** `./test.sh tests/test_filemeta.py -v` → FAIL.
- [ ] **Step 3: Implement** `filemeta.py`.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `"Read titles, authors and series from book files"`

### Task 4: Calibre import

**Files:**
- Create: `src/alcove/calibre.py`, `tests/test_calibre.py`; add fixture `make_calibre_db(root, books: list[dict])` to `tests/conftest.py`

**Interfaces:**
- Produces `CalibreBook` dataclass: `calibre_id: int`, `title: str`, `sort_title: str`, `authors: list[str]`, `author_sort: str`, `series: str`, `series_index: float | None`, `description: str` (plain text), `publisher: str`, `published: str` (`YYYY-MM-DD` or `""`; Calibre's `0101-01-01` placeholder → `""`), `language: str`, `tags: list[str]`, `cover: Path | None` (`<root>/<books.path>/cover.jpg` if `has_cover` and it exists), `files: list[Path]` (from `data`: `<root>/<books.path>/<name>.<format.lower()>`).
- Produces `read_calibre(root: Path) -> dict[Path, CalibreBook]` keyed by each file path (several formats → same `CalibreBook`); `{}` if `root/"metadata.db"` is absent or unreadable. Opens `file:{db}?mode=ro&immutable=1` with `uri=True`.
- Produces `html_to_text(html: str) -> str` — `<p>`, `<br>`, `<div>`, `<li>` become line breaks (paragraphs separated by one blank line), all other tags dropped, `<script>`/`<style>` dropped *with* their content, entities unescaped, whitespace tidied. Uses `html.parser.HTMLParser`.
- `make_calibre_db` builds the subset of Calibre's schema Alcove reads: `books(id, title, sort, author_sort, path, has_cover, series_index, pubdate)`, `authors(id, name)`, `books_authors_link(book, author)`, `series(id, name)`, `books_series_link(book, series)`, `tags(id, name)`, `books_tags_link(book, tag)`, `comments(book, text)`, `publishers(id,name)`, `books_publishers_link(book, publisher)`, `languages(id, lang_code)`, `books_languages_link(book, lang_code)`, `data(book, format, name)`; and writes the book files + `cover.jpg` it lists.

- [ ] **Step 1: Write failing tests:**
  - `test_reads_calibre_book`: one book "It" by "Stephen King", series "Dark Tower" index 3, tags `["Horror","Fiction"]`, PDF file, cover → every field above maps; key is the PDF's path.
  - `test_two_formats_one_book`: EPUB + PDF for one id → two keys, same `CalibreBook`.
  - `test_html_to_text`: `'<p>One &amp; two</p><script>alert(1)</script><p>Three<br>four</p>'` → `"One & two\n\nThree\nfour"`.
  - `test_missing_or_corrupt_db`: no `metadata.db` → `{}`; a `metadata.db` of random bytes → `{}`.
  - `test_never_writes`: file mtime of `metadata.db` and directory listing of `root` unchanged after `read_calibre` (no `-wal`/`-shm` created).
- [ ] **Step 2: Run** `./test.sh tests/test_calibre.py -v` → FAIL.
- [ ] **Step 3: Implement** `calibre.py`; switch `filemeta` EPUB description to `html_to_text`.
- [ ] **Step 4: Run** `./test.sh -v` → all pass.
- [ ] **Step 5: Commit** `"Import titles, series, tags and covers from Calibre"`

### Task 5: Covers and the scanner

**Files:**
- Create: `src/alcove/covers.py`, `src/alcove/scanner.py`, `tests/test_covers.py`, `tests/test_scanner.py`

**Interfaces:**
- Consumes: `format_of`, `read_file_meta`, `read_calibre`, `db.session`.
- Produces `covers.extract_cover(path: Path, fmt: str) -> bytes | None` — EPUB: OPF cover item (manifest `properties="cover-image"`, or `<meta name="cover">` id); PDF: page 1 rendered with pypdfium2 at 600 px wide; CBZ: first image by natural sort (`page2` before `page10`); others `None`. Never raises.
- Produces `covers.store_cover(cfg, book_id: int, image: bytes) -> str` — writes `cover_dir/{book_id}-480.jpg` and `-240.jpg` (width, keep aspect, JPEG q85, RGB) and returns the cover colour as `#rrggbb`: the average colour of the image, darkened so its HSL lightness ≤ 0.30 (used behind the "continue reading" panel).
- Produces `covers.cover_path(cfg, book_id: int, width: int) -> Path | None` — `width` snapped to 240 or 480.
- Produces `scanner.scan(cfg) -> ScanResult` (`added: int, updated: int, removed: int`) and `scanner.Scanner(cfg)` with `.start()` (scan now, then every `scan_interval_minutes` in a daemon thread), `.trigger()` (scan soon), `.running: bool`, `.last: ScanResult | None`.

Scan rules:
- For each root in `books_dirs`: if it does not exist, isn't a directory, or listing it raises → log a warning and **skip it entirely, including removals**.
- Walk with `os.scandir` recursively; skip names starting with `.`; keep files where `format_of` is not `None`.
- Calibre files: one book per `calibre_id` (look up by `books.calibre_id`); details from `CalibreBook`; cover from its `cover.jpg`. Loose files: one book per file; details from `read_file_meta`; cover from `extract_cover`.
- A file whose `(size, mtime)` matches `book_files` is skipped. Changed → details and cover re-read (`updated`). New → book + file inserted with `added_at = now` (`added`). Calibre re-read only when `metadata.db`'s mtime differs from `meta["calibre_mtime:<root>"]`.
- Files under a reachable root that are gone → their `book_files` row deleted; a book with no files left is deleted with its covers (`removed`).
- `sort_title` drops a leading "The ", "A ", "An "; `books_fts` row replaced whenever a book is written.

- [ ] **Step 1: Write failing tests:**
  - `test_cover_from_each_format` (parametrised EPUB-with-cover, PDF, CBZ): `extract_cover` returns bytes Pillow can open; for CBZ, image is the one from `page1.png` (fill each test page with a distinct colour and check the pixel).
  - `test_store_cover_sizes_and_colour`: two files with widths 480 and 240; colour string matches `^#[0-9a-f]{6}$` and its HSL lightness ≤ 0.30.
  - `test_scan_library`: root with a Calibre book (PDF), a loose `Comics/Thing #1.cbz`, `Unknown/Passwords - Unknown.docx` → 2 books, no book has "Passwords" in its title.
  - `test_rescan_unchanged_is_noop`: second `scan` → `ScanResult(0, 0, 0)`.
  - `test_removed_file`: delete the CBZ, rescan → `removed == 1`, its cover files gone.
  - `test_unreachable_root_keeps_books`: scan, then point `books_dirs` at the now-renamed root (missing) and scan → `removed == 0`, book count unchanged.
  - `test_broken_file_still_listed`: zero-byte `Broken Book.pdf` → one book titled "Broken Book", `has_cover == 0`, scan completes.
- [ ] **Step 2: Run** `./test.sh tests/test_covers.py tests/test_scanner.py -v` → FAIL.
- [ ] **Step 3: Implement** `covers.py` and `scanner.py`.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Real-library dry run:** with `ALCOVE_DATA_DIR=<scratch dir> ALCOVE_BOOKS_DIRS=/var/mnt/smb-g/EBooks`, run `UV_PROJECT_ENVIRONMENT=$HOME/.local/share/alcove/venv uv run python -c "from alcove.config import load_config; from alcove.scanner import scan; print(scan(load_config()))"`. Expected: `added` between 140 and 150 (135 Calibre books + the loose `Assassins Creed/` PDFs), no exceptions, no `Passwords` book, and a listing of `/var/mnt/smb-g/EBooks` taken before and after is identical.
- [ ] **Step 6: Commit** `"Scan the books folder with covers; never lose books when the share is down"`

### Task 6: Accounts

**Files:**
- Create: `src/alcove/auth.py` (adapted from `../Music Media Server/src/shelf/auth.py`: scrypt hashing, `TimestampSigner` session token carrying `user_id:version`, login lockout), `tests/test_auth.py`

**Interfaces:**
- Produces `User(id, username, admin, version)` with `.json() -> {"id","username","admin"}`; `COOKIE = "alcove_session"`; `create_user(cfg, username, password, admin=False) -> User` (raises `ValueError` with a human message for a bad name, password under 6 chars, or a taken name); `authenticate(cfg, username, password, ip) -> User | None`; `make_token(cfg, user) -> str`; `user_from_token(cfg, token) -> User | None`; `list_users(cfg) -> list[User]`; `delete_user(cfg, user_id)` (bumps nothing — row gone); `set_password(cfg, user_id, password)` (bumps `version`); `has_users(cfg) -> bool`.
- FastAPI dependencies (used by Task 8): `current_user(request) -> User` (cookie or `Authorization: Bearer`; 401 otherwise) and `admin_user(user) -> User` (403 for members).

- [ ] **Step 1: Write failing tests:** create + authenticate; wrong password → `None`; token round-trip; `set_password` invalidates the old token; 8 wrong passwords from one IP → the 9th correct attempt is refused within the window; `create_user` with `"bad/name"` or `"abc"` password raises `ValueError`.
- [ ] **Step 2: Run** `./test.sh tests/test_auth.py -v` → FAIL.
- [ ] **Step 3: Implement** `auth.py`.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `"Accounts and sessions"`

### Task 7: Library queries

**Files:**
- Create: `src/alcove/library.py`, `tests/test_library.py`

**Interfaces:**
- Produces `book_card(row) -> dict`: `{"id", "title", "authors": list[str], "series", "series_index", "has_cover": bool, "color"}`.
- Produces `home(cfg, user) -> dict`:
  `{"hero": card | None, "rows": [{"title": str, "kind": "recent"|"series"|"tag", "value": str | None, "books": [card...]}]}`.
  - `hero` in M1: the most recently added book (M2 replaces this with "continue reading").
  - Row 1 "Recently added": 15 newest by `added_at`.
  - Then up to 8 series rows: series with ≥ 2 books, ordered by their newest `added_at`, books by `series_index`; row title is the series name.
  - Then up to 6 tag rows: tags with ≥ 3 books, by book count, 20 books each by `sort_title`.
- Produces `list_books(cfg, *, kind: str | None, value: str | None, sort: "title"|"added"|"author" = "title", offset=0, limit=60) -> {"total": int, "books": [card]}` (`kind` `series`/`tag`/`author` filters).
- Produces `get_book(cfg, book_id) -> dict | None`: card plus `description`, `publisher`, `published`, `language`, `tags`, `files: [{"id","format","size"}]`, `series_books: [card]` (the rest of its series, ordered).
- Produces `search(cfg, q: str, limit=40) -> [card]` — FTS5 prefix match on each word (`word*`), diacritics-insensitive; quotes and FTS operators in `q` are neutralised (each word wrapped in double quotes before `*`); empty `q` → `[]`.

- [ ] **Step 1: Write failing tests** (insert rows directly via `db.session`): row order and limits above; series row books ordered 1, 2, 10 for indexes 10, 1, 2; tag row needs ≥3 books; `search("tide")` finds "Tide Line"; `search("Ökafor")` finds author "Okafor"; `search('"); DROP')` returns `[]` without raising; `get_book` of a missing id → `None`.
- [ ] **Step 2: Run** `./test.sh tests/test_library.py -v` → FAIL.
- [ ] **Step 3: Implement** `library.py`.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `"Home rows, browsing and search"`

### Task 8: HTTP API

**Files:**
- Create: `src/alcove/app.py`, `tests/test_api.py`; fixture `client` in conftest (a `TestClient(create_app(cfg))` over a scanned temp library, signed in as an admin)

**Interfaces:**
- Produces `create_app(cfg: Config) -> FastAPI`. Starts `Scanner(cfg)` on startup (tests may pass `scan_on_start=False`).
- Routes:
  - `GET /api/status` → `{"setup_needed": bool}` (no users yet).
  - `POST /api/setup {username, password}` → creates the first admin, sets cookie; 409 once any user exists.
  - `POST /api/login {username, password}` → sets cookie (`httponly`, `samesite=lax`, 1 year); 401 on failure. `POST /api/logout`. `GET /api/me`.
  - Admin: `GET /api/users`, `POST /api/users {username, password}` (member), `DELETE /api/users/{id}` (cannot delete yourself → 400), `POST /api/scan` → 202, `GET /api/scan` → `{"running", "last"}`.
  - `GET /api/home`, `GET /api/books?kind=&value=&sort=&offset=&limit=`, `GET /api/books/{id}`, `GET /api/search?q=`.
  - `GET /api/books/{id}/cover?w=240|480` → JPEG, `Cache-Control: private, max-age=86400`; 404 if none.
  - `GET /api/files/{file_id}` → the file (`FileResponse`, `Content-Disposition: attachment` with the original filename, RFC 5987-encoded). Only paths present in `book_files` are ever served.
  - `/` and other non-`/api` paths → `src/alcove/web/` static files, `index.html` for `/`.

- [ ] **Step 1: Write failing tests:** setup flow (status → setup → 409 on second setup); unauthenticated `/api/home` → 401; member `POST /api/scan` → 403; `/api/books/{id}` description for a Calibre book whose comment had `<script>` contains no `<`; cover returns `image/jpeg`; `/api/files/{id}` for a book named `Who's #1? ..\\odd.pdf` downloads with the right bytes; `/api/files/99999` → 404; `/api/search?q=tide` returns the card.
- [ ] **Step 2: Run** `./test.sh tests/test_api.py -v` → FAIL.
- [ ] **Step 3: Implement** `app.py`.
- [ ] **Step 4: Run** `./test.sh -v` → all pass.
- [ ] **Step 5: Commit** `"HTTP API for the library"`

### Task 9: The cover-wall web app

Load the `frontend-design:frontend-design` skill before writing this task's UI. Match the chosen mockup (`.superpowers/brainstorm/*/content/library-home.html`, option A).

**Files:**
- Create: `src/alcove/web/index.html`, `style.css`, `manifest.webmanifest`, `icons/icon.svg`, `fonts/` (self-hosted woff2: a warm serif for titles, a clean sans for interface — builder's pick, OFL-licensed), `js/api.js`, `js/main.js`, `js/login.js`, `js/home.js`, `js/grid.js`, `js/book.js`, `js/cover.js`, `js/admin.js`

**Interfaces:**
- Consumes: the Task 8 routes.
- `js/api.js`: `api(path, {method, body}) -> Promise<json>`; on 401 routes to `#/login`.
- `js/main.js`: hash router — `#/` home, `#/login`, `#/setup`, `#/all?kind=&value=&title=`, `#/book/:id`, `#/search?q=`, `#/admin` (admin only).
- `js/cover.js`: `coverEl(card, width) -> HTMLElement` — `<img loading="lazy">` from `/api/books/{id}/cover?w=`, or, when `has_cover` is false or the image fails, a generated cover: a gradient seeded from the title (stable per title) with the title and first author in the serif font.

Screens:
- **Login / setup:** centred card on the dark background; setup says "Create the admin account".
- **Home (cover wall):** top bar — "Library" wordmark, search field (Enter → `#/search`), and for admins a gear → `#/admin`. **Hero panel**: large cover, label "NEW IN YOUR LIBRARY" (M1), title, author, series, a gradient from `hero.color` to the background, "Read" button (M1: downloads the file via `/api/files/{first file id}` — replaced by the reader in M2). Then each row: title + "See all ›" (→ `#/all`), horizontally scrolling covers (scroll-snap; arrow buttons on hover on desktop; titles under covers, 2 lines max).
- **See all / search:** responsive cover grid (`repeat(auto-fill, minmax(120px, 1fr))`, 104px on phones), infinite scroll by 60.
- **Book page:** big cover left (top on phones), title (serif), authors (→ `#/all?kind=author`), series "Book 3 of Dark Tower" (→ series), description paragraphs, tags as chips (→ tag), formats with sizes and a Download button, then "More in this series" row.
- **Admin:** users list with add member / remove, and "Rescan library" with last result.
- Phone width (≤ 600px): 16px gutters, no horizontal page scroll, hero stacks.

- [ ] **Step 1: Build the screens** above.
- [ ] **Step 2: Run against the real library:** `ALCOVE_DATA_DIR=$HOME/.local/share/alcove-dev ALCOVE_BOOKS_DIRS=/var/mnt/smb-g/EBooks ./run.sh`, then `chromium-browser --headless=new --screenshot=<scratch dir>/home.png --window-size=1440,900 http://localhost:4545/` (after setup via `curl`), and the same at `--window-size=390,844`. Expected: covers load, hero shows a real book, series rows include "Assassin's Creed: Uprising" in order #1–#12, no horizontal scroll on the phone shot.
- [ ] **Step 3: Check** book page for "It" and a search for "avatar" by screenshot.
- [ ] **Step 4: Run** `./test.sh` → all pass.
- [ ] **Step 5: Commit** `"Cover-wall library, book pages and search in the browser"`
