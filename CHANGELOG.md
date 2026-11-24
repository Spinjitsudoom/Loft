# Changelog

## 0.2.0 (2026-11-24)

- The stacks: every spine looks bound (cloth, raised ribs, a title label) in two colours picked
  from its own cover, and the whole title fits, smaller or on two or three lines. Existing books
  get their colours in the background after updating.
- Checking out: opening a book checks it out to you; finishing it, leaving it for 30 days, or
  Return on its page returns it. It never locks a book: others can still read it, and its page
  says who has it out. Your library card (`#/card`, from Your settings) lists your loans.
- Ratings: one to five stars per person on a book's page, or when you reach its end; everyone
  sees the average. Book lists can be sorted, Highest rated among the choices.
- Go to a page: tap "Page x of y" in the reader (or press G) and type a page.
- Activity (`#/activity`, admins): sign-ins, people, books added, edited and removed, loans,
  ratings, requests, comments and Loft's own work (scans, backups, updates), kept for a year.
- Fixed: long one-word titles pushed pages wider than a phone; Kindle books took their title from
  the file name; a new library's first scan could fail with "database is locked"; the Windows
  tray's Restart could start two servers; an empty library's stacks offered Clear filters.

## 0.1.8 (2026-11-23)

- Windows: Restart to update (and Update in the tray's menu) installs the new version and starts
  Loft Server again; before, a copy installed with the setup closed and stayed closed, still on the
  old version. Loft now starts the setup and keeps running; the setup closes Loft, installs over it
  and starts it again, and writes what it did to `%LOCALAPPDATA%\Loft\update-setup.log`. If the
  setup can't start, Loft stays running as it was.
- What an installed update leaves beside Loft is cleared when it next starts, and a download cut
  short (Loft closed in the middle of it) no longer shows as "downloading" in Library settings.
- Loft's last log lines before it restarts into a new version are no longer lost.

## 0.1.7 (2026-11-23)

- Reading status for every book: Want to read, Not started, Reading, Incomplete (after 15 days
  unread), Abandoned (after 30), Finished; set any by hand from the book's page. Continue reading shows
  only what you're reading; a new Incomplete row on home; the stacks filter by every status.
- Search finds books from the words you remember: in any order, with typos, without apostrophes or
  hyphens, and from the description too; the best matches first.
- Picture books get the Pages settings on their edit page: reading direction (starting at the book's
  own), page order (move, hide, blank pages), splitting pages that hold two printed pages, and the
  wraparound cover. A setting change doesn't download a book again, and your place and bookmarks stay
  on their pages.
- Docker: the image is published as `ghcr.io/spinjitsudoom/loft` (amd64 and arm64) with every
  release, and `compose.yaml` uses it. It makes `/data` Loft's when it starts, then runs Loft as
  `PUID`:`PGID` (1000). Each release has `loft-compose.yaml`, and `loft-zimaos.yaml` to install
  Loft on ZimaOS or CasaOS as a custom app.

## 0.1.6 (2026-11-22)

- Fixed-layout books (picture books, many children's books; EPUB, or Kindle AZW3) are read as pages,
  each exactly as the book designed it: its pictures, fonts and words where they belong, scaled to
  the screen, with the page curl, spreads, Scroll mode, zoom, bookmarks and offline downloads. Such
  as Geronimo Stilton's *Wedding Crashers*, which showed as stray lines of text on empty pages.
- Fonts stored scrambled in EPUBs (the standard font obfuscation, not DRM) are unscrambled.

## 0.1.5 (2026-11-21)

- Backups: Loft backs up its library by itself (Library settings, Backups): the database, covers
  chosen by hand and books waiting for approval, in one zip. Every day, every week or off; to a
  folder of the admin's choosing; keeping a week of dailies then eight weeklies, or the newest 5,
  10 or 30. Back up now, Download and Restore (which backs up what's there first). Admins are told
  when a backup can't be made.

## 0.1.4 (2026-11-21)

- On Windows, opening `loft-server.exe` directly (by double-clicking it, or from a shortcut made
  by the first 0.1.3 setup) starts Loft Server in the tray instead of a console window. Typed in
  a terminal, it still runs there.
- A Windows server installed by the first 0.1.3 setup updates itself to this one and ends up in
  the tray.
- What's new opens in Loft instead of on GitHub: a pop-up after each update (once), and from Your
  settings and Library settings any time. Before updating, Library settings shows the new
  version's notes. Each release carries them as `whatsnew.json` (from `src/loft/web/whatsnew.json`).

## 0.1.3 (2026-11-21)

- The Windows server has a setup (`loft-server-<version>-windows-x64-setup.exe`): no administrator
  needed, Start menu shortcuts, and an uninstaller that leaves the library's data alone. Installed
  copies update themselves by running the next setup. The zip is still there for anyone who'd
  rather unpack it.
- Loft Server for Windows runs in the background, with an icon in the notification area (like
  Shelf Server): Open Loft, the address other devices use, Update, Start with Windows, the data
  folder, Restart and Quit. No console window; the server's messages go to
  `%LOCALAPPDATA%\Loft\server.log`, and settings to `%LOCALAPPDATA%\Loft\config.toml`.

## 0.1.2 (2026-11-20)

- Loft keeps itself up to date: the standalone server downloads new versions and an admin chooses
  when to restart into them; the desktop app (Windows, Linux AppImage) and Loft Lite download them
  and ask; everything else is told a new version is out.
- The folder inside each server download is now just `loft-server`.

## 0.1.1 (2026-11-20)

The first release. Downloads for Windows, macOS, Linux and Android, and what's in it:
[docs/releases/0.1.1.md](docs/releases/0.1.1.md).

- Standalone server for Windows, macOS (Apple silicon) and Linux, needing nothing else installed.
- Desktop app for Windows, macOS and Linux; Loft Lite for Android.
- Previous and Next on a book's page.
- New books' missing details are filled in automatically from sure matches (and can be undone).
- Hardcover and ISBNdb as lookup sources.
- Renamed from Alcove to Loft.
