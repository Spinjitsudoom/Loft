# Automatic backups

## Why

Loft had no backups. The test server's library survived only because its data folder was never
deleted; moving it to the Windows server took a hand-made copy. A disk failure or a mistake on the
real server would lose accounts, reading progress, shelves, bookmarks, edits and filled-in details,
none of which a rescan can rebuild. The admin should choose how backups work.

## Goals

- Backups made by themselves, on the admin's schedule: **daily** (the default), **weekly**, or **off**.
- The admin chooses **where** they go (another drive is safer). Until then: `backups` in Loft's data folder.
- The admin chooses **how many to keep**: Shelf's way (the default: one a day for the last week, then
  one a week for the eight weeks before) or the newest 5, 10 or 30.
- **Back up now**, **Download** and **Restore** in Library settings, as in Shelf.
- Restoring first backs up what's there now, so a wrong restore can be undone the same way.

## Non-goals

- Restoring a backup made on another computer whose books are at other paths (as for the move to
  Windows). A restore is for the server that made it.
- Uploading a backup file through the app to restore it.
- Several backup folders, or a time of day.

## Anti-goals

- A backup must never be half-written where a good one was expected, and never be inside a books
  folder (Loft only reads those, except uploads).
- A failing backup must not fail silently.

## Approaches

1. **Shelf's backups, carried over and widened (chosen).** Shelf's `backups.py`: SQLite's online
   backup (whole even while Loft is busy), written to a temporary name then renamed, a retention
   rule, a background loop, a restore that backs up first. Widened for Loft with a schedule
   choice, a keep choice, and the files beside the database a rescan can't rebuild. Proven in
   Shelf; one module.
2. **Copy the whole data folder.** Simple, but copying a live SQLite file can catch it mid-write,
   and it drags along hundreds of MB of page images Loft remakes anyway.
3. **Leave it to the operating system** (File History, cron, Docker volumes). Nothing for the admin
   to choose in Loft, and differs on every system: not what was asked.

## Design

- **What's in a backup:** one zip, `loft-YYYY-MM-DD-HHMMSS-<id>.zip` (`<id>`: six hex digits from
  this server's secret, so Lofts sharing a folder prune only their own; any can be restored), holding `loft.db` (an online backup
  copy), `covers/` (covers chosen by hand exist only there) and `uploads/` (books sent but not yet
  approved). Not the page and flow caches (remade when needed), and not `secret_key` (a backup file
  must not be enough to sign in as anyone). The library settings in the database include saved
  lookup keys, so the backups folder should be one only the admin can read.
- **Settings** (Library settings → Backups; stored with the other library settings):
  `backup_every` = `day` | `week` | `off`; `backup_dir` = a full path, or empty for the data folder's
  `backups`; `backup_keep` = 0 (Shelf's way) or 5, 10, 30. A folder must exist, be writable, and not
  be inside (or contain) a books folder, nor be inside Loft's data folder other than its `backups`.
  Choosing a folder leaves a `.loft-backups` mark in it; a chosen folder without the mark (an
  unplugged drive's empty mount point) is never written to.
- **When:** a background loop like the update check looks every hour; a backup is due when the
  newest is 23 hours old (daily) or 7 days less an hour old (weekly). The first look is two minutes
  after Loft starts. Off makes none, and prunes none.
- **Keeping:** after each scheduled or Back up now backup, older ones are pruned by the rule. Days
  and weeks are fixed on the calendar (counted back from now, each day's backup pushed the last
  out of the first week's place). A backup's date comes from its name, which copying keeps. The
  newest is never removed. Backups made before a restore (`…-before-restore.zip`) are outside the
  rule and kept 30 days. Only files named like Loft's backups are ever touched.
- **Failing:** a failed backup is logged and admins get one notification ("Loft couldn't back up:
  …") until one succeeds again. The panel shows when the last backup was made, or why it failed.
- **Restoring:** checks the zip (a whole database with Loft's tables) before touching anything,
  backs up what's there now, copies the database in with SQLite's backup, replaces `covers/` and
  `uploads/`, clears the page and flow caches, adds any columns added since, and starts a rescan. The
  backup settings stay as they are now (they say where the backups are, including the one just made).
  Everyone, the admin included, signs in again (every account's sign-in version moves past any
  before: account numbers are reused, so an old sign-in could otherwise become someone else's).
  The folders are swapped before the database, and put back if anything fails: all or nothing.
- **Routes** (admins only): `GET /api/backups` (settings, list, last result), `POST /api/backups`
  (back up now), `GET /api/backups/{name}` (download), `POST /api/backups/{name}/restore`. The
  settings save through `PATCH /api/library`, like every other library setting.

## Left to the builder

The wording on the panel, how sizes and dates show, and the exact layout, in Loft's style and like
Shelf's backups list.
