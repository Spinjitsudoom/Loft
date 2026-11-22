// Fixed-layout books (picture books, many children's books): read as pages, like comics, but each
// page is the book's own page (its pictures, fonts and words where the designer put them), sent
// whole and cleaned by the server (src/loft/fixedpage.py) and shown in a sandboxed frame where
// nothing can run. Turning, spreads, scrolling, bookmarks and settings are the comics reader's.
import { Reader, registerFixedReader } from "./reader.js";
import { openZoom } from "./zoom.js";
import * as offline from "./offline.js";
import { pageScale, pageUrl, placeOf, startPage } from "./fixedfit.js";

const NEAR = 4;           // pages either side kept loaded
const KEEP = 3 * NEAR;    // pages further away than this are emptied, to save memory
const TEXTS = 24;         // page documents kept in memory

class FixedReader extends Reader {
  constructor(app, book, file, outline, reading) {
    super(app, book, file, { ...outline, count: outline.chapters.length, sizes: outline.fixed.sizes, rtl: outline.rtl }, reading);
    this.texts = new Map();
    this.sizer = new ResizeObserver((entries) => entries.forEach((e) => this.fit(e.target)));
  }

  open(start, progress = null) {
    super.open(progress ? startPage(progress, this.count) : start);
  }

  close() {
    this.sizer.disconnect();
    super.close();
  }

  destroyBook() {
    if (this.sizer) this.sizer.disconnect();
    super.destroyBook();
  }

  size(i) { return this.m.sizes[i] || [1000, 1500]; }

  twoPages() { return this.m.fixed.spread && super.twoPages(); }

  pageInner(i) {
    const [w, h] = this.size(i);
    return `<div class="fixed-page" data-page="${i}"><iframe sandbox="allow-same-origin" tabindex="-1" scrolling="no"
      title="Page ${i + 1}" style="width:${w}px;height:${h}px"></iframe></div>`;
  }

  // The page's frame at the page's own size, scaled to fill its space and centred in it.
  fit(holder) {
    const frame = holder.querySelector("iframe");
    const [w, h] = this.size(Number(holder.dataset.page));
    const s = pageScale([w, h], [holder.clientWidth, holder.clientHeight]);
    frame.style.transform = `translate(${(holder.clientWidth - w * s) / 2}px, ${(holder.clientHeight - h * s) / 2}px) scale(${s})`;
  }

  // A page's document: from this device for a downloaded book, else from the server.
  text(i) {
    if (this.texts.has(i)) return this.texts.get(i);
    const kept = this.stored ? offline.chapterText(this.book.id, this.file.id, i) : Promise.resolve(null);
    const p = kept.then((t) => t ?? fetch(pageUrl(this.file.id, i, this.m), { credentials: "same-origin" })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`page ${i + 1}: ${r.status}`)))));
    this.texts.set(i, p);
    p.catch(() => this.texts.delete(i));   // try again next time
    while (this.texts.size > TEXTS) this.texts.delete(this.texts.keys().next().value);
    return p;
  }

  async fill(i, frame) {
    const doc = await this.text(i);
    if (frame.dataset.page !== String(i)) { frame.dataset.page = String(i); frame.srcdoc = doc; }
  }

  empty(frame) {
    if (frame.dataset.page) { delete frame.dataset.page; frame.srcdoc = ""; }
  }

  holders() { return [...this.stage.querySelectorAll(".fixed-page")]; }

  loadNear(i) {
    for (const holder of this.holders()) {
      const p = Number(holder.dataset.page);
      const frame = holder.querySelector("iframe");
      if (!holder.dataset.watched) { holder.dataset.watched = "1"; this.sizer.observe(holder); }
      if (Math.abs(p - i) <= NEAR + 1) this.fill(p, frame).catch(() => {});
      else if (Math.abs(p - i) > KEEP) this.empty(frame);
    }
  }

  fillScrollPage(el, i) {
    const holder = el.querySelector(".fixed-page");
    if (!holder.dataset.watched) { holder.dataset.watched = "1"; this.sizer.observe(holder); }
    this.fill(i, holder.querySelector("iframe")).catch(() => {});
    // Far from here: let the frames go (the scroll column has one per page).
    for (const other of this.holders()) {
      if (Math.abs(Number(other.dataset.page) - i) > KEEP) this.empty(other.querySelector("iframe"));
    }
  }

  zoom() {
    if (this.zoomView) return;
    this.zoomView = openZoom({
      frame: { size: (i) => this.size(i), fill: (i, frame) => this.fill(i, frame) },
      index: this.page, count: this.count, rtl: this.rtl,
      onClose: (i) => { this.zoomView = null; if (i !== this.page) this.goTo(i); },
    });
  }

  progressBody() {
    const page = Math.max(...this.visiblePages());
    return { file_id: this.file.id, page, pages: this.count, locator: placeOf(page) };
  }

  tocPage(t) { return t.page ?? t.chapter; }
}

registerFixedReader(FixedReader);
