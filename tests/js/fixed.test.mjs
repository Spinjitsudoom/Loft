// Fixed-layout books (src/loft/web/js/fixedfit.js): where to open, and how big each page is drawn.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bookmarkPage, downloadFits, halfBox, pageScale, pageUrl, placeOf, startPage } from "../../src/loft/web/js/fixedfit.js";

const whole = (n) => Array.from({ length: n }, (_, i) => [i, null]);

test("a place saved while read as flowing text finds its page", () => {
  assert.equal(startPage({ page: 12, pages: 139 }, whole(139)), 12);                    // saved here
  assert.equal(startPage({ page: 500, pages: 1001, locator: { chapter: 40 } }, whole(139)), 40);
  assert.equal(startPage({ page: 500, pages: 1001 }, whole(139)), 69);                   // half way
  assert.equal(startPage({ page: 900, pages: 139 }, whole(139)), 138);                   // never past the end
  assert.equal(startPage({ page: 3, pages: 139, locator: { chapter: 300 } }, whole(139)), 138);
  assert.equal(startPage(null, whole(139)), 0);
  assert.equal(startPage({ page: -4, pages: 139 }, whole(139)), 0);
});

test("a place saved by 0.1.6 still opens on its page after splitting or hiding", () => {
  const split = [[0, 1], [1, 0], [1, 1], [2, 0], [2, 1], [0, 0]];
  assert.equal(startPage({ page: 2, pages: 3, locator: { chapter: 2, progress: 0 } }, split), 3);
  assert.equal(startPage({ page: 1, pages: 3, locator: { chapter: 1, progress: 0.5 } }, split), 2);
  const hidden = [[0, null], [2, null], [3, null]];            // page 1 hidden
  assert.equal(startPage({ page: 1, pages: 4, locator: { chapter: 1, progress: 0 } }, hidden), 1);
  assert.equal(startPage({ page: 9, pages: 4, locator: { chapter: 9, progress: 0 } }, hidden), 2);
});

test("a place names the source page and the half", () => {
  const plan = [[2, null], [-1, null], [0, 0], [0, 1]];
  assert.deepEqual(placeOf(plan, 0), { chapter: 2, progress: 0 });
  assert.deepEqual(placeOf(plan, 1), { chapter: 2, progress: 0 });   // a blank: the page before
  assert.deepEqual(placeOf(plan, 3), { chapter: 0, progress: 0.5 });
  assert.equal(startPage({ page: 3, pages: 4, locator: placeOf(plan, 3) }, plan), 3);
  assert.deepEqual(placeOf([[-1, null], [4, null]], 0), { chapter: 4, progress: 0 });  // a blank first: the page after
});

test("half a page", () => {
  assert.deepEqual(halfBox([1412, 1024], null), { width: 1412, height: 1024, shiftX: 0 });
  assert.deepEqual(halfBox([1412, 1024], 0), { width: 706, height: 1024, shiftX: 0 });
  assert.deepEqual(halfBox([1412, 1024], 1), { width: 706, height: 1024, shiftX: 706 });
});

test("pages fit their space", () => {
  assert.equal(pageScale([706, 1024], [353, 512]), 0.5);
  assert.equal(pageScale([706, 1024], [706, 2000]), 1);
  assert.ok(Math.abs(pageScale([1000, 1500], [400, 900]) - 0.4) < 1e-9);
  assert.equal(pageScale([706, 1024], [0, 0]), 0);
});

test("a place is saved the way the server keeps places in books", () => {
  assert.deepEqual(placeOf(whole(139), 7), { chapter: 7, progress: 0 });     // a chapter, and how far through it
  assert.equal(startPage({ page: 7, pages: 139, locator: placeOf(whole(139), 7) }, whole(139)), 7);
});

test("a download made for the other kind of reader isn't used", () => {
  const pages = { fixed: { sizes: [[706, 1024]], spread: true } };
  assert.equal(downloadFits({ layout: "fixed", manifest: pages }, pages), true);
  assert.equal(downloadFits({ kind: "flow", manifest: { chapters: [] } }, pages), false);   // downloaded as flowing text
  assert.equal(downloadFits({ kind: "flow", manifest: pages }, pages), false);             // pages not labelled as such
  assert.equal(downloadFits({ layout: "fixed", manifest: pages }, { chapters: [] }), false);
  assert.equal(downloadFits({ kind: "flow", manifest: { chapters: [] } }, { chapters: [] }), true);
  assert.equal(downloadFits({ kind: "pages" }, { count: 3 }), true);                       // comics as before
  assert.equal(downloadFits(undefined, pages), false);
});

test("a picture book's pages have their own address, so an old cached chapter never stands in", () => {
  const outline = { version: 1795288702, fixed: { sizes: [[706, 1024]], spread: true } };
  assert.equal(pageUrl(154, 3, outline), "/api/files/154/chapters/3?v=1795288702&layout=fixed");
  assert.equal(pageUrl(154, 3, { version: 1795288702 }), "/api/files/154/chapters/3?v=1795288702");
});

test("a bookmark from 0.1.6 (no locator: its page was the book's page) stays on that page", () => {
  const hidden = [[1, null], [2, null], [3, null]];             // page 0 hidden
  assert.equal(bookmarkPage({ page: 2 }, hidden), 1);            // the book's page 2, now shown second
  assert.equal(bookmarkPage({ page: 2, locator: { chapter: 3, progress: 0 } }, hidden), 2);
  assert.equal(bookmarkPage({ page: 0 }, hidden), 0);            // hidden: the next page shown
});
