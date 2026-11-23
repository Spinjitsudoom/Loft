# Page settings for picture books: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fixed-layout EPUB and Kindle books get the comics **Pages** settings: reading direction, page order,
splitting two-page pages, and the wraparound cover. These work in the reader, zoom, Scroll mode and downloads.

**Architecture:** `pages.manifest` learns fixed-layout flow files. Their source pages and sizes come from
`FlowBook.fixed`, and the existing `split_plan` and `arrange` give the page plan. The `/flow` outline of a
fixed-layout book carries that plan. `FixedReader` shows plan entry *i* in one of three ways: a source page's
frame, half of it (clipped), or a blank. Documents stay per source page, so downloads never change. The edit page
asks each EPUB or Kindle file's outline whether it's fixed-layout, and shows the Pages section for it. Arrange
pages draws frame thumbnails for such files.

**Tech Stack:** Python 3 / FastAPI, `pytest` (`bash test.sh -q`); vanilla ES modules, `node --test tests/js/`;
Playwright (scratch venv) against the `loft-test` service on port 4545.

**Spec:** `docs/superpowers/specs/2026-11-23-fixed-layout-page-settings-design.md`

## Global Constraints

- Don't commit, push or release. The user commits when they ask.
- Work on `master` in place. Never install to device R32D204ZH6J.
- After Python changes: `systemctl --user restart loft-test`. Web files are served live.
- Books under `/var/mnt/smb-g/EBooks` are only read.
- `version` in a fixed-layout book's outline stays the file's version (`int(mtime)`). Page URLs and downloads
  must not change with the layout. A separate `layout_v` (`layout_rev`) does change.
- For fixed-layout books, Automatic never splits (`scanned=False`). The direction defaults to the book's own
  (`FlowBook.fixed.rtl`) until the admin picks one.
- Pages stay in sandboxed, script-less frames (`sandbox="allow-same-origin"`), as in 0.1.6, including thumbnails.
- Copy, verbatim from the spec:
  - "Two printed pages on one page": "Don’t split" (default) / "Split them"; hint "For books made from scans:
    cuts only the wide pages in two."
  - "Wraparound cover (back and front on one page)": "Automatic" / "Front first" / "As the book has it".
  - Reading direction: "Left to right" / "Right to left (manga)", as for comics.
- Errors for flowing books: "Only books with pages have page layouts" (layout) and "Only books with pages have
  pages to arrange" (arrangement).

## Review Focus

1. A place saved by 0.1.6 (`locator {chapter: n, progress: 0}`, `page == n`) reopens on source page *n* after
   the admin turns on splitting or hides earlier pages. Pinned in Task 3.
2. A flowing EPUB, or a Kindle file that can't be opened, on the edit page: no Pages section, no error banner,
   the rest of the edit page works. Pinned in Tasks 1 and 5.
3. "Split them" on a book with no wide pages changes nothing and doesn't fail. Pinned in Task 1.
4. A downloaded picture book, after a layout change: not downloaded again. Offline, it reads with the stored plan,
   and the plan is updated next time it's online. Pinned in Task 4.
5. Right to left with an odd page count and a blank page or hidden cover: page turning and the scrubber stay
   consistent, with the existing comics behaviour for odd counts. Checked in Task 4's browser step.

---

### Task 1: Page manifests for fixed-layout books

**Files:**
- Modify: `src/loft/pages.py`
- Test: `tests/test_fixed_layout.py` (new section "page settings")

**Interfaces:**
- Produces:
  - `pages.FIXED_FORMATS = {"epub", "azw3", "azw", "mobi"}`
  - `pages.fixed_layout_of(cfg, row) -> FixedLayout | None`. Opens via `flowbooks.open_flow` only for
    `FIXED_FORMATS`. `flow.Unreadable` becomes `pages.Unreadable` with the same kind.
  - `pages.has_pages(cfg, row) -> bool`: the format is in `READABLE`, or the file is fixed-layout.
  - `pages.file_layout(row, default_rtl: bool = False) -> dict`. A stored bool `rtl` wins, else `default_rtl`.
  - `pages.manifest(cfg, file_id) -> dict`. For a fixed-layout file:
    - the same keys as for comics;
    - `source` is the book's page sizes;
    - `toc` comes from `book.toc`, each entry `{title, chapter, anchor, level, page}`;
    - plus `"fixed": True`, `"spread": fixed.spread`, `"layout": file_layout(f, fixed.rtl)` and
      `"layout_v": f["layout_rev"]`.
  - `set_layout` and `set_arrangement` accept fixed-layout files. They refuse other flowing files with the
    exact errors above.
  - `render_page` and `render_piece` raise `Unreadable("format")` for fixed-layout files.

- [ ] **Step 1: Write the failing tests.** They use `add_to_library` and `fixed_epub`. Pages are portrait
  `VP` (706×1024) unless a wide viewport `WIDE = "width=1412, height=1024"` is given.

```python
def test_a_fixed_book_has_a_page_manifest(cfg):
    fid = add_to_library(cfg, "M.epub", pages=[(f"Text/p{i}.xhtml", f"<p>{i}</p>", VP) for i in range(3)])
    m = pages.manifest(cfg, fid)
    assert m["fixed"] is True and m["plan"] == [[0, None], [1, None], [2, None]]
    assert m["sizes"] == [[706, 1024]] * 3 and m["layout"] == {"split": None, "wraparound": None, "rtl": False}

def test_automatic_never_splits_a_fixed_book_but_split_them_does(cfg):
    fid = add_to_library(cfg, "W.epub", pages=[("Text/a.xhtml", "<p>a</p>", WIDE), ("Text/b.xhtml", "<p>b</p>", WIDE)])
    assert pages.manifest(cfg, fid)["plan"] == [[0, None], [1, None]]
    m = pages.set_layout(cfg, fid, True, None)
    assert m["plan"] == [[0, 1], [1, 0], [1, 1], [0, 0]]          # wraparound: front first, back last
    assert m["sizes"][0] == [706, 1024]
    assert pages.set_layout(cfg, fid, True, False)["plan"] == [[0, 0], [0, 1], [1, 0], [1, 1]]

def test_split_them_leaves_portrait_pages_whole(cfg):
    fid = add_to_library(cfg, "P.epub", pages=[("Text/a.xhtml", "<p>a</p>", VP)])
    assert pages.set_layout(cfg, fid, True, None)["plan"] == [[0, None]]

def test_direction_starts_at_the_books_own(cfg):
    fid = add_to_library(cfg, "R.epub", pages=[("Text/a.xhtml", "<p>a</p>", VP)],
                         spine_attrs=' page-progression-direction="rtl"')
    assert pages.manifest(cfg, fid)["rtl"] is True
    assert pages.set_layout(cfg, fid, None, None, rtl=False)["rtl"] is False

def test_a_fixed_book_can_be_arranged(cfg):
    fid = add_to_library(cfg, "A.epub", pages=[(f"Text/p{i}.xhtml", f"<p>{i}</p>", VP) for i in range(3)])
    m = pages.set_arrangement(cfg, fid, [[2, None], [-1, None], [0, None], [1, None]], [[1, None]])
    assert m["plan"] == [[2, None], [-1, None], [0, None]] and m["custom"] is True
    assert m["layout_v"] > 0

def test_flowing_books_have_no_page_settings(cfg, make_rich_epub):
    with session(cfg.db_path) as con:
        flowing = con.execute("SELECT id FROM book_files WHERE path LIKE '%Tale.epub'").fetchone()["id"]
    with pytest.raises(ValueError, match="Only books with pages have page layouts"):
        pages.set_layout(cfg, flowing, True, None)
    with pytest.raises(ValueError, match="Only books with pages have pages to arrange"):
        pages.set_arrangement(cfg, flowing, None, [])
```

  Copy the `Tale.epub` lookup from `test_the_outline_says_so`.

- [ ] **Step 2: Run them.**
  - Run: `~/.local/share/loft/venv/bin/python -m pytest tests/test_fixed_layout.py -q -k "manifest or split or direction or arranged or flowing_books_have"`
  - Expected: FAIL. `Unreadable: format` comes from `manifest`.
- [ ] **Step 3: Implement the Interfaces above in `src/loft/pages.py`.**
  - `_measured` returns `(fixed.sizes, toc, False)` for a fixed-layout file. It doesn't store `page_info`: the
    flow book is already cached.
  - `_natural` passes `default_rtl`.
  - Grep the tests for the old "Only PDFs and comics" messages and update them (record a ruling).
- [ ] **Step 4: Run them, then the whole suite.**
  - Run: `bash test.sh -q`
  - Expected: all pass (556 + 6 new, 1 skipped).

### Task 2: The outline carries the page plan

**Files:**
- Modify: `src/loft/app.py` (`flow_outline`)
- Test: `tests/test_fixed_layout.py::test_the_outline_says_so` (updated), plus a new test

**Interfaces:**
- Consumes: `pages.manifest` (Task 1).
- Produces. A fixed-layout book's outline has:
  - `outline["fixed"] = {"sizes": source sizes, "spread", "plan", "page_sizes", "layout_v"}`;
  - `outline["rtl"]`: resolved;
  - `outline["toc"]`: the manifest's toc;
  - `outline["layout"]`: `{split, wraparound, rtl}`;
  - `outline["arranged"]`: `custom`;
  - `outline["version"]`: still `int(mtime)`.

- [ ] **Step 1: Update and add tests.**

```python
def test_the_outline_says_so(client, cfg):          # updated: the plan rides along
    ...
    assert outline["fixed"]["sizes"] == [[706, 1024], [706, 1024]] and outline["fixed"]["spread"] is True
    assert outline["fixed"]["plan"] == [[0, None], [1, None]] and outline["fixed"]["page_sizes"] == [[706, 1024]] * 2
    assert outline["layout"] == {"split": None, "wraparound": None, "rtl": False} and outline["arranged"] is False

def test_a_layout_change_keeps_the_version_and_moves_layout_v(client, cfg, admin_client):
    fid = add_to_library(cfg, "V.epub", pages=[("Text/a.xhtml", "<p>a</p>", VP), ("Text/b.xhtml", "<p>b</p>", VP)])
    before = client.get(f"/api/files/{fid}/flow").json()
    r = admin_client.patch(f"/api/files/{fid}/arrangement", json={"order": [[1, None], [0, None]], "hidden": []})
    assert r.status_code == 200
    after = client.get(f"/api/files/{fid}/flow").json()
    assert after["version"] == before["version"] and after["fixed"]["layout_v"] > before["fixed"]["layout_v"]
    assert after["fixed"]["plan"] == [[1, None], [0, None]] and after["arranged"] is True
```

  Use whatever admin client fixture the other route tests use; check `tests/conftest.py`.
- [ ] **Step 2: Run them.**
  - Run: `… -m pytest tests/test_fixed_layout.py -q -k "outline"`
  - Expected: FAIL (KeyError `plan`).
- [ ] **Step 3: Implement in `flow_outline`.** Call `pages.manifest(cfg, file_id)` only when `book.fixed`, and
  map the keys as above.
- [ ] **Step 4: Run the suite and restart the test server.**
  - Run: `bash test.sh -q && systemctl --user restart loft-test`
  - Expected: all pass.

### Task 3: Places and halves, without a browser (`fixedfit.js`)

**Files:**
- Modify: `src/loft/web/js/fixedfit.js`
- Test: `tests/js/fixed.test.mjs`

**Interfaces:**
- Produces (replacing the old `placeOf(page)` and `startPage(progress, count)`):
  - `placeOf(plan, page) -> {chapter, progress}`. `chapter` is the entry's source page. `progress` is `0.5` for a
    right half (half 1), else `0`. A blank takes the nearest real page before it, or after it if there's none.
  - `startPage(progress, plan) -> int`:
    - With `locator.chapter`, the entry showing that source page, matching the half when the page is split
      (`progress >= 0.5` means half 1). If the page is hidden, the first shown entry of a later source page in
      book order, else the last page.
    - Without a locator, the old rules, with `count = plan.length`.
  - `halfBox([w, h], half) -> {width, height, shiftX}`: `half` null gives `{w, h, 0}`, 0 gives `{w/2, h, 0}`,
    and 1 gives `{w/2, h, w/2}`.
  - `pageScale`, `pageUrl` and `downloadFits` don't change.

- [ ] **Step 1: Rewrite the two place tests and add new ones.** `whole(n)` builds `[[0,null],…]`.

```js
const whole = (n) => Array.from({ length: n }, (_, i) => [i, null]);
test("a place saved by 0.1.6 still opens on its page after splitting or hiding", () => {
  const split = [[0, 1], [1, 0], [1, 1], [2, 0], [2, 1], [0, 0]];
  assert.equal(startPage({ page: 2, pages: 3, locator: { chapter: 2, progress: 0 } }, split), 3);
  assert.equal(startPage({ page: 1, pages: 3, locator: { chapter: 1, progress: 0.5 } }, split), 2);
  const hidden = [[0, null], [2, null], [3, null]];            // page 1 hidden
  assert.equal(startPage({ page: 1, pages: 4, locator: { chapter: 1, progress: 0 } }, hidden), 1);
  assert.equal(startPage({ page: 9, pages: 4, locator: { chapter: 9, progress: 0 } }, hidden), 2);
});
test("old places with no locator use the page number", () => {
  assert.equal(startPage({ page: 12, pages: 139 }, whole(139)), 12);
  assert.equal(startPage({ page: 500, pages: 1001 }, whole(139)), 69);
  assert.equal(startPage(null, whole(139)), 0);
});
test("a place names the source page and the half", () => {
  const plan = [[2, null], [-1, null], [0, 0], [0, 1]];
  assert.deepEqual(placeOf(plan, 0), { chapter: 2, progress: 0 });
  assert.deepEqual(placeOf(plan, 1), { chapter: 2, progress: 0 });   // a blank: the page before
  assert.deepEqual(placeOf(plan, 3), { chapter: 0, progress: 0.5 });
  assert.equal(startPage({ page: 3, pages: 4, locator: placeOf(plan, 3) }, plan), 3);
});
test("half a page", () => {
  assert.deepEqual(halfBox([1412, 1024], null), { width: 1412, height: 1024, shiftX: 0 });
  assert.deepEqual(halfBox([1412, 1024], 0), { width: 706, height: 1024, shiftX: 0 });
  assert.deepEqual(halfBox([1412, 1024], 1), { width: 706, height: 1024, shiftX: 706 });
});
```

  Keep the remaining `startPage` cases from the old test, with `whole(139)` as the plan.
- [ ] **Step 2: Run them.**
  - Run: `node --test tests/js/`
  - Expected: FAIL (`halfBox` isn't exported).
- [ ] **Step 3: Implement in `fixedfit.js`.**
- [ ] **Step 4: Run them.**
  - Run: `node --test tests/js/`
  - Expected: all pass.

### Task 4: The reader follows the plan (`fixed.js`, `zoom.js`, `offline.js`, `reader.js`)

**Files:**
- Modify:
  - `src/loft/web/js/fixed.js`
  - `src/loft/web/js/zoom.js`
  - `src/loft/web/js/offline.js`
  - `src/loft/web/js/reader.js`
  - `src/loft/web/style.css`
  - `src/loft/web/sw.js` (`CACHE` becomes `"loft-shell-v7"`)
- Verify: Playwright against `http://localhost:4545` on *Wedding Crashers* (loft-dev library).

**Interfaces:**
- Consumes: the outline (Task 2), and `placeOf`, `startPage` and `halfBox` (Task 3).
- Produces:
  - `FixedReader`:
    - `count = fixed.plan.length`, `sizes = fixed.page_sizes`, `rtl = outline.rtl`;
    - `entry(i) -> [src, half]`;
    - holders carry `data-page` (reader index), `data-src` and `data-half`;
    - a blank is `<div class="fixed-page fixed-blank" data-page>` (white, nothing loaded);
    - `text(src)` and `fill(src, frame)` are per source page;
    - `progressBody().locator = placeOf(plan, page)`;
    - `open` uses `startPage(progress, plan)`.
  - `fit(holder)` sets the iframe at the source size with
    `translate((cw - box.width*s)/2 - box.shiftX*s, (ch - h*s)/2) scale(s)`, where `s = pageScale([box.width, h], [cw, ch])`.
  - `openZoom({frame})`: `frame` gains `source(i) -> {size: [w, h], shiftX} | null` (null is a blank). Zoom sizes
    the iframe to `source.size`, shifts it by `-shiftX`, and clips to `frame.size(i)`. A blank shows white.
  - `offline.keepOutline(bookId, outline) -> Promise<void>`. For a complete record with the same `version`, it
    stores `outline` as `r.manifest`. Two callers:
    - `resume()`, in place of nothing, when `layout_v` differs;
    - `renderReader`, when `stored` and `manifest.fixed` and `kept.manifest.fixed?.layout_v !== manifest.fixed.layout_v`.

- [ ] **Step 1: Write the browser check first**, in `scratchpad/e2e/fixed_settings.py`, logged in as the test
  admin.
  1. Set an arrangement by `PATCH`: move page 2 first, hide page 3, and put a blank second.
  2. Open the reader and assert:
     - page 1's frame shows source 2 (`data-src="2"`);
     - page 2 is `.fixed-blank`;
     - the "Page x of N" count is `chapters − 1 + 1`.
  3. Turn on Split by `PATCH` (Wedding Crashers' pages are portrait, so the plan is unchanged), then set
     `rtl=true`. Assert that ArrowLeft goes forward.
  4. Download the book. Change the arrangement. Run `resume()` by reloading. Assert:
     - no new chapter fetches (count requests to `/chapters/`);
     - the stored outline's `layout_v` is the new one.
  5. Zoom page 1 and assert its frame shows source 2.
  6. Reset the arrangement and layout at the end.
- [ ] **Step 2: Run it.**
  - Run: `scratchpad/e2e/pwvenv/bin/python scratchpad/e2e/fixed_settings.py`
  - Expected: FAIL at the first assertion (`data-src` missing).
- [ ] **Step 3: Implement the Interfaces above.** In `style.css`, add `.fixed-blank { background: #fff; }`.
  Give `.zoom-frame` a blank state.
- [ ] **Step 4: Run it, then the JS tests.**
  - Run: the e2e script, then `node --test tests/js/`
  - Expected: all checks pass.
  - Also run the 0.1.6 reading checks again (the scripts in `scratchpad/e2e/` for reading and offline, 23 + 9
    checks): all still pass.

### Task 5: The edit page and Arrange pages

**Files:**
- Modify: `src/loft/web/js/book.js`, `src/loft/web/js/arrange.js`, `src/loft/web/style.css`
- Verify: Playwright, `scratchpad/e2e/fixed_edit.py`

**Interfaces:**
- Consumes: `outline.layout`, `outline.arranged` and `outline.fixed` (Task 2); `pages.manifest` for fixed-layout
  files through `/api/files/{id}/manifest` (Task 1); `pageUrl`, `halfBox` and `pageScale` (Task 3).
- Produces:
  - `book.js`:
    - `layoutHTML(b)` renders files with `f.layout`, using `f.fixed` to pick the picture-book copy and options:
      `SPLIT_FIXED = [[null, "Don’t split"], [true, "Split them"]]` (null is lit when `layout.split !== true`)
      and `WRAP_FIXED = [[null, "Automatic"], [true, "Front first"], [false, "As the book has it"]]`.
    - After the editor renders, each file with `readable === "flow"` and a format in
      `["epub", "azw3", "azw", "mobi"]` fetches `/api/files/{id}/flow`. A failure is ignored. When the outline has
      `fixed`, the file gets `f.layout = outline.layout`, `f.arranged = outline.arranged` and `f.fixed = true`.
      The section then renders into `[data-pages-slot]`, and `wirePages(main, b)` binds it.
    - `wirePages(main, b)` is the layout and arrange wiring moved out of `renderEditor`, unchanged for comics.
  - `arrange.js`: when `m.fixed`, a tile holds `<span class="arrange-frame" data-src data-half style="aspect-ratio">`.
    - An `IntersectionObserver` fills it with a sandboxed iframe `srcdoc` from
      `pageUrl(file.id, src, {version: m.file_v, fixed: true})`, cached per source.
    - It's scaled with `halfBox` and `pageScale` to the tile's width.
    - Blanks stay as they are.

- [ ] **Step 1: Write the browser check.** On the Wedding Crashers edit page (`#/book/<id>?edit=1`):
  - the Pages section appears with the picture-book copy (exact strings from Global Constraints);
  - clicking "Right to left (manga)" saves, which a reload shows;
  - Arrange pages shows tiles whose iframes have a non-empty `srcdoc` once scrolled into view;
  - hiding a page there is reflected by the reader.

  On the edit page of a flowing EPUB in the test library: no Pages section, and no `.form-error` visible. On a
  comic or PDF: the Pages section is as before ("Automatic" is present).
- [ ] **Step 2: Run it.**
  - Expected: FAIL (no Pages section on Wedding Crashers).
- [ ] **Step 3: Implement the Interfaces above.**
- [ ] **Step 4: Run it and the Task 4 check again.**
  - Expected: all pass.

### Task 6: Docs, and the whole suite

**Files:**
- Modify: `README.md` (the Reading/editing bullet that lists the Pages settings: add picture books)
- Modify: `CHANGELOG.md` (a new `## Unreleased` entry)

- [ ] **Step 1: Write the docs.** CHANGELOG: "Picture books get the Pages settings on their edit page: reading
  direction (starting at the book's own), page order (move, hide, blank pages), splitting pages that hold two
  printed pages, and the wraparound cover."
- [ ] **Step 2: Final verification.**
  - Run: `bash test.sh -q && node --test tests/js/`, then all `scratchpad/e2e` checks.
  - Expected: all pass.
  - Then `systemctl --user restart loft-test`, and confirm `/api/status` answers.
