// Fixed-layout books (src/loft/web/js/fixedfit.js): where to open, and how big each page is drawn.
import { test } from "node:test";
import assert from "node:assert/strict";
import { downloadFits, pageScale, pageUrl, placeOf, startPage } from "../../src/loft/web/js/fixedfit.js";

test("a place saved while read as flowing text finds its page", () => {
  assert.equal(startPage({ page: 12, pages: 139 }, 139), 12);                    // saved here
  assert.equal(startPage({ page: 500, pages: 1001, locator: { chapter: 40 } }, 139), 40);
  assert.equal(startPage({ page: 500, pages: 1001 }, 139), 69);                   // half way
  assert.equal(startPage({ page: 900, pages: 139 }, 139), 138);                   // never past the end
  assert.equal(startPage({ page: 3, pages: 139, locator: { chapter: 300 } }, 139), 138);
  assert.equal(startPage(null, 139), 0);
  assert.equal(startPage({ page: -4, pages: 139 }, 139), 0);
});

test("pages fit their space", () => {
  assert.equal(pageScale([706, 1024], [353, 512]), 0.5);
  assert.equal(pageScale([706, 1024], [706, 2000]), 1);
  assert.ok(Math.abs(pageScale([1000, 1500], [400, 900]) - 0.4) < 1e-9);
  assert.equal(pageScale([706, 1024], [0, 0]), 0);
});

test("a place is saved the way the server keeps places in books", () => {
  assert.deepEqual(placeOf(7), { chapter: 7, progress: 0 });     // a chapter, and how far through it
  assert.equal(startPage({ page: 7, pages: 139, locator: placeOf(7) }, 139), 7);
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
