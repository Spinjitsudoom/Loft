// The reader: a book whose pages curl like paper (StPageFlip), or a scrolling column of pages.
// Pages are images from the server; only the ones near where you are get loaded.
import { api, esc, icon } from "./api.js";
import { openZoom } from "./zoom.js";
import { loadPrefs, patchPrefs } from "./prefs.js";

const WIDTHS = [600, 900, 1200, 1800, 2400];
const SPEEDS = { gentle: 1000, normal: 700, quick: 420, off: 1 };
const READABLE = new Set(["pdf", "cbz", "cbr", "cb7"]);
const NEAR = 4;
const SAVE_AFTER = 1500;

function retryOnce() {
  if (this.dataset.retried) return;
  this.dataset.retried = "1";
  const url = this.getAttribute("src");
  setTimeout(() => { if (this.getAttribute("src") === url) this.src = `${url}&retry=1`; }, 1500);
}

const snap = (px) => WIDTHS.find((w) => w >= px) || WIDTHS[WIDTHS.length - 1];

function commonRatio(sizes) {
  const counts = new Map();
  for (const [w, h] of sizes) {
    const r = Math.round((w / h) * 100) / 100;
    counts.set(r, (counts.get(r) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
}

function unreadableCard(app, book, message) {
  const file = book.files[0];
  app.innerHTML = `<main class="reader-message"><div>
    <h1>${esc(book.title)}</h1>
    <p>${esc(message)}</p>
    <div class="hero-actions">
      <a class="btn" href="#/book/${book.id}">Back to the book</a>
      ${file ? `<a class="btn btn-primary" href="/api/files/${file.id}" download>${icon("download")}Download</a>` : ""}
    </div></div></main>`;
}

export async function renderReader(app, bookId, params, isCurrent = () => true) {
  app.innerHTML = `<div class="reader" data-theme="dark"><p class="reader-loading">Opening the book…</p></div>`;
  const stale = () => !isCurrent();
  const book = await api(`/books/${bookId}`);
  if (stale()) return () => {};
  const wanted = Number(params.get("file")) || (book.progress && book.progress.file_id);
  const file = book.files.find((f) => f.id === wanted && READABLE.has(f.format))
    || book.files.find((f) => READABLE.has(f.format));
  if (!file) {
    if (stale()) return () => {};
    unreadableCard(app, book, "This kind of book can’t be read here yet; download it instead.");
    return () => {};
  }
  let manifest;
  try {
    manifest = await api(`/files/${file.id}/manifest`);
  } catch (e) {
    if (!stale()) unreadableCard(app, book, e.message);
    return () => {};
  }
  const prefs = await loadPrefs();
  if (stale()) return () => {};
  const r = new Reader(app, book, file, manifest, prefs.reading);
  const fromLink = params.get("page");
  const saved = book.progress && book.progress.file_id === file.id ? book.progress.page : 0;
  r.open(fromLink !== null ? Number(fromLink) : saved);
  return () => r.close();
}

class Reader {
  constructor(app, book, file, manifest, reading) {
    this.app = app;
    this.book = book;
    this.file = file;
    this.m = manifest;
    this.count = manifest.count;
    this.reading = { ...reading };
    this.ratio = commonRatio(manifest.sizes);
    this.page = 0;
    this.flip = null;
    this.bookmarks = [];
    this.saveTimer = null;
    this.listeners = [];
    this.dirty = false;   // read past a page since the last save
    this.pageAt = 0;      // when that happened (seconds)
    this.quiet = false;   // moving the book ourselves (opening it), not the reader turning pages
    this.zoomView = null;
  }

  src(i, cssWidth) {
    return `/api/files/${this.file.id}/pages/${i}?w=${snap(cssWidth * (devicePixelRatio || 1))}&v=${this.m.version}`;
  }

  on(target, type, fn, opts) {
    target.addEventListener(type, fn, opts);
    this.listeners.push(() => target.removeEventListener(type, fn, opts));
  }

  open(start) {
    this.page = Math.max(0, Math.min(this.count - 1, start || 0));
    this.app.innerHTML = `<div class="reader" data-theme="${this.reading.theme}">
      <div class="reader-stage" aria-label="${esc(this.book.title)}"></div>
      <header class="reader-top">
        <a class="icon-btn" href="#/book/${this.book.id}" aria-label="Back to the book">${icon("left")}</a>
        <h1 class="reader-title">${esc(this.book.title)}</h1>
        <button class="icon-btn" type="button" data-panel="contents" aria-label="Contents and bookmarks">${icon("list")}</button>
        <button class="icon-btn" type="button" data-bookmark aria-label="Bookmark this page" aria-pressed="false">${icon("bookmark")}</button>
        <button class="icon-btn" type="button" data-panel="prefs" aria-label="Reading settings">${icon("type")}</button>
      </header>
      <footer class="reader-bottom">
        <input class="scrubber" type="range" min="0" max="${this.count - 1}" value="${this.page}" aria-label="Go to page">
        <span class="reader-where"></span>
      </footer>
      <aside class="reader-panel" data-for="contents" hidden></aside>
      <aside class="reader-panel" data-for="prefs" hidden></aside>
    </div>`;
    this.root = this.app.querySelector(".reader");
    this.stage = this.root.querySelector(".reader-stage");
    this.wire();
    this.build();
    this.loadBookmarks();
    this.showControls(true);
    this.hideTimer = setTimeout(() => this.showControls(false), 2200);
  }

  close() {
    if (this.zoomView) { this.zoomView.close(true); this.zoomView = null; }
    this.saveNow(true);
    clearTimeout(this.saveTimer);
    clearTimeout(this.hideTimer);
    this.listeners.forEach((off) => off());
    this.destroyBook();
  }

  // ---------- building the book ----------

  build() {
    this.destroyBook();
    if (this.reading.mode === "scroll") this.buildScroll();
    else this.buildPages();
    this.goTo(this.page, false);
  }

  destroyBook() {
    if (this.flip) { try { this.flip.destroy(); } catch {} this.flip = null; }
    if (this.observer) { this.observer.disconnect(); this.observer = null; }
    if (this.stage) this.stage.innerHTML = "";
  }

  twoPages() {
    const { clientWidth: w, clientHeight: h } = this.stage;
    return this.reading.spread && w >= 2 * h * this.ratio * 0.8;
  }

  buildPages() {
    this.spread = this.twoPages();
    const holder = document.createElement("div");
    holder.className = "flip-book";
    holder.innerHTML = Array.from({ length: this.count },
      (_, i) => `<div class="leaf" data-density="soft"><img alt="Page ${i + 1}" draggable="false" decoding="async"></div>`).join("");
    this.stage.appendChild(holder);
    const stageW = this.stage.clientWidth;
    this.flip = new St.PageFlip(holder, {
      width: 600, height: Math.round(600 / this.ratio), size: "stretch",
      minWidth: this.spread ? 60 : stageW + 1, maxWidth: 5000, minHeight: 60, maxHeight: 5000,
      showCover: true, usePortrait: true, drawShadow: true, maxShadowOpacity: 0.5,
      mobileScrollSupport: false, disableFlipByClick: true, showPageCorners: true,
      flippingTime: SPEEDS[this.reading.turn_speed] || 700, startPage: this.page,
    });
    this.flip.loadFromHTML(holder.querySelectorAll(".leaf"));
    this.flip.on("flip", (e) => this.onPage(e.data));
    this.flip.on("init", () => this.loadNear(this.page));
    this.flip.on("changeOrientation", () => this.loadNear(this.page));
  }

  buildScroll() {
    const col = document.createElement("div");
    col.className = "scroll-book";
    col.innerHTML = this.m.sizes.map(([w, h], i) =>
      `<div class="scroll-page" data-i="${i}" style="aspect-ratio: ${w} / ${h}"><img alt="Page ${i + 1}" decoding="async" draggable="false"></div>`).join("");
    this.stage.appendChild(col);
    this.scroller = col;
    const width = () => col.querySelector(".scroll-page").clientWidth;
    const loader = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const img = e.target.querySelector("img");
        if (!img.getAttribute("src")) { img.onerror = retryOnce; img.src = this.src(Number(e.target.dataset.i), width()); }
      }
    }, { root: col, rootMargin: "150% 0px" });
    const current = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) this.onPage(Number(e.target.dataset.i));
    }, { root: col, rootMargin: "-50% 0px -50% 0px" });
    col.querySelectorAll(".scroll-page").forEach((el) => { loader.observe(el); current.observe(el); });
    this.observer = { disconnect: () => { loader.disconnect(); current.disconnect(); } };
  }

  pageWidthCss() {
    try {
      const rect = this.flip && this.flip.getBoundsRect();
      if (rect && rect.pageWidth) return rect.pageWidth;
    } catch { /* not laid out yet */ }
    return null;
  }

  loadNear(i) {
    if (!this.flip) return;
    const imgs = this.stage.querySelectorAll(".leaf img");
    const w = this.pageWidthCss();
    if (!w) return; // the book isn't laid out yet; "init" calls back
    for (let j = Math.max(0, i - NEAR); j <= Math.min(this.count - 1, i + NEAR + 1); j++) {
      const want = this.src(j, w);
      if (imgs[j] && imgs[j].dataset.want !== want) {
        imgs[j].dataset.want = want;
        imgs[j].onerror = retryOnce;
        imgs[j].src = want;
      }
    }
  }

  // ---------- moving through the book ----------

  goTo(i, save = true) {
    i = Math.max(0, Math.min(this.count - 1, i));
    this.quiet = !save;  // turnToPage fires "flip" straight away; that isn't the reader turning a page
    try {
      if (this.flip) this.flip.turnToPage(i);
      else if (this.scroller) {
        const el = this.scroller.querySelector(`[data-i="${i}"]`);
        if (el) this.scroller.scrollTop = el.offsetTop - 16;
      }
    } finally {
      this.quiet = false;
    }
    this.onPage(i, save);
    if (!save && this.scroller) {  // scrolling to the saved page fires the observer too
      this.quiet = true;
      setTimeout(() => { this.quiet = false; }, 400);
    }
  }

  step(dir) {
    if (this.flip) {
      if (this.reading.turn_speed === "off") {
        const by = this.flip.getOrientation() === "landscape" ? 2 : 1;
        const cur = this.flip.getCurrentPageIndex();
        this.goTo(dir > 0 ? cur + by : Math.max(0, cur - by));
      } else if (dir > 0) this.flip.flipNext("bottom");
      else this.flip.flipPrev("bottom");
    } else if (this.scroller) {
      this.scroller.scrollBy({ top: dir * this.scroller.clientHeight * 0.9, behavior: "smooth" });
    }
  }

  onPage(i, save = true) {
    this.page = i;
    this.loadNear(i);
    const scrubber = this.root.querySelector(".scrubber");
    if (document.activeElement !== scrubber) scrubber.value = i;
    this.root.querySelector(".reader-where").textContent = `Page ${i + 1} of ${this.count}`;
    this.markBookmarkButton();
    if (save && !this.quiet) {
      this.dirty = true;
      this.pageAt = Date.now() / 1000;
      clearTimeout(this.saveTimer);
      this.saveTimer = setTimeout(() => this.saveNow(), SAVE_AFTER);
    }
  }

  saveNow(leaving = false) {
    clearTimeout(this.saveTimer);
    if (!this.dirty) return;  // nothing read since the last save: never overwrite another device's place
    this.dirty = false;
    // The last page in view, so reaching the final spread of a two-page book counts as finished.
    const page = Math.max(...this.visiblePages());
    const body = JSON.stringify({ file_id: this.file.id, page, pages: this.count, at: this.pageAt });
    fetch(`/api/books/${this.book.id}/progress`, {
      method: "PUT", body, keepalive: leaving, credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    }).then((r) => { if (!r.ok) this.dirty = true; }).catch(() => { this.dirty = true; });
  }

  // ---------- taps, keys, gestures ----------

  wire() {
    let down = null, lastTap = 0, tapTimer = null;
    this.on(this.stage, "pointerdown", (e) => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; });
    this.on(this.stage, "pointerup", (e) => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      const quick = performance.now() - down.t < 350;
      down = null;
      if (moved > 8 || !quick) return;
      const x = e.clientX / innerWidth;
      const now = performance.now();
      if (x > 0.3 && x < 0.7) {
        if (now - lastTap < 300) { clearTimeout(tapTimer); lastTap = 0; this.zoom(); return; }
        lastTap = now;
        tapTimer = setTimeout(() => this.toggleControls(), 260);
        return;
      }
      if (this.reading.mode === "scroll") return;
      const forward = (x >= 0.7) !== this.reading.left_handed;
      if (e.pointerType === "mouse" && this.flip) {
        // StPageFlip turns the page itself when a corner is clicked (its mouseup comes after ours).
        setTimeout(() => { if (this.flip && this.flip.getState() === "read") this.step(forward ? 1 : -1); }, 0);
      } else {
        this.step(forward ? 1 : -1);
      }
    });
    this.on(this.stage, "touchstart", (e) => { if (e.touches.length === 2) { e.preventDefault(); this.zoom(); } }, { passive: false });
    this.on(this.stage, "wheel", (e) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); this.zoom(); } }, { passive: false });
    this.on(window, "keydown", (e) => {
      if (e.target.closest && e.target.closest("input, textarea, select")) return;
      if (["ArrowRight", "PageDown", " "].includes(e.key)) { e.preventDefault(); this.step(1); }
      else if (["ArrowLeft", "PageUp"].includes(e.key)) { e.preventDefault(); this.step(-1); }
      else if (e.key === "Escape") {
        if (!this.closePanels()) location.hash = `#/book/${this.book.id}`;
      }
    });
    let resizeTimer;
    this.on(window, "resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (this.reading.mode === "pages" && this.twoPages() !== this.spread) this.build();
        else this.loadNear(this.page);
      }, 200);
    });
    this.on(window, "pagehide", () => this.saveNow(true));
    this.on(document, "visibilitychange", () => { if (document.visibilityState === "hidden") this.saveNow(true); });

    const scrubber = this.root.querySelector(".scrubber");
    scrubber.addEventListener("input", () => {
      this.root.querySelector(".reader-where").textContent = `Page ${Number(scrubber.value) + 1} of ${this.count}`;
    });
    scrubber.addEventListener("change", () => { this.goTo(Number(scrubber.value)); scrubber.blur(); });

    this.root.querySelectorAll("[data-panel]").forEach((b) =>
      b.addEventListener("click", () => this.togglePanel(b.dataset.panel)));
    this.root.querySelector("[data-bookmark]").addEventListener("click", () => this.toggleBookmark());
    this.root.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".reader-top, .reader-bottom, .reader-panel")) clearTimeout(this.hideTimer);
    });
  }

  zoom() {
    if (this.zoomView) return;
    this.zoomView = openZoom({
      src: (i) => `/api/files/${this.file.id}/pages/${i}?w=2400&v=${this.m.version}`,
      index: this.page, count: this.count,
      onClose: (i) => { this.zoomView = null; if (i !== this.page) this.goTo(i); },
    });
  }

  showControls(on) {
    this.root.classList.toggle("controls-on", on);
    if (!on) this.closePanels();
  }

  toggleControls() {
    clearTimeout(this.hideTimer);
    this.showControls(!this.root.classList.contains("controls-on"));
  }

  closePanels() {
    let closed = false;
    this.root.querySelectorAll(".reader-panel").forEach((p) => { if (!p.hidden) { p.hidden = true; closed = true; } });
    return closed;
  }

  togglePanel(name) {
    const panel = this.root.querySelector(`.reader-panel[data-for="${name}"]`);
    const opening = panel.hidden;
    this.closePanels();
    if (!opening) return;
    if (name === "contents") this.drawContents(panel);
    else this.drawPrefs(panel);
    panel.hidden = false;
  }

  // ---------- contents and bookmarks ----------

  async loadBookmarks() {
    this.bookmarks = (await api(`/books/${this.book.id}/bookmarks`).catch(() => []))
      .filter((b) => b.file_id === this.file.id);
    this.markBookmarkButton();
  }

  visiblePages() {
    if (this.flip && this.flip.getOrientation() === "landscape" && this.page > 0) {
      const left = this.page % 2 === 1 ? this.page : this.page - 1;
      return [left, left + 1].filter((p) => p < this.count);
    }
    return [this.page];
  }

  markBookmarkButton() {
    const on = this.bookmarks.some((b) => this.visiblePages().includes(b.page));
    const button = this.root && this.root.querySelector("[data-bookmark]");
    if (!button) return;
    button.setAttribute("aria-pressed", String(on));
    button.setAttribute("aria-label", on ? "Remove bookmark" : "Bookmark this page");
  }

  async toggleBookmark() {
    const here = this.bookmarks.filter((b) => this.visiblePages().includes(b.page));
    if (here.length) {
      await Promise.all(here.map((b) => api(`/bookmarks/${b.id}`, { method: "DELETE" })));
      this.bookmarks = this.bookmarks.filter((b) => !here.includes(b));
    } else {
      const mark = await api(`/books/${this.book.id}/bookmarks`, {
        method: "POST", body: { file_id: this.file.id, page: this.page },
      });
      this.bookmarks.push(mark);
      this.bookmarks.sort((a, b) => a.page - b.page);
    }
    this.markBookmarkButton();
    const panel = this.root.querySelector('.reader-panel[data-for="contents"]');
    if (!panel.hidden) this.drawContents(panel);
  }

  drawContents(panel) {
    const toc = this.m.toc.length ? this.m.toc
      : Array.from({ length: Math.ceil(this.count / 10) }, (_, k) => ({ title: `Page ${k * 10 + 1}`, page: k * 10, level: 0 }));
    panel.innerHTML = `
      <h2>Contents</h2>
      <ol class="toc">${toc.map((t) => `<li style="--level:${Math.min(t.level, 4)}">
        <button type="button" data-go="${t.page}"><span>${esc(t.title)}</span><span class="toc-page">${t.page + 1}</span></button></li>`).join("")}</ol>
      <h2>Bookmarks</h2>
      ${this.bookmarks.length ? `<ol class="toc marks">${this.bookmarks.map((b) => `<li>
        <button type="button" data-go="${b.page}"><span>Page ${b.page + 1}${b.note ? ` · ${esc(b.note)}` : ""}</span></button>
        <button type="button" class="icon-btn" data-unmark="${b.id}" aria-label="Remove bookmark on page ${b.page + 1}">×</button></li>`).join("")}</ol>`
        : `<p class="muted">Tap the bookmark at the top to keep your place on a page.</p>`}`;
    panel.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => {
      this.goTo(Number(b.dataset.go));
      this.closePanels();
    }));
    panel.querySelectorAll("[data-unmark]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/bookmarks/${b.dataset.unmark}`, { method: "DELETE" });
      this.bookmarks = this.bookmarks.filter((m) => String(m.id) !== b.dataset.unmark);
      this.markBookmarkButton();
      this.drawContents(panel);
    }));
  }

  // ---------- reading settings ----------

  drawPrefs(panel) {
    const r = this.reading;
    const seg = (key, options) => `<div class="segmented" role="radiogroup">${options.map(([v, label]) =>
      `<button type="button" role="radio" aria-checked="${r[key] === v}" data-set="${key}" data-value="${v}">${label}</button>`).join("")}</div>`;
    const sw = (key, label) => `<label class="switch"><input type="checkbox" data-toggle="${key}" ${r[key] ? "checked" : ""}><span>${label}</span></label>`;
    panel.innerHTML = `
      <h2>Reading</h2>
      <h3>Colours</h3>
      <div class="swatches" role="radiogroup">${[["dark", "Dark"], ["sepia", "Sepia"], ["white", "White"], ["black", "Black"]].map(([v, label]) =>
        `<button type="button" role="radio" class="swatch swatch-${v}" aria-checked="${r.theme === v}" data-set="theme" data-value="${v}"><span>${label}</span></button>`).join("")}</div>
      <h3>Pages</h3>
      ${seg("mode", [["pages", "Turn pages"], ["scroll", "Scroll"]])}
      <h3>Page turn</h3>
      ${seg("turn_speed", [["gentle", "Gentle"], ["normal", "Normal"], ["quick", "Quick"], ["off", "Instant"]])}
      ${sw("spread", "Two pages side by side when there’s room")}
      ${sw("left_handed", "Left-handed: tap the left edge to go forward")}`;
    panel.querySelectorAll("[data-set]").forEach((b) => b.addEventListener("click", () => this.setPref(b.dataset.set, b.dataset.value, panel)));
    panel.querySelectorAll("[data-toggle]").forEach((c) => c.addEventListener("change", () => this.setPref(c.dataset.toggle, c.checked, panel)));
  }

  async setPref(key, value, panel) {
    const before = { ...this.reading };
    this.reading[key] = value;
    if (key === "theme") this.root.dataset.theme = value;
    if (key === "turn_speed" && this.flip) this.flip.getSettings().flippingTime = SPEEDS[value];
    if (key === "mode" || key === "spread") this.build();
    this.drawPrefs(panel);
    try {
      await patchPrefs({ reading: { [key]: value } });
    } catch {
      this.reading = before;
      this.root.dataset.theme = before.theme;
      this.drawPrefs(panel);
    }
  }
}
