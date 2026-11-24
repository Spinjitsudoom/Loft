// The stacks: the whole library as bookcases, signed by series, section or author, with books
// standing spine-out (or face-out). One bar on top chooses how to shelve and narrows what's shown;
// on a phone its filters fold behind one button. Tap a spine and the book slides out.
import { api, authorLine, esc, seriesLine } from "./api.js";
import { coverHTML } from "./cover.js";
import { spineTitle } from "./titles.js";
import { STATUS_LABELS as STATUS } from "./statusmenu.js";
import { LINE_HEIGHT, fitTitle, hash, spineColours } from "./spines.js";

const KEPT = "loft-stacks";
const BY = [["series", "Series"], ["section", "Sections"], ["author", "Authors"]];
const FORMATS = { pdf: "PDF", epub: "EPUB", cbz: "Comic (CBZ)", cbr: "Comic (CBR)", cb7: "Comic (CB7)",
  mobi: "Kindle (MOBI)", azw: "Kindle (AZW)", azw3: "Kindle (AZW3)", fb2: "FB2", txt: "Text" };
const FILTERS = ["status", "section", "author", "format"];

function remembered() {
  try { return JSON.parse(localStorage.getItem(KEPT) || "{}"); } catch { return {}; }
}

// Thicker for longer books: pages when Loft knows them, else the file's size.
function thickness(b) {
  if (b.pages) return Math.round(Math.min(46, Math.max(13, 9 + b.pages / 9)));
  const mb = (b.size || 0) / 1e6;
  return Math.round(Math.min(40, Math.max(14, 14 + Math.log2(Math.max(1, mb)) * 4)));
}


const number = (i) => (i == null ? "" : String(i).replace(/\.0$/, ""));

// A bound spine: cloth in the cover's main colour, two ribs, and the title on a label in its second.
function spineHTML(b, inSeries = false) {
  const { c, label, letter, trim } = spineColours(b);
  const tall = 84 + (hash(b.id) % 15);  // a real shelf is never all one height
  const reading = b.progress && !b.progress.finished;
  return `<button type="button" class="spine${reading ? " is-reading" : ""}" data-book="${b.id}" aria-expanded="false"
      style="--c:${esc(c)};--label:${esc(label)};--letter:${letter};--trim:${trim};--w:${thickness(b)}px;--tall:${tall}%"
      aria-label="${esc(b.title)}${b.authors.length ? `, by ${esc(authorLine(b.authors))}` : ""}${reading ? ", reading" : ""}">
    <span class="spine-rib spine-rib-top"></span><span class="spine-rib spine-rib-foot"></span>
    <span class="spine-orn" aria-hidden="true">✦</span>
    <span class="spine-label"></span>
    <span class="spine-title">${esc(spineTitle(b, inSeries))}</span>
    ${b.series_index ? `<span class="spine-no">${esc(number(b.series_index))}</span>` : ""}
  </button>`;
}

// Every title at the largest size at which it fits its label. Sizes come from one layout read (a
// spine's height, so the row's) and a canvas, so a long shelf costs no extra layout.
const LABEL_TOP = 0.15, LABEL_FOOT = 0.18;
const FONT = "Literata";
let pen = null;
// Measured at the size itself, not scaled: Literata's letters are wider at small (optical) sizes.
const textWidths = new Map();
function measure(text, size) {
  const key = `${size} ${text}`;
  let w = textWidths.get(key);
  if (w === undefined) {
    pen ||= document.createElement("canvas").getContext("2d");
    pen.font = `600 ${size}px ${FONT}`;
    w = pen.measureText(text).width;
    textWidths.set(key, w);
  }
  return w;
}

async function fitSpines(main) {
  const spines = [...main.querySelectorAll(".spine")];
  if (!spines.length) return;
  try {
    await document.fonts.load(`600 12px ${FONT}`);
    await document.fonts.ready;
  } catch { /* measured with whatever font there is */ }
  if (!spines[0].isConnected) return;
  const tall = (s) => parseFloat(s.style.getPropertyValue("--tall")) / 100;
  const row = spines[0].offsetHeight / tall(spines[0]);
  if (!row) return;
  textWidths.clear();  // the font may have arrived since the last fitting
  for (const s of spines) {
    const t = s.querySelector(".spine-title");
    const width = parseFloat(s.style.getPropertyValue("--w"));
    const { size, lines, fits } = fitTitle(t.textContent, row * tall(s) * (1 - LABEL_TOP - LABEL_FOOT), width, measure);
    const block = (fits ? lines : 1) * size * LINE_HEIGHT;  // a title that can't fit: one line, cut short
    t.style.setProperty("--fs", `${size}px`);
    Object.assign(t.style, { width: `${block}px`, left: `${(width - block) / 2}px`, right: "auto", whiteSpace: fits ? "" : "nowrap" });
  }
}

function faceHTML(b) {
  return `<a class="face" href="#/book/${b.id}" title="${esc(b.title)}">${coverHTML(b, 240)}</a>`;
}

function pulledHTML(b) {
  const reading = b.progress && !b.progress.finished;
  return `<div class="pulled" data-pulled="${b.id}">
    <a class="pulled-cover" href="#/book/${b.id}" tabindex="-1">${coverHTML(b, 240)}</a>
    <div class="pulled-text">
      <strong>${esc(b.title)}</strong>
      ${b.authors.length ? `<span>${esc(authorLine(b.authors))}</span>` : ""}
      ${b.series ? `<span class="muted">${esc(seriesLine(b))}</span>` : ""}
      ${reading ? `<span class="muted">Page ${b.progress.page + 1} of ${b.progress.pages}</span>` : ""}
      <span class="pulled-actions">
        <a class="btn btn-small btn-primary" href="#/read/${b.id}">${reading ? "Continue" : b.progress ? "Read again" : "Read"}</a>
        <a class="btn btn-small" href="#/book/${b.id}">About</a>
      </span>
    </div>
  </div>`;
}

// On lettered shelves (and the books in no series) a name card stands where one author's books begin.
function shelfHTML(c, view) {
  const one = view === "covers" ? (b) => faceHTML(b) : (b) => spineHTML(b, c.kind === "series");
  if (c.kind !== "letter" && c.kind !== "loose") return c.books.map(one).join("");
  let last = null;
  return c.books.map((b) => {
    const who = b.authors[0] || "No author";
    const card = who !== last ? `<span class="divider" aria-hidden="true"><span>${esc(who)}</span></span>` : "";
    last = who;
    return card + one(b);
  }).join("");
}

function caseLink(c) {
  if (c.kind === "series") return `#/all?kind=series&value=${encodeURIComponent(c.title)}&title=${encodeURIComponent(c.title)}`;
  if (c.kind === "author" && c.title !== "Unknown author") return `#/all?kind=author&value=${encodeURIComponent(c.title)}&title=${encodeURIComponent(c.title)}`;
  return "";
}

export async function renderStacks(main, params) {
  const kept = remembered();
  const pick = (k, fallback = "") => (params.has(k) ? params.get(k) : (kept[k] ?? fallback));
  const state = { by: pick("by", "series"), view: pick("view", "spines") };
  for (const f of FILTERS) state[f] = params.get(f) || "";
  if (!BY.some(([k]) => k === state.by)) state.by = "series";
  try { localStorage.setItem(KEPT, JSON.stringify({ by: state.by, view: state.view })); } catch { /* fine */ }

  const q = new URLSearchParams({ by: state.by });
  for (const f of FILTERS) if (state[f]) q.set(f, state[f]);
  const data = await api(`/stacks?${q}`);
  const active = FILTERS.filter((f) => state[f]).length;

  const go = (change) => {
    const next = { ...state, ...change };
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(next)) if (v) p.set(k, v);
    location.hash = `#/stacks?${p}`;
  };
  const select = (name, label, options) => `<label class="pick${state[name] ? " is-set" : ""}">
      <span class="pick-label">${label}</span>
      <select data-filter="${name}">
        <option value="">All</option>
        ${options.map(([v, text, n]) => `<option value="${esc(v)}" ${state[name] === v ? "selected" : ""} ${n === 0 && state[name] !== v ? "disabled" : ""}>${esc(text)}${n != null ? ` (${n})` : ""}</option>`).join("")}
      </select></label>`;
  const f = data.facets;

  main.innerHTML = `<section class="stacks">
    <header class="stacks-head">
      <h1>The stacks</h1>
      <p class="muted">${data.total} ${data.total === 1 ? "book" : "books"}${active ? " match" : " in the library"}</p>
    </header>
    <div class="stacks-bar">
      <div class="segmented" role="radiogroup" aria-label="Shelve by">${BY.map(([k, label]) =>
        `<button type="button" role="radio" aria-checked="${state.by === k}" data-by="${k}">${label}</button>`).join("")}</div>
      <button class="btn btn-small stacks-filter-toggle" type="button" data-toggle aria-expanded="false">
        Filters${active ? ` <span class="count">${active}</span>` : ""}</button>
      <div class="stacks-filters" data-filters>
        ${select("status", "Reading", Object.entries(STATUS).map(([k, label]) => [k, label, f.status[k]]))}
        ${select("section", "Section", Object.entries(f.section).map(([k, n]) => [k, k, n]))}
        ${select("author", "Author", Object.entries(f.author).map(([k, n]) => [k, k, n]))}
        ${Object.keys(f.format).length > 1 || state.format ? select("format", "Format", Object.entries(f.format).map(([k, n]) => [k, FORMATS[k] || k.toUpperCase(), n])) : ""}
        ${active ? `<button class="link-btn" type="button" data-clear>Clear filters</button>` : ""}
      </div>
      <div class="segmented stacks-view" role="radiogroup" aria-label="Show books">${[["spines", "Spines"], ["covers", "Covers"]].map(([k, label]) =>
        `<button type="button" role="radio" aria-checked="${state.view === k}" data-view="${k}">${label}</button>`).join("")}</div>
    </div>
    ${data.cases.length ? data.cases.map((c) => `<section class="case" aria-label="${esc(c.title)}" data-trail="${esc(c.title)}">
        <header class="case-sign">
          <h2>${esc(c.title)}</h2><span class="case-count">${c.count}</span>
          ${caseLink(c) ? `<a class="see-all" href="${caseLink(c)}">See all</a>` : ""}
        </header>
        <div class="case-shelf ${state.view === "covers" ? "is-faces" : ""}">
          <div class="case-row">${shelfHTML(c, state.view)}</div>
        </div>
      </section>`).join("")
      : active ? `<div class="empty"><p>No books match those filters.</p><button class="btn" type="button" data-clear>Clear filters</button></div>`
      : `<div class="empty"><p>The shelves are empty.</p><a class="btn" href="#/add">Add books</a></div>`}
  </section>`;

  const phone = matchMedia("(max-width: 700px)");  // where the rows are shorter
  const refit = () => fitSpines(main);
  if (state.view !== "covers") {
    fitSpines(main);
    phone.addEventListener("change", refit);
  }

  const books = new Map(data.cases.flatMap((c) => c.books).map((b) => [String(b.id), b]));
  main.querySelectorAll("[data-by]").forEach((b) => b.addEventListener("click", () => go({ by: b.dataset.by })));
  main.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => go({ view: b.dataset.view })));
  main.querySelectorAll("[data-filter]").forEach((s) => s.addEventListener("change", () => go({ [s.dataset.filter]: s.value })));
  main.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", () => go(Object.fromEntries(FILTERS.map((k) => [k, ""])))));
  const toggle = main.querySelector("[data-toggle]");
  toggle.addEventListener("click", () => {
    const open = main.querySelector("[data-filters]").classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", String(open));
  });

  // Tap a spine: the book slides out beside it; tap again (or another, or Escape) to put it back.
  const putBack = () => {
    main.querySelectorAll(".pulled").forEach((p) => {
      p.classList.remove("is-out");
      setTimeout(() => p.remove(), 260);
    });
    main.querySelectorAll(".spine[aria-expanded=true]").forEach((s) => s.setAttribute("aria-expanded", "false"));
  };
  main.addEventListener("click", (e) => {
    const spine = e.target.closest(".spine");
    if (!spine) return;
    const wasOut = spine.getAttribute("aria-expanded") === "true";
    putBack();
    if (wasOut) return;
    spine.setAttribute("aria-expanded", "true");
    spine.insertAdjacentHTML("afterend", pulledHTML(books.get(spine.dataset.book)));
    const pulled = spine.nextElementSibling;
    requestAnimationFrame(() => {
      pulled.classList.add("is-out");
      setTimeout(() => pulled.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" }), 200);
    });
  });
  const onKey = (e) => { if (e.key === "Escape") putBack(); };
  document.addEventListener("keydown", onKey);
  window.addEventListener("hashchange", () => {
    document.removeEventListener("keydown", onKey);
    phone.removeEventListener("change", refit);
  }, { once: true });
}
