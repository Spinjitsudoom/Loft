# Alcove — design

A self-hosted ebook library: a server that holds your books, and apps that let you and the people
you invite browse and read them, with pages that turn like paper.

Date: 2026-11-16. Status: approved to build ("let's start building and make adjustments from there").
Named Alcove (chosen 2026-11-16).

## Why

The owner wants their own ebook library rather than Kavita or Calibre-Web, because ready-made apps
feel clunky and their interfaces aren't to their taste. **How it looks and feels is the point.**
They've built Shelf (their music server, `../Music Media Server`) the same way and want a separate
app for books. They also want to stop using Calibre.

## Goals

- Read any common ebook format, on phone, tablet and PC, with realistic page-curl page turning.
- A library that feels like a bookstore window: dark, warm, covers first.
- Replace Calibre: import its library once, then add and edit books in Alcove.
- Several people: each with their own progress, bookmarks and shelves; members can submit and
  request books and discuss each book without spoilers.

## Non-goals

- Breaking DRM. Protected books are detected and flagged, not opened.
- Being open to the internet by default. Away from home goes through Tailscale (as Shelf does).
- Merging with Shelf. Separate app, separate server; it may borrow Shelf's code and patterns.

## Anti-goals (a failure even if it works)

- A clunky or generic interface: cramped toolbars, slow page turns, admin-panel look in reading
  screens.
- Changing or moving the owner's existing book files.
- Showing non-book files from the books folder (there is a `Passwords.docx` in it today).
- Spoiling a book for someone through the discussion.

## The library today

`/var/mnt/smb-g/EBooks` (an SMB share; on the media server the path will differ — it's config).

- A Calibre library: `metadata.db` lists 135 books, each in `Author/Title (id)/` with `cover.jpg`
  and `metadata.opf`. Plus folders Calibre doesn't know about (`Assassins Creed/Books`, `/Comics`).
- 147 PDFs, 1 EPUB, 1 DOCX. Novels are text PDFs at fixed sizes (US letter, A4, one A3); comics
  are image-only PDFs. 2.8 GB.

## Platforms and the order they're built

| Piece | What | Order |
|---|---|---|
| Server + browser app | Python server that also serves the web app. Runs on Mac, Linux, Windows; Docker too. Lives on the owner's dedicated media server. | **First (this design's build)** |
| Desktop apps | Mac, Linux, Windows: the web app in a desktop shell (Electron, like Shelf's), plus offline downloads | Second |
| Lite (Android) | The web app full-screen in a tiny shell, like Shelf Lite | Third (small) |
| Android | Full app with offline downloads | Fourth |

Open for later (not decided): whether the full Android app is native like Shelf's, or the web
reader in a richer shell. A native app would mean building the curl reader twice.

## How it's built (decided)

Same stack as Shelf, so its solved problems carry over:

- **Server:** Python 3.14+, FastAPI + uvicorn, SQLite (WAL), `itsdangerous` sessions, `uv`.
  The venv lives on local disk (the NAS share can't hold one) — `run.sh` like Shelf's.
- **Web app:** plain JavaScript modules, no build step, served by the server. Installable (PWA).
- **Config:** `config.toml` (books folder(s), data dir, host, port). Port 4545 by default.
- **Data:** the server's own database, page cache and covers live in a data dir on local disk.
  **The books folder is read-only to Alcove**, except that new uploads are written into it.

### Rendering pages

- **PDF and comics (CBZ, CBR, CB7):** the server renders each page to an image on demand
  (PDF via `pypdfium2`; comics are already images inside an archive) at a width suited to the
  screen, caches it, and the browser curls those images. Zooming fetches a sharper render.
- **EPUB:** the browser lays the book out into screen-sized pages (fits text to the screen, font
  and size adjustable), then curls those.
- **MOBI, AZW3, FB2:** converted to EPUB on the server the first time they're opened; the EPUB is
  cached in the data dir, the original is untouched.
- **TXT:** shown as a simple EPUB-like flowing book.
- **DRM-protected files:** detected and marked "protected" in the library.
- Considered and rejected: rendering PDFs in the browser (PDF.js) — heavy on older phones and Lite;
  rendering EPUBs to images on the server — loses fitting the text to the screen.

## The library (screens)

Chosen from mockups: **"Cover wall."**

- Dark, warm palette (near-black brown background, warm amber accent `#c9a27a`), covers do the
  talking.
- Top: search (books, authors, series).
- A large **Continue reading** panel: cover, title, chapter or page, time/pages left, progress bar.
- Rows of covers: Recently added, then one row per shelf/series/genre. "See all" opens a grid.
- Book page: cover, title, author, series and number, description, Read / Continue, Download,
  Discussion, and (admin) Edit.
- Series show as an ordered shelf (e.g. *Assassin's Creed: Uprising #1–12*).

## The reader

Chosen from working demos: **paper curl** (soft pages that bend under the finger, shadow, fall back
if released halfway) — the StPageFlip library's behaviour.

- Two-page spread on wide screens (laptop, tablet sideways); one page on a phone.
- Turn pages by dragging a corner, swiping, tapping/clicking the edges, or arrow keys.
- Pinch-to-zoom (and ctrl/scroll zoom on desktop) on any page; zoom is how fixed-page PDFs are read
  on phones (agreed).
- Tap the middle for controls: back to library, chapters/contents, bookmarks, a scrubber to jump
  anywhere, and for EPUB: font, text size, margins.
- Reading colour themes: dark (default), sepia, white, black. Separate from the library theme.
- A settings switch for "scroll instead of pages" for those who prefer it.
- **Progress is saved on the server** per person, so you continue on any device.

## Books in and out (replacing Calibre)

- **Calibre import, once:** read `metadata.db` (title, authors, series and index, tags,
  description, publisher, date, language, identifiers, cover). After that Calibre isn't needed.
- **Folder scan:** books in the folder that Calibre didn't know about are picked up too, with
  details from the file itself. Only book formats are shown.
- **Adding (admin):** drag files onto the browser/desktop app. Details are read from the file, gaps
  filled from Open Library; the admin reviews before saving. Saved into the books folder as
  `Author/Title/file`.
- **Editing (admin), right on the book page:** an Edit button on the book page turns its details
  into fields in place — title, authors, series and number, cover (upload or pick from lookup),
  description, tags/shelves, publisher, date, language. Stored in Alcove's database; existing files
  are not renamed or rewritten. (Owner's request, 2026-11-16.)
- **Download:** the original file, for reading elsewhere.

## People

- **Admin** (the owner) and **members**. First person to open a new server makes the admin
  account (as Shelf). Admin adds members.
- Each person: their own progress, bookmarks, and shelves (Want to read, Finished, own shelves).
- **Submit a book:** member uploads a file and **must fill in its details before it can be sent**
  (owner's request, 2026-11-16). The form is pre-filled from the file and Open Library where
  possible. It then waits in the admin's approval queue (admin checks and can correct the details
  and cover, approves or rejects). Nothing appears for others until approved.
- **Request a book:** member asks for a title; others can upvote; admin sees requests ranked; when
  the admin adds the book and links it to the request, the requester is notified.
- **Discussion per book**, from the book page or the reader. Each message is stamped with where the
  writer was (page or %). **Messages from further ahead than you are blurred** until you reach that
  point; tap to reveal anyway. Live updates while open.
- Notifications (in-app): request fulfilled, submission approved/rejected, replies.

## Settings and customization

The owner asked for settings for people and the admin, customization, and a library check, and left
the details to the builder (2026-11-16). Everything a person sets is stored on the server, so it
follows them to every device.

**Your settings** (everyone, from the top bar):
- **Account:** change password; sign out on every device.
- **Reading:** open books in pages (paper curl) or scrolling; reading colours (dark, sepia, white,
  black); page-turn speed (gentle / normal / quick / off); two pages side by side on wide screens on
  or off; left-handed taps (swap which edge goes back); for EPUBs, font, text size and margins.
- **Look:** accent colour (brass by default, plus a handful of curated alternatives); cover size on
  the shelves (small / medium / large); titles under covers on or off; which rows the home screen
  shows and in what order (Recently added, series, genres; hide any).

**Library settings** (admin):
- **People:** add, remove, reset a password, make or unmake admin (never the last admin).
  Sign-up requests appear here once members can ask to join (M5).
- **Books folders:** the folders scanned (editable here; `config.toml` still works and is where
  the first one comes from), how often to scan, rescan now, last scan's result.
- **Plain-text files:** `.txt` files are **not** shown as books unless this is turned on — a stray
  notes or passwords file in the share must not appear for members (spec anti-goal).
- **Library name:** shown in the top bar and sign-in page instead of "Alcove" if set.
- **Online lookups:** allow Alcove to ask Open Library for details and covers (on by default; sends
  titles, authors and ISBNs only).
- Approvals and requests queues (M5).

**Library check** (admin): one page listing what needs attention, each with a direct fix:
- books with no cover → find one online or upload one;
- books with no author, or whose title came from the filename → edit;
- possible duplicates (same title and author, different files) → keep both or remove one;
- gaps in a series (e.g. *Uprising* has #1–7 and #9–12: #8 is missing) → request it or ignore;
- files that couldn't be opened (damaged), and protected (DRM) files;
- folders the last scan couldn't read, and files Calibre lists that aren't on disk.
Anything can be marked "ignore" so the list stays useful.

## Getting book details without Calibre

Alcove reads the folder itself (its own scanner, M1). For details it uses, in order: what the admin
typed, Calibre's import (once), the file's own details, then Open Library (by ISBN found in the
file, else title and author). The admin always sees and can correct the result. A camera barcode
scanner was considered and left out for now.

## Away from home and offline

- Tailscale, as with Shelf. A reverse-proxy mode can come later.
- Desktop and Android apps download books for offline reading; progress syncs when back online.
  The browser and Lite read from the server.

## Milestones for the first build (server + browser)

1. **Library** (done): server, config, accounts, folder scan, Calibre import, covers, cover-wall
   library, book page, search.
2. **Reader for PDF and comics** (done): page images, paper curl, zoom, controls, themes, progress,
   bookmarks, "Continue reading" on the home screen, and **your settings** (account, reading, look).
3. **EPUB and the other formats** (done): EPUB pagination and curl, MOBI/AZW3/FB2/TXT conversion, DRM flag.
4. **Adding and editing books** (done): edit on the book page, uploads, Open Library lookup, shelves,
   **library settings** and the **library check**.
5. **Members:** sign-up requests, submissions (details required) and the approval queue, requests
   with upvotes, per-book discussion with spoiler blur, notifications.

Then: Docker and packaging, desktop apps, Lite, Android.

## Left to the builder

Database schema, API shape, page-image sizes and cache limits, exact animation timings, how EPUB
pagination is done in the browser, file layout of the code, icons and fonts (warm serif for reading,
clean sans for the interface), tests.

## Calls made without asking (check these)

- Port 4545.
- `.txt` files hidden unless the admin turns them on.
- Settings, customization and library check contents (section above).
- Non-book files in the books folder are never shown.
- Uploads go into the books folder as `Author/Title/file`; edits are stored in Alcove's database only.
- PDFs and comics rendered as images on the server; EPUB laid out in the browser.
- Members can't add books directly — everything they submit goes through the approval queue.
- Away from home via Tailscale, as Shelf.
- Edits lock the fields they touch: later scans (a changed file, a changed Calibre library) never
  overwrite what the admin set. Merging two books locks everything on the one kept.
- Library settings saved in the app override `config.toml`; until the admin saves a folder list,
  the config's is used.
- Removing a folder in Library settings removes its books and everyone's progress in them (after a
  warning). A folder that merely disappears from `config.toml` or can't be reached removes nothing.
- Uploads: up to 2 GB per file, saved into the books folder the admin picks ("new books go here"),
  as `Author/Title/file`, never overwriting (a taken name gets " (2)").
- Duplicates are merged into one book (both files kept), never deleted: Alcove doesn't delete files.
- Series gaps count from #1 up to the highest number held.
- "Finished" is the books you read to the end, not a shelf you fill. "Want to read" is always there.
- Open Library fills publisher and language only when it lists exactly one of each (it lists every
  edition's otherwise). Covers are downloaded only from covers.openlibrary.org.
- Demoting or promoting an admin takes effect on their next request without signing them out.
