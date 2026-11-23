# Loft

A self-hosted ebook library with pages that turn like paper. Your books stay where they are;
Loft reads them, shelves them, and lets everyone you invite read them on a phone, tablet or
computer.

**[Website and interactive demo →](https://spinjitsudoom.github.io/my-portfolio/loft.html)**

- **A library that looks like one.** A cover wall at home, and **the stacks**: every book standing
  spine-out on bookcases, shelved by series, section or author.
- **A reader that turns like paper.** Comics and PDFs page by page, EPUB, Kindle and FB2 laid out
  to your font and size; two pages side by side on wide screens; manga right to left.
- **For several people.** Each with their own place in each book, bookmarks and shelves. Members can
  submit books (you approve them), ask for books, and talk about each one without spoilers.
- **Offline.** Download a book and read it with no connection; your place catches up later.

## Install

### Download

Each [release](https://github.com/Spinjitsudoom/Loft/releases/latest) has the server for Windows,
macOS and Linux (nothing else to install: unpack it, start `loft-server`, open
`http://localhost:4545`; on Windows there's also a setup, `loft-server-…-setup.exe`: Loft Server then
runs in the background with an icon by the clock, and starts with Windows), the desktop app for each, and Loft Lite
for Android. The release page says
what each system asks the first time.

### With Docker (any Linux server, NAS or Raspberry Pi)

Change the books path in `compose.yaml`, then:

```bash
docker compose up -d
```

and open `http://<that computer>:4545`. More in [docs/docker.md](docs/docker.md).

### Directly (Linux and macOS)

Loft needs [uv](https://docs.astral.sh/uv/) (it fetches the right Python itself). For CBR comics,
install `unar` (or `unrar`, `7z` or `bsdtar`).

```bash
cp config.example.toml config.toml     # set books_dirs to your books folder
bash run.sh
```

Then open `http://localhost:4545`. To keep it running and start it with the computer, see
[deploy/loft.service](deploy/loft.service).

**The first person to open a new Loft makes the admin account.** After that, the admin adds
people in **Library settings → People**, or lets them ask to join from the sign-in page.

## On Android

**Loft Lite** (`android-lite/`) is the web app in a small Android shell: it asks once for the
server's address, then opens straight onto your library. It keeps the app's own files on the phone,
so with no connection it still opens onto your downloaded books (even over plain http), keeps the
screen on while you read, lets you pick books from the phone to add or send, and saves files to
Downloads. Build it with `bash android-lite/build.sh` (needs the Android SDK and a JDK; see the
script), then install `android-lite/build/loft-lite.apk`.

## On a computer

**Loft for Windows, macOS and Linux** (`desktop/`) is the web app in its own window (Electron),
like Shelf's. It asks once for the server's address, opens straight onto it after that, and from
the second start opens with no connection too, onto your downloaded books. **Change server** is
in its menu (Alt shows it) and in Your settings. To run it: `cd desktop && npm install &&
node node_modules/electron/install.js && npm start`; to package it: `npm run dist:linux` (or
`dist:win`, `dist:mac`). The standalone server is built with
`uv run --with pyinstaller python packaging/build_server.py`; pushing a `v*` tag builds everything.

## Updates

Loft checks for a new version once a day (turn it off in **Library settings → Loft version**).
- **The standalone server** downloads it, then admins are told it's ready; **Restart to update**
  swaps it in (the old version is kept beside it as `loft-server.previous`).
- **Docker and source installs** are told a new version is out (update them the way you installed them).
- **The desktop app** on Windows and as an AppImage downloads it and asks to restart; on macOS, and
  from a .deb or .rpm, it offers the download page.
- **Loft Lite** downloads it and asks; Android shows its own install screen to confirm.

Only Loft's release page on GitHub is asked; nothing about your library is sent. Releasing: push a
`v*` tag (the Release workflow drafts it), run `bash packaging/attach-apk.sh <tag>`, then publish.

## Away from home

Loft isn't meant to face the internet. Use [Tailscale](https://tailscale.com): install it on the
server and your devices, and open `http://<server's Tailscale name>:4545`. For https (which lets a
phone keep the app itself for opening offline), run `sudo tailscale serve --bg 4545` and use
`https://<server>.<tailnet>.ts.net`.

## Your books

- Formats: EPUB, PDF, CBZ / CBR / CB7 comics, Kindle (MOBI, AZW, AZW3) and FB2. Plain-text files only
  if you turn them on (a stray notes file shouldn't appear as a book). Protected (DRM) books are
  listed but can't be opened.
- Loft **never renames, moves or rewrites your files.** Details you edit are kept in Loft's own
  database and survive rescans. Books added in Loft are saved into the folder you choose, as
  `Author/Title/file`.
- Calibre libraries are recognised: titles, authors, series and covers come from them once.

## Finding books

- **Home**: what you're reading, your shelves, what's new, and rows for series and sections.
- **Reading status**, each person's own for each book: Want to read, Not started, Reading,
  Incomplete, Abandoned or Finished. Loft keeps it up to date as you read (Incomplete after 15 days
  unread, Abandoned after 30, Finished at the last page); set any of them by hand on the book's page.
  Continue reading shows only what you're reading, and books you stopped get an Incomplete row.
- **The stacks** (the shelf icon): bookcases shelved by **Series**, **Sections** or **Authors**
  (by surname, with name cards between them), narrowed by reading status, section, author or
  format. Tap a spine and the book slides out. Switch to **Covers** to see them face-out.
- **Sections** are the library's categories. Loft suggests them from your books' tags; arrange
  them in **Library settings → Sections** (a book stands in the first section it matches).
- **Search** finds books from the words you remember, in any order: in titles, series, authors, tags
  and descriptions, forgiving typos, apostrophes and hyphens, with the best matches first.

## Reading

- Tap the middle for controls; the edges turn pages (swap them for left hands in Your settings).
- PDFs and comics: zoom, two-page scans split into pages, wraparound covers, **Right to left
  (manga)**, and **Arrange pages** (move, hide, or add blank pages; the file is never changed),
  all on the book's edit page.
- EPUB and the others: font, size and margins in the reader's settings.
- Fixed-layout books (picture books and many children's books, EPUB or Kindle) are read as pages,
  each as the book designed it, with its pictures and fonts: the page curl, two pages side by side
  when there's room, zoom, and downloads. Their text size can't change; zoom instead. Pages are
  shown in a sealed frame: nothing in a book runs, and nothing outside it is loaded. Their edit page
  has the same page settings as comics: reading direction (starting at the book's own), **Arrange
  pages**, splitting pages that hold two printed pages (for books made from scans), and the
  wraparound cover.
- Your place and bookmarks follow you between devices.

## Adding and editing books (admins)

- **+ → Add books**: drop files, check the details (from the file, and from Google Books, Open
  Library or AniList with **Look up details**), save.
- **Edit** on any book's page: details, cover, and for page books their layout.
- **Library check** (Library settings): books without covers, authors or tags, damaged or
  protected files, possible duplicates, gaps in series. For books with no tags or no cover,
  **Look them up one by one** goes through them: each is looked up (its title tidied first, and by
  title alone if the author finds nothing), you pick the match, and only what's missing is filled in.
- **Google Books** needs a free key (Library settings): it knows the editions themselves, like
  English manga volumes with their covers and ISBNs.

## People

- **Members** see the whole library, read, keep shelves, and:
  - **submit books**: they fill in the details and an admin approves or declines (**+ → Approvals**);
  - **ask for books**: others vote, and everyone who asked is told when it's added;
  - **talk about a book** on its page or in the reader. Each message shows where its writer was;
    one from further on than you is blurred until you get there (tap to read it anyway).
- **Notifications** (the bell): replies, books you asked for arriving, and for admins, what's waiting.

## Downloads

**Download** on a book's page keeps it on that device to read with no connection (comics and PDFs
as page images, EPUBs and the like with their pictures). They're under **On this device** at home
and in **Your settings → Downloads**. Progress and bookmarks made offline are sent when the server
is back; a book that changes on the server downloads again by itself.

## Backups

Loft backs up its library by itself (**Library settings → Backups**): everything a rescan can't
bring back, meaning accounts, reading progress, shelves, bookmarks, edits and filled-in details,
covers chosen by hand, and books waiting for approval. Each backup is one zip
(`loft-YYYY-MM-DD-HHMMSS-<code>.zip`).

- **How often:** every day (the default), every week, or off.
- **Where:** `backups/` in Loft's data folder until you pick another folder. Another drive is
  safer. Not a books folder (Loft only reads those) and not inside Loft's data folder. Loft leaves
  a small `.loft-backups` file there; if the drive isn't connected, Loft doesn't back up anywhere
  else, and admins are told.
- **How many:** a week of daily backups then one a week for eight weeks (the default), or the
  newest 5, 10 or 30. Only files named like Loft's backups are ever removed.
- **Back up now**, **Download** and **Restore**. Restoring first backs up what's there, so it can be
  undone the same way, and everyone signs in again afterwards. If it can't finish, nothing changes.
- Several Lofts can share a backup folder: each prunes only its own (their names end in a short
  code for the Loft that made them), and any of them can be restored.

Backups hold the lookup keys saved in Library settings, but not what signs people in.

## Where things live

Loft's own data (`~/.local/share/loft`, or `/data` in Docker): `loft.db` (accounts, the
library, progress, settings), `covers/`, `pages/` (page images, pruned to `page_cache_mb`), and
`uploads/` (books waiting to be saved or approved), and `backups/` unless they go elsewhere.

## Development

```bash
bash run.sh                     # the server, on port 4545
bash test.sh -q                 # the tests
```

`run.sh` and `test.sh` keep the Python environment on local disk (`~/.local/share/loft/venv`),
since a network share can't hold one. The design and the decisions made along the way are in
`docs/superpowers/specs/`.

## Licence

AGPL-3.0-or-later. See [LICENSE](LICENSE).
