// Activity (admins only): what happened in the library, newest first, grouped by day. At the top,
// what's checked out now. Filters for a person and a kind; Show more loads older entries.
import { api, esc, icon } from "./api.js";

const DAY = 24 * 3600;

function midnight(at) {
  const d = new Date(at * 1000);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
}

/** "Today", "Yesterday", "Sunday 22 November", or with the year when it isn't this one. */
export function dayHeading(at, now = Date.now() / 1000) {
  const days = Math.round((midnight(now) - midnight(at)) / DAY);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  const d = new Date(at * 1000);
  const year = d.getFullYear() !== new Date(now * 1000).getFullYear();
  const weekday = d.toLocaleDateString("en-GB", { weekday: "long" });
  const date = d.toLocaleDateString("en-GB", year ? { day: "numeric", month: "long", year: "numeric" } : { day: "numeric", month: "long" });
  return `${weekday} ${date}`;
}

const time = (at) => new Date(at * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

function who(e) {
  if (!e.user) return `<span class="act-who is-loft">Loft</span>`;
  return `<span class="act-who">${esc(e.user.name || "Someone")}</span>`;
}

function what(e) {
  const book = e.book ? (e.book.exists ? ` <a href="#/book/${e.book.id}">${esc(e.book.title)}</a>`
    : ` <span class="act-gone">${esc(e.book.title)}</span>`) : "";
  const fields = e.details && Array.isArray(e.details.fields) && e.details.fields.length
    ? ` <span class="muted">(${esc(e.details.fields.join(", "))})</span>` : "";
  const after = e.details && e.details.after ? ` <span class="act-after">${esc(e.details.after)}</span>` : "";
  return `${esc(e.text)}${book}${after}${fields}`;
}

function entriesHTML(entries, lastDay) {
  let day = lastDay;
  return entries.map((e) => {
    const heading = dayHeading(e.at);
    const head = heading !== day ? `<li class="act-day"><h2>${esc(heading)}</h2></li>` : "";
    day = heading;
    return `${head}<li class="act-entry"><time datetime="${new Date(e.at * 1000).toISOString()}">${time(e.at)}</time>
      <span>${who(e)} ${what(e)}</span></li>`;
  }).join("");
}

function outNowHTML(out) {
  if (!out || !out.length) return `<p class="muted">Nothing is checked out right now.</p>`;
  const people = out.reduce((n, o) => n + o.people.length, 0);
  return `<details class="act-out"><summary><strong>${out.length} ${out.length === 1 ? "book is" : "books are"} checked out</strong>
      <span class="muted">${people === out.length ? "" : `(${people} loans)`}</span></summary>
    <ul>${out.map((o) => `<li><a href="#/book/${o.book.id}">${esc(o.book.title)}</a>
      <span class="muted">${esc(o.people.join(", "))}</span></li>`).join("")}</ul></details>`;
}

export async function renderActivity(main, params = new URLSearchParams()) {
  const user = params.get("user") || "";
  const group = params.get("group") || "";
  const query = (before) => `/activity?${new URLSearchParams(Object.entries({ user, group, before: before ?? "" })
    .filter(([, v]) => v !== ""))}`;
  const first = await api(query());
  main.innerHTML = `<section class="page narrow activity-page">
    <header class="page-head"><h1>Activity</h1>
      <p class="muted">What happened in the library, newest first. Kept for a year. <a href="#/admin">Library settings</a></p></header>
    ${"out_now" in first ? `<div class="act-top">${outNowHTML(first.out_now)}</div>` : ""}
    <div class="act-filters">
      <label>Person <select data-filter="user"><option value="">Everyone</option>${first.people.map((p) =>
        `<option value="${p.id}"${String(p.id) === user ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
      <label>Kind <select data-filter="group"><option value="">Everything</option>${Object.entries(first.groups).map(([k, label]) =>
        `<option value="${k}"${k === group ? " selected" : ""}>${esc(label)}</option>`).join("")}</select></label>
    </div>
    ${first.entries.length ? `<ol class="act-list">${entriesHTML(first.entries, null)}</ol>`
      : `<div class="empty"><p>${user || group ? "Nothing like that has happened yet." : "Nothing has happened yet. Sign-ins, new books, loans and the like show here."}</p></div>`}
    ${first.more ? `<button class="btn" type="button" data-more>Show more</button>` : ""}
  </section>`;

  main.querySelectorAll("[data-filter]").forEach((s) => s.addEventListener("change", () => {
    const next = new URLSearchParams({ user, group, [s.dataset.filter]: s.value });
    [...next.keys()].forEach((k) => { if (!next.get(k)) next.delete(k); });
    location.hash = `#/activity${next.toString() ? `?${next}` : ""}`;
  }));

  let entries = first.entries;
  const more = main.querySelector("[data-more]");
  more?.addEventListener("click", async () => {
    more.disabled = true;
    try {
      const page = await api(query(entries[entries.length - 1].id));
      const lastDay = dayHeading(entries[entries.length - 1].at);
      main.querySelector(".act-list").insertAdjacentHTML("beforeend", entriesHTML(page.entries, lastDay));
      entries = entries.concat(page.entries);
      if (page.more) more.disabled = false;
      else more.remove();
    } catch (e) {
      more.disabled = false;
      more.insertAdjacentHTML("afterend", `<p class="form-error" role="alert">${esc(e.message)}</p>`);
    }
  });
}

export function activityLinkHTML() {
  return `<a class="check-link quiet" href="#/activity">
      ${icon("list")}<span><strong>Activity</strong>
      <span class="muted">Who did what: sign-ins, new books, loans, ratings and more</span></span>
      ${icon("right")}</a>`;
}
