# Alcove

A self-hosted ebook library with pages that turn like paper. Your books stay where they are;
Alcove reads them, shelves them, and lets everyone you invite read them on a phone, tablet or
computer.

- **A library that looks like one.** A cover wall at home, and **the stacks**: every book standing
  spine-out on bookcases, shelved by series, section or author.
- **A reader that turns like paper.** Comics and PDFs page by page, EPUB, Kindle and FB2 laid out
  to your font and size; two pages side by side on wide screens; manga right to left.
- **For several people.** Each with their own place in each book, bookmarks and shelves. Members can
  submit books (you approve them), ask for books, and talk about each one without spoilers.
- **Offline.** Download a book and read it with no connection; your place catches up later.

## Install

### With Docker (any Linux server, NAS or Raspberry Pi)

Change the books path in `compose.yaml`, then:

```bash
docker compose up -d
```

and open `http://<that computer>:4545`. More in [docs/docker.md](docs/docker.md).

### Directly (Linux and macOS)

Alcove needs [uv](https://docs.astral.sh/uv/) (it fetches the right Python itself). For CBR comics,
install `unar` (or `unrar`, `7z` or `bsdtar`).

```bash
cp config.example.toml config.toml     # set books_dirs to your books folder
bash run.sh
```

Then open `http://localhost:4545`. To keep it running and start it with the computer, see
[deploy/alcove.service](deploy/alcove.service).

**The first person to open a new Alcove makes the admin account.** After that, the admin adds
people in **Library settings → People**, or lets them ask to join from the sign-in page.

## Away from home

Alcove isn't meant to face the internet. Use [Tailscale](https://tailscale.com): install it on the
server and your devices, and open `http://<server's Tailscale name>:4545`. For https (which lets a
phone keep the app itself for opening offline), run `sudo tailscale serve --bg 4545` and use
`https://<server>.<tailnet>.ts.net`.

## Your books

- Formats: EPUB, PDF, CBZ / CBR / CB7 comics, Kindle (MOBI, AZW, AZW3) and FB2. Plain-text files only
  if you turn them on (a stray notes file shouldn't appear as a book). Protected (DRM) books are
  listed but can't be opened.
- Alcove **never renames, moves or rewrites your files.** Details you edit are kept in Alcove's own
  database and survive rescans. Books added in Alcove are saved into the folder you choose, as
  `Author/Title/file`.
- Calibre libraries are recognised: titles, authors, series and covers come from them once.

## Finding books

- **Home**: what you're reading, your shelves, what's new, and rows for series and sections.
- **The stacks** (the shelf icon): bookcases shelved by **Series**, **Sections** or **Authors**
  (by surname, with name cards between them), narrowed by reading status, section, author or
  format. Tap a spine and the book slides out. Switch to **Covers** to see them face-out.
- **Sections** are the library's categories. Alcove suggests them from your books' tags; arrange
  them in **Library settings → Sections** (a book stands in the first section it matches).
- **Search** finds titles, authors, series and tags.

## Reading

- Tap the middle for controls; the edges turn pages (swap them for left hands in Your settings).
- PDFs and comics: zoom, two-page scans split into pages, wraparound covers, **Right to left
  (manga)**, and **Arrange pages** (move, hide, or add blank pages; the file is never changed),
  all on the book's edit page.
- EPUB and the others: font, size and margins in the reader's settings.
- Your place and bookmarks follow you between devices.

## Adding and editing books (admins)

- **+ → Add books**: drop files, check the details (from the file, and from Google Books, Open
  Library or AniList with **Look up details**), save.
- **Edit** on any book's page: details, cover, and for page books their layout.
- **Library check** (Library settings): books without covers or authors, damaged or protected
  files, possible duplicates, gaps in series.
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

## Where things live

Alcove's own data (`~/.local/share/alcove`, or `/data` in Docker): `alcove.db` (accounts, the
library, progress, settings), `covers/`, `pages/` (page images, pruned to `page_cache_mb`), and
`uploads/` (books waiting to be saved or approved). Back up the database and covers.

## Development

```bash
bash run.sh                     # the server, on port 4545
bash test.sh -q                 # the tests
```

`run.sh` and `test.sh` keep the Python environment on local disk (`~/.local/share/alcove/venv`),
since a network share can't hold one. The design and the decisions made along the way are in
`docs/superpowers/specs/`.

## Licence

AGPL-3.0-or-later. See [LICENSE](LICENSE).
