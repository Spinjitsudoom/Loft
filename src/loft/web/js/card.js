// Your library card: what you have checked out now, and what you've returned (finished, abandoned
// or given back early), newest first. Opening a book checks it out; finishing it returns it.
import { api, authorLine, esc } from "./api.js";
import { coverHTML } from "./cover.js";

const HOW = { finished: "Finished", abandoned: "Abandoned", returned: "Returned early" };

function day(at, withYear) {
  return new Date(at * 1000).toLocaleDateString(undefined, withYear ? { day: "numeric", month: "long", year: "numeric" } : { day: "numeric", month: "long" });
}

/** "3 – 20 November", "28 October – 2 November", or with years when they aren't this one. */
export function spanText(from, to) {
  const a = new Date(from * 1000), b = new Date(to * 1000);
  const thisYear = new Date().getFullYear();
  const years = a.getFullYear() !== b.getFullYear() || b.getFullYear() !== thisYear;
  if (!years && a.getMonth() === b.getMonth() && a.getDate() !== b.getDate()) {
    return `${a.getDate()} – ${day(to, false)}`;
  }
  if (!years && a.getMonth() === b.getMonth()) return day(to, false);
  return `${day(from, years)} – ${day(to, years)}`;
}

function rowHTML(b, note) {
  return `<li><a class="card-row" href="#/book/${b.id}">
    <span class="card-cover">${coverHTML(b, 240)}</span>
    <span class="card-text"><strong>${esc(b.title)}</strong>
      ${b.authors && b.authors.length ? `<span class="muted">${esc(authorLine(b.authors))}</span>` : ""}
      <span class="card-note">${note}</span></span></a></li>`;
}

export async function renderCard(main) {
  const { out, returned } = await api("/me/loans");
  const thisYear = new Date().getFullYear();
  main.innerHTML = `<section class="page narrow library-card">
    <header class="page-head"><h1>Your library card</h1>
      <p class="muted">Opening a book checks it out. Finishing it returns it, and so does leaving it unread for 30 days.</p></header>
    <h2>Checked out</h2>
    ${out.length ? `<ul class="card-list">${out.map((b) =>
      rowHTML(b, `Since ${esc(day(b.out_at, new Date(b.out_at * 1000).getFullYear() !== thisYear))}`)).join("")}</ul>`
      : `<p class="muted">Nothing checked out. Open a book to check it out.</p>`}
    <h2>Returned</h2>
    ${returned.length ? `<ul class="card-list">${returned.map((b) =>
      rowHTML(b, `${esc(spanText(b.out_at, b.returned_at))} · ${esc(HOW[b.how] || "Returned")}`)).join("")}</ul>`
      : `<p class="muted">Books you finish or return show here.</p>`}
  </section>`;
}
