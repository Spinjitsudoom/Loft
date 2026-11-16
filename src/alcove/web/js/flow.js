// Flowing books (EPUB, Kindle, FB2, text): the text is laid out to fit the page at your font, size
// and margins, then turned like paper. Chapters are measured in hidden CSS columns to know how many
// pages each makes; a page shows one column of its chapter. Places are kept as {chapter, progress}
// so changing the text size or the screen keeps you on the same passage.
import { openZoom } from "./zoom.js";
import { Reader, registerFlowReader } from "./reader.js";

const FONTS = {
  literata: '"Literata", Georgia, serif',
  serif: 'Georgia, "Iowan Old Style", "Palatino Linotype", "Times New Roman", serif',
  sans: '"Instrument Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
};
const MARGINS = { narrow: 0.06, normal: 0.09, wide: 0.13 };
const NEAR = 3;

class Layout {
  constructor(reader, box) {
    this.r = reader;
    this.box = box;
    this.counts = [];
    this.starts = [];
    this.anchors = [];
    this.total = 0;
  }

  key() {
    const b = this.box, r = this.r.reading;
    return `alcove-flow:${this.r.file.id}:${this.r.m.version}:${b.textW}x${b.textH}:${r.epub_font}:${b.fontSize}`;
  }

  async measure(onProgress) {
    const n = this.r.m.chapters.length;
    let cached = null;
    try { cached = JSON.parse(sessionStorage.getItem(this.key()) || "null"); } catch { /* private mode */ }
    if (cached && cached.counts && cached.counts.length === n) {
      this.counts = cached.counts;
      this.anchors = cached.anchors;
    } else {
      const probe = document.createElement("div");
      probe.className = "flow-measure";
      probe.innerHTML = `<div class="flow-text"></div>`;
      document.body.appendChild(probe);
      const text = probe.firstChild;
      this.r.styleText(text, this.box);
      const step = this.box.textW + this.box.gap;
      try {
        for (let c = 0; c < n; c++) {
          text.innerHTML = await this.r.chapter(c);
          const pages = Math.max(1, Math.ceil((text.scrollWidth + this.box.gap - 2) / step));
          const anchors = {};
          text.querySelectorAll("[id]").forEach((el) => {
            anchors[el.id] = Math.min(pages - 1, Math.max(0, Math.floor((el.offsetLeft + 1) / step)));
          });
          this.counts.push(pages);
          this.anchors.push(anchors);
          onProgress((c + 1) / n);
        }
      } finally {
        probe.remove();
      }
      try { sessionStorage.setItem(this.key(), JSON.stringify({ counts: this.counts, anchors: this.anchors })); } catch { /* full */ }
    }
    let at = 0;
    this.starts = this.counts.map((count) => { const s = at; at += count; return s; });
    this.total = at;
  }

  where(page) {
    let c = this.starts.length - 1;
    while (c > 0 && this.starts[c] > page) c--;
    return { chapter: c, k: page - this.starts[c] };
  }

  locatorOf(page) {
    const { chapter, k } = this.where(page);
    return { chapter, progress: this.counts[chapter] ? k / this.counts[chapter] : 0 };
  }

  pageOf(loc) {
    if (!loc) return 0;
    const c = Math.min(Math.max(0, loc.chapter), this.counts.length - 1);
    return this.starts[c] + Math.min(this.counts[c] - 1, Math.floor((loc.progress || 0) * this.counts[c] + 1e-6));
  }

  anchorPage(chapter, anchor) {
    const c = Math.min(Math.max(0, chapter), this.counts.length - 1);
    return this.starts[c] + ((anchor && this.anchors[c][anchor]) || 0);
  }
}

class FlowReader extends Reader {
  constructor(...args) {
    super(...args);
    this.texts = new Map();
    this.layout = null;
    this.startLocator = null;
  }

  open(start, progress) {
    this.startLocator = progress && progress.locator ? progress.locator : null;
    this.startPage = start;
    super.open(0);
  }

  chapter(c) {
    if (!this.texts.has(c)) {
      this.texts.set(c, fetch(`/api/files/${this.file.id}/chapters/${c}`, { credentials: "same-origin" })
        .then((r) => (r.ok ? r.text() : "<p>This part of the book couldn’t be loaded.</p>")));
    }
    return this.texts.get(c);
  }

  // ---------- page size and type ----------

  pageBox() {
    const W = this.stage.clientWidth, H = this.stage.clientHeight;
    const phone = W < 700;
    const two = this.reading.spread && !phone && W > H * 1.05;
    let pageW, pageH;
    if (phone) { pageW = W; pageH = H; }
    else if (two) { pageH = H; pageW = Math.floor(Math.min(W / 2, H * 0.72)); }
    else { pageH = H; pageW = Math.floor(Math.min(W, H * 0.72)); }
    const mx = Math.round(pageW * (MARGINS[this.reading.epub_margins] || MARGINS.normal));
    const my = Math.round(pageH * 0.07);
    const fontSize = Math.round((phone ? 17 : 18) * (this.reading.epub_size || 100) / 100 * 10) / 10;
    return { two, pageW, pageH, mx, my, textW: pageW - 2 * mx, textH: pageH - 2 * my - 14, gap: 2 * mx, fontSize };
  }

  styleText(el, box) {
    el.style.width = `${box.textW}px`;
    el.style.height = `${box.textH}px`;
    el.style.columnWidth = `${box.textW}px`;
    el.style.columnGap = `${box.gap}px`;
    el.style.fontFamily = FONTS[this.reading.epub_font] || FONTS.literata;
    el.style.fontSize = `${box.fontSize}px`;
    el.style.setProperty("--text-h", `${box.textH}px`);
  }

  // ---------- building ----------

  async build() {
    const keep = this.layout ? this.layout.locatorOf(this.page) : this.startLocator;
    const keepPage = this.layout ? null : this.startPage;
    this.destroyBook();
    if (this.reading.mode === "scroll") return this.buildFlowScroll(keep);
    const box = this.pageBox();
    this.box = box;
    this.spread = box.two;
    const note = document.createElement("p");
    note.className = "reader-loading";
    note.textContent = "Laying out the book…";
    this.stage.appendChild(note);
    await (document.fonts ? document.fonts.ready : Promise.resolve());
    const layout = new Layout(this, box);
    const token = (this.buildToken = (this.buildToken || 0) + 1);
    await layout.measure((f) => { note.textContent = `Laying out the book… ${Math.round(f * 100)}%`; });
    if (token !== this.buildToken || !this.root.isConnected) return;
    note.remove();
    this.layout = layout;
    this.count = layout.total;
    const scrubber = this.root.querySelector(".scrubber");
    scrubber.max = Math.max(0, this.count - 1);

    const holder = document.createElement("div");
    holder.className = "flip-book flow-book";
    holder.style.width = `${box.two ? box.pageW * 2 : box.pageW}px`;
    holder.style.height = `${box.pageH}px`;
    holder.style.margin = "0 auto";
    holder.innerHTML = Array.from({ length: this.count }, (_, i) =>
      `<div class="leaf flow-leaf" data-density="soft"><div class="flow-page" style="left:${box.mx}px;top:${box.my}px;width:${box.textW}px;height:${box.textH}px"></div><span class="folio">${i + 1}</span></div>`).join("");
    this.stage.appendChild(holder);
    this.flip = new St.PageFlip(holder, {
      width: box.pageW, height: box.pageH, size: "fixed", usePortrait: true, showCover: false,
      drawShadow: true, maxShadowOpacity: 0.35, mobileScrollSupport: false, disableFlipByClick: true,
      showPageCorners: true, flippingTime: { gentle: 1000, normal: 700, quick: 420, off: 1 }[this.reading.turn_speed] || 700,
    });
    this.flip.loadFromHTML(holder.querySelectorAll(".leaf"));
    this.flip.on("flip", (e) => this.onPage(e.data));
    const target = keep ? layout.pageOf(keep) : Math.min(keepPage || 0, this.count - 1);
    this.goTo(target, false);
  }

  loadNear(i) {
    if (!this.flip || !this.layout) return;
    const leaves = this.stage.querySelectorAll(".flow-leaf .flow-page");
    const step = this.box.textW + this.box.gap;
    for (let j = Math.max(0, i - NEAR); j <= Math.min(this.count - 1, i + NEAR + 1); j++) {
      const page = leaves[j];
      if (!page || page.dataset.filled) continue;
      page.dataset.filled = "1";
      const { chapter, k } = this.layout.where(j);
      this.chapter(chapter).then((html) => {
        const text = document.createElement("div");
        text.className = "flow-text";
        this.styleText(text, this.box);
        text.style.transform = `translateX(${-k * step}px)`;
        text.innerHTML = html;
        page.replaceChildren(text);
      });
    }
  }

  visiblePages() {
    if (this.flip && this.flip.getOrientation() === "landscape") {
      const left = this.page - (this.page % 2);
      return [left, left + 1].filter((p) => p < this.count);
    }
    return [this.page];
  }

  rescaleSpread() {
    if (this.reading.mode !== "pages" || !this.box) return false;
    const now = this.pageBox();
    return Math.abs(now.pageW - this.box.pageW) > 2 || Math.abs(now.pageH - this.box.pageH) > 2 || now.two !== this.box.two;
  }

  relayoutFor(key) { return ["mode", "spread", "epub_font", "epub_size", "epub_margins"].includes(key); }

  // ---------- scrolling instead of pages ----------

  async buildFlowScroll(keep) {
    this.layout = null;
    const col = document.createElement("div");
    col.className = "scroll-book flow-scroll";
    col.style.fontFamily = FONTS[this.reading.epub_font] || FONTS.literata;
    col.style.fontSize = `${Math.round(18 * (this.reading.epub_size || 100)) / 100}px`;
    const n = this.m.chapters.length;
    col.innerHTML = Array.from({ length: n }, (_, c) => `<section class="flow-chapter" data-c="${c}"><p class="reader-loading-inline">…</p></section>`).join("");
    this.stage.appendChild(col);
    this.scroller = col;
    this.count = n;
    this.root.querySelector(".scrubber").max = Math.max(0, n - 1);
    const sections = [...col.querySelectorAll(".flow-chapter")];
    await Promise.all(sections.map(async (s, c) => { s.innerHTML = await this.chapter(c); }));
    if (!this.root.isConnected) return;
    const target = keep || { chapter: 0, progress: 0 };
    const sec = sections[Math.min(target.chapter, n - 1)];
    this.quiet = true;
    col.scrollTop = sec.offsetTop + target.progress * sec.offsetHeight - 40;
    setTimeout(() => { this.quiet = false; }, 400);
    this.onScroll = () => {
      const mid = col.scrollTop + col.clientHeight / 2;
      const s = sections.find((el) => el.offsetTop + el.offsetHeight > mid) || sections[n - 1];
      this.scrollLoc = { chapter: Number(s.dataset.c), progress: Math.min(1, Math.max(0, (mid - s.offsetTop) / s.offsetHeight)) };
      this.onPage(this.scrollLoc.chapter);
    };
    col.addEventListener("scroll", this.onScroll, { passive: true });
    this.onScroll();
  }

  onPage(i, save = true) {
    super.onPage(i, save);
    if (this.reading.mode === "scroll") {
      const t = this.m.chapters[i] && this.m.chapters[i].title;
      this.root.querySelector(".reader-where").textContent = t || `Chapter ${i + 1} of ${this.m.chapters.length}`;
    }
  }

  goTo(i, save = true) {
    if (this.reading.mode === "scroll" && this.scroller) {
      const sec = this.scroller.querySelector(`[data-c="${i}"]`);
      if (sec) this.scroller.scrollTop = sec.offsetTop - 16;
      return;
    }
    super.goTo(i, save);
  }

  // ---------- saving and bookmarks ----------

  progressBody() {
    if (this.reading.mode === "scroll" || !this.layout) {
      const loc = this.scrollLoc || { chapter: 0, progress: 0 };
      const n = this.m.chapters.length;
      const page = Math.min(1000, Math.round(((loc.chapter + loc.progress) / n) * 1000));
      return { file_id: this.file.id, page, pages: 1001, locator: loc };
    }
    return { file_id: this.file.id, page: Math.max(...this.visiblePages()), pages: this.count,
             locator: this.layout.locatorOf(this.page) };
  }

  bookmarkBody() {
    const body = this.progressBody();
    return { file_id: this.file.id, page: this.layout ? this.page : body.page, locator: body.locator };
  }

  bookmarkPage(b) {
    if (this.layout && b.locator) return this.layout.pageOf(b.locator);
    if (!this.layout && b.locator) return b.locator.chapter;
    return b.page;
  }

  tocEntries() {
    return this.m.toc.length ? this.m.toc
      : this.m.chapters.map((c, i) => ({ title: c.title || `Chapter ${i + 1}`, chapter: i, anchor: "", level: 0 }));
  }

  tocPage(t) { return this.layout ? this.layout.anchorPage(t.chapter, t.anchor) : t.chapter; }

  // ---------- taps on links and pictures ----------

  handleTap(e) {
    const link = e.target.closest && e.target.closest("a");
    if (link) {
      if (link.dataset.chapter !== undefined) {
        e.preventDefault();
        const c = Number(link.dataset.chapter);
        if (this.layout) this.goTo(this.layout.anchorPage(c, link.dataset.anchor));
        else this.goTo(c);
      }
      return true;  // external links open in a new tab by themselves
    }
    const img = e.target.closest && e.target.closest(".flow-text img, .flow-chapter img");
    if (img) {
      openZoom({ src: () => img.src, index: 0, count: 1, onClose: () => {} });
      return true;
    }
    return false;
  }

  zoom() {}  // text gets bigger with the text size setting, not by zooming

  wire() {
    super.wire();
    // Links inside pages are handled on tap; stop the browser following "#".
    this.on(this.stage, "click", (e) => { if (e.target.closest && e.target.closest("a[data-chapter]")) e.preventDefault(); });
  }

  // ---------- text settings ----------

  extraPrefs() {
    const r = this.reading;
    const seg = (key, options) => `<div class="segmented" role="radiogroup">${options.map(([v, label]) =>
      `<button type="button" role="radio" aria-checked="${r[key] === v}" data-set="${key}" data-value="${v}">${label}</button>`).join("")}</div>`;
    return `
      <h3>Font</h3>
      ${seg("epub_font", [["literata", "Literata"], ["serif", "Serif"], ["sans", "Sans"]])}
      <h3>Text size</h3>
      <div class="segmented size-steps">
        <button type="button" data-size="-10" aria-label="Smaller text" ${r.epub_size <= 80 ? "disabled" : ""}>A−</button>
        <span class="size-now">${r.epub_size}%</span>
        <button type="button" data-size="10" aria-label="Bigger text" ${r.epub_size >= 160 ? "disabled" : ""}>A+</button>
      </div>
      <h3>Margins</h3>
      ${seg("epub_margins", [["narrow", "Narrow"], ["normal", "Normal"], ["wide", "Wide"]])}`;
  }

  wireExtraPrefs(panel) {
    panel.querySelectorAll("[data-size]").forEach((b) => b.addEventListener("click", () => {
      const next = Math.min(160, Math.max(80, (this.reading.epub_size || 100) + Number(b.dataset.size)));
      this.setPref("epub_size", next, panel);
    }));
  }
}

registerFlowReader(FlowReader);
