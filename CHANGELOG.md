# Changelog

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
