# Page settings for picture books: design

## Why

Since 0.1.6, fixed-layout books (picture books, Kindle comics; EPUB or AZW3) are read as pages, like comics and
PDFs. But the book's edit page still has no **Pages** section for them, so an admin can't fix one that reads
wrong: the wrong direction, spreads that pair up wrong, a stray page, or a Kindle comic made from scans whose
pictures hold two printed pages each.

## Goals

The four settings comics and PDFs have, for fixed-layout books too, saved the same way (per file, at once,
admin only), and taking effect in the reader, Scroll mode, zoom and downloads:

1. **Reading direction:** left to right, or right to left. Starts at the book's own direction (its
   `page-progression-direction`), not always left to right.
2. **Page order:** the existing **Arrange pages** screen: move pages, hide them, put blank pages in.
3. **Two printed pages on one page:** split the wide pages in two.
4. **Wraparound cover:** when splitting, a wide first page is a back-and-front cover: front first (default) or
   as the book has it.

## Non-goals

- Changing the book file. As for comics, the settings sit beside it.
- Settings for flowing (non-fixed) EPUBs. They have no pages to arrange.

## Anti-goals

- A setting change makes a downloaded book download again. A picture book's pages don't change when it's
  rearranged, only which ones show where. So downloads stay, and only the order is updated.
- Saved reading places and bookmarks jump to a different page after a setting change.
- Loading a book's page (not its edit page) gets slower. The edit page finds out whether a file is fixed-layout;
  the book page doesn't.

## Approaches considered

1. **Reuse the comics page plan (chosen).** Comics already work out "which source page, or which half of it,
   each reader page shows", through split, wraparound, direction, then the admin's order and hidden pages
   (`pages.split_plan`, `pages.arrange`). A fixed-layout book gets the same plan, with its page sizes from the
   book instead of from images. The reader then shows source page *n* in its frame, or half of it, or a blank.
   One set of rules, already tested, for every book with pages.
2. **Separate settings for picture books.** Its own storage and its own arranger. Double the code for the same
   behaviour, and two sets of rules that drift apart.
3. **Only direction and page order.** Less work, but leaves Kindle comics made from scans with their spreads
   uncut, which is what the user asked for too.

## How it works

### Server

- `pages.manifest` accepts a fixed-layout flow file. Its source pages are the book's pages, and their sizes
  come from the book (`FlowBook.fixed.sizes`). It isn't a scan, so **Automatic never splits it**; the admin
  chooses "Split them". The direction is the admin's choice if made, else the book's own.
- `set_layout` and `set_arrangement` accept fixed-layout files, and still refuse flowing books ("Only books with
  pages have page layouts"). They store into `book_files.layout`, as for comics.
- The book's outline (`GET /api/files/{id}/flow`), for a fixed-layout book, also carries the plan:
  - each reader page's source page and half;
  - each reader page's size (half the width for a half);
  - the resolved direction;
  - the contents mapped to reader pages;
  - its layout settings and whether it's arranged (for the edit page).

  `version` stays the file's version, so page addresses and downloads don't change with the layout. A separate
  `layout_v` changes with it.
- `GET /api/files/{id}/manifest` works for fixed-layout files too, so **Arrange pages** loads as it does for
  comics. `piece` (thumbnail images) isn't used for them.

### Reader (`fixed.js`, `fixedfit.js`)

- Reader page *i* shows plan entry *i*:
  - a whole source page: its frame, as now;
  - a half: the frame at the source page's full size, clipped to its left or right half and scaled to fill;
  - a blank: a plain white page the size of the one before it.
- Documents are still fetched and kept per **source** page (`pageUrl(file, source, outline)`). The same
  download serves any arrangement.
- Places: the saved locator names the source page and the half (`{chapter: source, progress: 0 | 0.5}`).
  Opening finds that page in the current plan, or the next one shown if it's now hidden, so a place survives a
  layout change. Places saved before (page = chapter) still open where they were.
- Zoom shows halves and blanks the same way.

### Downloads (`offline.js`)

When the outline's `layout_v` differs from the download's, the stored outline is refreshed. No pages are
downloaded again.

### Edit page (`book.js`)

- For each EPUB, AZW3, AZW or MOBI file, the edit page asks for the file's outline. If the file is fixed-layout,
  the Pages section shows for it, with:
  - **Reading direction:** Left to right / Right to left.
  - **Two printed pages on one page:** Don't split (default) / Split them. There's no "Automatic", because it
    would mean the same as Don't split here. Hint: "For books made from scans: cuts only the wide pages in two."
  - **Wraparound cover (back and front on one page):** Automatic / Front first / As the book has it.
  - **Page order:** the note and **Arrange pages**, as for comics.
- Saves work exactly as for comics.

### Arrange pages (`arrange.js`)

For a fixed-layout file, each thumbnail is the page's own frame (sandboxed, no scripts, as in the reader),
scaled down and clipped for halves, and filled only when it scrolls into view. Everything else (choosing,
moving, hiding, blanks, undo, reset) is unchanged.

## Tests

- Python:
  - the manifest for a fixed-layout EPUB (whole pages; split halves and their sizes; wraparound; the book's own
    right-to-left direction and the admin's override; order, hidden and blank pages);
  - `set_layout` and `set_arrangement` accept fixed-layout and refuse flowing EPUBs;
  - the outline carries the plan;
  - `version` doesn't change with the layout, and `layout_v` does.
- JS: mapping a place to a reader page and back (through halves, hidden pages, older places), and the
  half-page clipping sums.
- Browser, on *Wedding Crashers* on the test server:
  - each setting changes the reader;
  - a hidden page is skipped;
  - a blank shows;
  - right to left turns the other way;
  - the place is kept across changes;
  - a downloaded copy isn't downloaded again after a change;
  - Arrange pages shows real page thumbnails.

## Left to the builder

Exact field names in the outline, the CSS for clipped halves and thumbnails, and wording beyond what's given
above, in the style of the existing edit page.
