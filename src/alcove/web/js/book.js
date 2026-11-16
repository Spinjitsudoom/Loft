// A book's own page.
import { api, authorLine, esc, icon, seriesLine } from "./api.js";
import { coverHTML } from "./cover.js";
import { shelfHTML, wireShelves } from "./home.js";

function size(bytes) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function link(kind, value, label = value) {
  return `<a href="#/all?kind=${kind}&value=${encodeURIComponent(value)}&title=${encodeURIComponent(value)}">${esc(label)}</a>`;
}

export async function renderBook(main, id) {
  const b = await api(`/books/${id}`);
  const authors = b.authors.map((a) => link("author", a)).join(" and ");
  const paragraphs = (b.description || "").split(/\n{2,}/).filter(Boolean)
    .map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("");
  const facts = [
    b.publisher && ["Publisher", esc(b.publisher)],
    b.published && ["Published", esc(new Date(b.published).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }))],
    b.language && ["Language", esc(b.language)],
  ].filter(Boolean);

  main.innerHTML = `<article class="book-page" style="--glow: ${esc(b.color || "#3a2a1e")}">
    <div class="book-page-cover">${coverHTML(b, 480, "book-thick")}</div>
    <div class="book-page-text">
      <h1 class="book-page-title">${esc(b.title)}</h1>
      ${authors ? `<p class="book-page-author">${authors}</p>` : ""}
      ${b.series ? `<p class="book-page-series">${link("series", b.series, seriesLine(b))}</p>` : ""}
      <div class="files">
        ${b.files.map((f) => `<a class="btn ${f === b.files[0] ? "btn-primary" : ""}" href="/api/files/${f.id}" download>
          ${icon("download")}Download ${esc(f.format.toUpperCase())}<span class="file-size">${size(f.size)}</span></a>`).join("")}
      </div>
      ${paragraphs ? `<div class="description">${paragraphs}</div>` : ""}
      ${facts.length ? `<dl class="facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>` : ""}
      ${b.tags.length ? `<ul class="tags">${b.tags.map((t) => `<li>${link("tag", t)}</li>`).join("")}</ul>` : ""}
    </div>
  </article>
  ${b.series_books.length ? shelfHTML({ title: `More in ${b.series}`, kind: "series", value: b.series, books: b.series_books }) : ""}`;
  wireShelves(main);
}
