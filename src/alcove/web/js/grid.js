// Every book on one shelf, or a search: a grid of covers that loads more as you scroll.
import { api, authorLine, esc } from "./api.js";
import { coverHTML } from "./cover.js";

const PAGE = 60;

function gridItem(book) {
  return `<li><a href="#/book/${book.id}" class="grid-link">
    ${coverHTML(book, 240)}
    <span class="shelf-title">${esc(book.title)}</span>
    <span class="shelf-author">${esc(authorLine(book.authors))}</span>
  </a></li>`;
}

export async function renderGrid(main, { kind, value, title, query }) {
  const sort = new URLSearchParams(location.hash.split("?")[1] || "").get("sort") || "title";
  if (query !== undefined) {
    const books = await api(`/search?q=${encodeURIComponent(query)}`);
    main.innerHTML = `<section class="page">
      <header class="page-head"><h1>${books.length ? `Results for “${esc(query)}”` : `Nothing matches “${esc(query)}”`}</h1>
      ${books.length ? "" : `<p class="muted">Try part of a title, an author’s surname or a series name.</p>`}</header>
      <ul class="grid">${books.map(gridItem).join("")}</ul></section>`;
    return;
  }

  const base = `/books?sort=${sort}${kind ? `&kind=${encodeURIComponent(kind)}&value=${encodeURIComponent(value || "")}` : ""}`;
  const first = await api(`${base}&offset=0&limit=${PAGE}`);
  const heading = title || "All books";
  main.innerHTML = `<section class="page">
    <header class="page-head"><h1>${esc(heading)}</h1>
      <p class="muted">${first.total} ${first.total === 1 ? "book" : "books"}</p></header>
    <ul class="grid">${first.books.map(gridItem).join("")}</ul>
    <div class="grid-more" aria-hidden="true"></div>
  </section>`;

  const list = main.querySelector(".grid");
  let loaded = first.books.length;
  let busy = false;
  const sentinel = main.querySelector(".grid-more");
  if (loaded >= first.total) return;
  const observer = new IntersectionObserver(async ([entry]) => {
    if (!entry.isIntersecting || busy || !document.body.contains(sentinel)) return;
    busy = true;
    const next = await api(`${base}&offset=${loaded}&limit=${PAGE}`);
    list.insertAdjacentHTML("beforeend", next.books.map(gridItem).join(""));
    loaded += next.books.length;
    busy = false;
    if (loaded >= next.total || !next.books.length) observer.disconnect();
  }, { rootMargin: "600px" });
  observer.observe(sentinel);
}
