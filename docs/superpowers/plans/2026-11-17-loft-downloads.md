# Downloads (offline reading) Implementation Plan

> For agentic workers: executed inline (superpowers:executing-plans). Ledger:
> `.superpowers/sdd/2026-11-17-loft-downloads/progress.md`.

**Goal:** a book's Download button keeps it inside Loft on this device (like Shelf), so it reads
with no connection; progress and bookmarks made offline reach the server later.

**Architecture:** everything downloaded lives in IndexedDB (works over plain http, unlike service
workers). A new `web/js/offline.js` owns the store, the download queue, the offline write queue and
"is the server there?". The readers ask it first for page images, chapters and chapter pictures. A
service worker keeps the app's own files so the app opens with no connection where browsers allow
one (https or localhost). No server changes except serving `sw.js` without caching.

**Owner's request (2026-11-17):** "can downloading a book be kept within the app like with shelf";
then "lets do downloads and members". Design as proposed in conversation and accepted.

## Global constraints
- Book files on the server are never changed. Nothing in this plan writes to the books folder.
- Downloads belong to the signed-in account on that browser (records carry user_id; others never
  see them). Signing out keeps them.
- Every storage call in try/catch: private windows or full disks must not break reading online.
- Copy: plain words, sentence case; buttons say what happens ("Download", "Remove download",
  "Save file").

## Store (IndexedDB "loft-offline", version 1)
- `books` { key: `${user}:${bookId}`, user, bookId, fileId, kind: "pages"|"flow", version,
  width, book (the /api/books/{id} JSON), manifest, done, total, size, savedAt, complete }
- `blobs` { key: `${fileId}:${what}` } what = `p${i}` page image, `c${n}` chapter text,
  `r${path}` chapter picture, `cover`; value { key, fileId, blob }
- `outbox` (autoIncrement) { user, method, path, body, at } — progress and bookmark writes made
  while the server couldn't be reached, sent in order when it can.

## Tasks
1. **offline.js store + download engine.** open/put/get helpers; `status(bookId)`;
   `download(book)` (picks the file the reader would open; pages: manifest then every page at one
   width — the device's portrait page width × DPR, snapped to 600/900/1200/1800 — 3 at a time;
   flow: outline, each chapter, every `/api/files/{id}/res/...` picture in them; cover); progress
   events (`downloads-changed`); cancel; remove; removeAll; list for the account; total size;
   resume unfinished downloads at start; `navigator.storage.persist()` on first download.
2. **Readers read from the store.** renderReader: book/manifest/bookmarks fall back to the stored
   copy (and use it when the book is downloaded); Reader.src → stored page URL; zoom too;
   FlowReader.chapter → stored text with picture URLs swapped for stored ones. Progress PUT and
   bookmark add/delete go through the outbox when the server can't be reached; replayed in order.
3. **Offline mode.** main.js: if /status can't be reached (network error, not 401) → offline:
   home shows only "On this device", book pages come from the store, the reader works, everything
   else says it needs the server. A small banner says so. When the server answers again: replay
   the outbox, leave offline mode quietly.
4. **Book page + home + settings UI.** Book page: Download / "Downloading 34%" (Cancel) /
   "Downloaded · 182 MB" (Remove download); file buttons become "Save file EPUB · 3 MB". Home:
   "On this device" row when there are downloads. Your settings: Downloads section (each book with
   size, Remove; total; Remove all; space the browser allows).
5. **Keeping downloads current.** At start (online), each downloaded book whose server version
   differs (file replaced, layout/order changed) is downloaded again in the background.
6. **App shell offline.** `web/sw.js` (network first, cache fallback, never /api) registered only
   in secure contexts; WebFiles serves it uncached.

## Verify (headless Chromium, scratch server :4548, shot.py; offline via CDP
`Network.emulateNetworkConditions`)
- Download a comic and an EPUB; size shown; reload → still downloaded.
- Go offline: home shows On this device; open both; turn pages; pictures in the EPUB show.
- Read offline, come back online → server progress updated with the offline time.
- Change the comic's layout → after reload online it re-downloads.
- Remove → gone from store and home.
- Full pytest suite still green.
