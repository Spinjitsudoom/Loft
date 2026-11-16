// The cover wall: a lamplit book at the top, then shelves of covers.
import { api, authorLine, esc, icon, seriesLine } from "./api.js";
import { coverHTML } from "./cover.js";

export function shelfItem(book) {
  return `<li class="shelf-item">
    <a href="#/book/${book.id}" class="shelf-link">
      ${coverHTML(book, 240)}
      <span class="shelf-title">${esc(book.title)}</span>
      <span class="shelf-author">${esc(authorLine(book.authors))}</span>
    </a>
  </li>`;
}

function allLink(row) {
  if (row.kind === "recent") return "#/all?sort=added&title=Recently%20added";
  return `#/all?kind=${row.kind}&value=${encodeURIComponent(row.value)}&title=${encodeURIComponent(row.title)}`;
}

export function shelfHTML(row) {
  return `<section class="shelf" aria-label="${esc(row.title)}">
    <header class="shelf-head">
      <h2>${esc(row.title)}</h2>
      <a class="see-all" href="${allLink(row)}">See all</a>
    </header>
    <div class="shelf-frame">
      <button class="shelf-arrow prev" type="button" aria-label="Scroll left" tabindex="-1">${icon("left")}</button>
      <ul class="shelf-row">${row.books.map(shelfItem).join("")}</ul>
      <button class="shelf-arrow next" type="button" aria-label="Scroll right" tabindex="-1">${icon("right")}</button>
    </div>
  </section>`;
}

export function wireShelves(root) {
  for (const frame of root.querySelectorAll(".shelf-frame")) {
    const row = frame.querySelector(".shelf-row");
    const update = () => {
      frame.classList.toggle("at-start", row.scrollLeft < 8);
      frame.classList.toggle("at-end", row.scrollLeft + row.clientWidth > row.scrollWidth - 8);
    };
    frame.querySelector(".prev").addEventListener("click", () => row.scrollBy({ left: -row.clientWidth * 0.85, behavior: "smooth" }));
    frame.querySelector(".next").addEventListener("click", () => row.scrollBy({ left: row.clientWidth * 0.85, behavior: "smooth" }));
    row.addEventListener("scroll", update, { passive: true });
    update();
  }
}

function heroHTML(book, detail) {
  const description = (detail && detail.description) || "";
  const firstFile = detail && detail.files && detail.files[0];
  return `<section class="hero" style="--glow: ${esc(book.color || "#3a2a1e")}">
    <a class="hero-cover" href="#/book/${book.id}" aria-label="${esc(book.title)}">${coverHTML(book, 480, "book-thick")}</a>
    <div class="hero-text">
      <p class="hero-label">Newly shelved</p>
      <h1 class="hero-title">${esc(book.title)}</h1>
      <p class="hero-author">${esc(authorLine(book.authors))}</p>
      ${book.series ? `<p class="hero-series">${esc(seriesLine(book))}</p>` : ""}
      ${description ? `<p class="hero-blurb">${esc(description.split("\n\n")[0])}</p>` : ""}
      <div class="hero-actions">
        <a class="btn btn-primary" href="#/book/${book.id}">Open book</a>
        ${firstFile ? `<a class="btn" href="/api/files/${firstFile.id}" download>${icon("download")}Download ${esc(firstFile.format.toUpperCase())}</a>` : ""}
      </div>
    </div>
  </section>`;
}

export async function renderHome(main) {
  const home = await api("/home");
  if (!home.hero) {
    main.innerHTML = `<div class="empty"><h1>Your shelves are empty</h1>
      <p>Alcove shows the books in the folders set in <code>config.toml</code>. Add books there, then rescan from library settings.</p>
      <a class="btn" href="#/admin">Library settings</a></div>`;
    return;
  }
  const detail = await api(`/books/${home.hero.id}`).catch(() => null);
  main.innerHTML = heroHTML(home.hero, detail) + home.rows.map(shelfHTML).join("");
  wireShelves(main);
}
