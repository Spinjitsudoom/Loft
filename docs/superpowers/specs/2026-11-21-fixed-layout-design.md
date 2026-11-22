# Fixed-layout books

## Why

*Wedding Crashers* (Geronimo Stilton, AZW3) opens in Loft as a few loose lines of text on empty
pages. It's a fixed-layout book: each page is a full-page picture (a CSS background) with words
placed on it at exact positions in the book's own fonts, at 706×1024. Loft's reader treats every
EPUB and Kindle book as flowing text: it keeps the words, and deliberately never uses a book's own
stylesheets, so the pictures, positions and fonts are lost. The same happens to every fixed-layout
book (picture books, many children's books, some comics and cookbooks), EPUB or Kindle.

## Goals

- A book that says it is fixed-layout is read as pages, each exactly as the book designed it (its
  pictures, fonts and positions), scaled to fit the screen.
- Turned like a comic: the page curl, two pages side by side when there's room (unless the book
  says no spreads), the cover on its own, right-to-left books turning the other way, and Scroll
  mode as a column of pages.
- Zoom in on a page (double-tap, pinch, ctrl+wheel) as for comics.
- Progress, bookmarks, the contents list, discussion and downloads (offline reading) work as for
  other books.
- EPUB and Kindle (AZW3, which unpacks to EPUB) alike.

## Non-goals

- Changing the text size or font of a fixed-layout book (the page is a picture; zoom instead).
- Scripts in books (some fixed-layout books animate or read aloud with them): never run.
- Books that mix fixed and flowing sections page by page: the whole book follows its own
  declaration.
- KFX, MOBI metadata, `.prc`: separate work.

## Anti-goals

- A book's HTML or CSS must never run code, reach anything outside the book, or see Loft's
  cookies or pages: book files can contain anything.
- Flowing books must not change.

## Approaches

1. **Each page in a locked-down frame (chosen).** The server sends each page as one safe,
   self-contained HTML document: the book's own CSS inlined after cleaning, its markup cleaned,
   every reference rewritten to the book's own pictures and fonts on Loft's server, and anything
   else removed. The reader puts it in a sandboxed iframe (no scripts) scaled to the page's size,
   inside the same page-curl reader comics use. Works on every device Loft runs on.
2. **Only the page pictures.** Lose the words, which in this book aren't in the pictures.
3. **Render pages to images on the server with a headless browser.** Identical everywhere, but
   needs a whole browser on the server: too heavy for the Windows tray app and Docker.

## Design

- **Detecting:** an EPUB is fixed-layout when its package says `rendition:layout` is
  `pre-paginated`, or carries the older `<meta name="fixed-layout" content="true"/>`. AZW3 files
  unpack to EPUB and are detected the same way. Found when the book is opened; nothing at scan time.
- **Page sizes:** each page's `<meta name="viewport" content="width=…, height=…">`; else the book's
  `rendition:viewport` or `original-resolution`; else an SVG page's `viewBox`; else 2:3.
- **The outline** (`GET /api/files/{id}/flow`) gains `"fixed": {"sizes": [[w, h], …], "spread":
  true|false}` and `"rtl"` for fixed-layout books (`spread` false when the book says
  `rendition:spread` `none`; `rtl` from the spine's `page-progression-direction`). Each spine item
  is a page, so the existing chapter list is the page list.
- **A page** is served by the existing `GET /api/files/{id}/chapters/{n}`, which for a fixed-layout
  book returns a whole document instead of flowing text:
  - CSS: the page's linked stylesheets and `<style>` blocks, inlined. `url(…)` kept only when it
    resolves to a picture or font inside the book (rewritten to `/api/files/{id}/res/…`), else
    dropped; `@import` resolved inside the book or dropped; nothing that can run (`expression`,
    `behavior`, `-moz-binding`, `javascript:`).
  - Markup: the book's body with its `id`, `class` and `style` kept (the CSS needs them), without
    scripts, forms, frames, objects, event handlers or links outside the book; SVG kept for the
    subset pages use to show pictures (`svg`, `g`, `image`, `rect`, `path`…) with `href`s rewritten
    the same way.
  - The body's own `id` and `class` (CSS often hangs page pictures on them) are kept.
  - A `Content-Security-Policy` both as a header and as a `<meta>` in the document:
    `default-src 'none'; img-src 'self' blob: data:; font-src 'self' blob: data:; style-src
    'unsafe-inline'`.
- **Fonts:** `/api/files/{id}/res/…` also serves the book's fonts (`.otf`, `.ttf`, `.woff`,
  `.woff2`) with their media types and `nosniff`.
- **The reader:** a `FixedReader` (extends the comics `Reader`) chosen when the outline has
  `fixed`. Each leaf holds an iframe with `sandbox="allow-same-origin"` (no `allow-scripts`, so
  nothing runs; same origin so the book's pictures load with the reader's sign-in) and
  `pointer-events: none` (taps reach the reader), at the page's own size and scaled with a CSS
  transform to the leaf. Its document is fetched (or read from the download) and set as
  `srcdoc`. Pages near the current one are loaded, as comics do; far ones are emptied to save memory.
- **Zoom** shows the current page alone, larger, to pan and pinch, with next/previous.
- **Progress and bookmarks** are by page, as for comics (`page`, `pages` = page count), with a
  `locator` of `{chapter: page}`, so progress saved while it was read as flowing text still
  finds its page.
- **Downloads** keep each page's document and the pictures and fonts it names, as flowing books
  keep chapters, so fixed-layout books read offline.

## Decided while writing this up

- CSS is cleaned with a real CSS parser, `tinycss2` (small, pure Python, a new dependency), not
  regular expressions: CSS has comments, escapes and strings that hide `url(` from a pattern.
- Markup is cleaned with `nh3` (already used), with a wider allow-list than flowing text; the
  rewriting of `src`/`href` to the book's resources reuses Loft's existing rewriter.

## Left to the builder

The exact CSS and SVG allow-lists (as small as the books need), how many pages stay loaded, and
the zoom's look, in the reader's existing style.
