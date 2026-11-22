// Fixed-layout books (fixed.js): where to open one, and how big to draw a page. Kept apart from the
// reader so they can be tested without a browser.

const clamp = (n, count) => Math.max(0, Math.min(count - 1, Math.floor(n) || 0));

/** The page to open at, from saved progress. Progress saved while the book was read as flowing text
 *  names its chapter (each chapter is a page) or a place out of 1001. */
export function startPage(progress, count) {
  if (!progress || count < 1) return 0;
  if (progress.locator && Number.isFinite(progress.locator.chapter)) return clamp(progress.locator.chapter, count);
  if (progress.pages === count || !(progress.pages > 0)) return clamp(progress.page, count);
  return clamp((progress.page / progress.pages) * count, count);
}

/** How much a page of `size` ([w, h], CSS px) is scaled to fit inside `box` ([w, h]). */
export function pageScale([w, h], [boxW, boxH]) {
  if (!(w > 0 && h > 0) || !(boxW > 0 && boxH > 0)) return 0;
  return Math.min(boxW / w, boxH / h);
}

/** Where a page is, as the server keeps places in books: a chapter (each page is one) and how far
 *  through it. Read as flowing text, the same book would open there too. */
export function placeOf(page) { return { chapter: page, progress: 0 }; }

/** Whether a download suits the book as it's read now. A picture book's download is labelled
 *  layout "fixed" when it holds real pages; one made before Loft read such books as pages (or one
 *  that took old text from the browser's cache) holds text-only chapters and is redone. */
export function downloadFits(kept, outline) {
  if (!kept) return false;
  return (kept.layout === "fixed") === Boolean(outline && outline.fixed);
}

/** Where a chapter (a page, for a picture book) is fetched from. A picture book's pages have their
 *  own address: browsers keep chapters for a week, and one kept from when the book was read as
 *  flowing text must never stand in for a page. */
export function pageUrl(fileId, n, outline) {
  return `/api/files/${fileId}/chapters/${n}?v=${outline.version}${outline.fixed ? "&layout=fixed" : ""}`;
}
