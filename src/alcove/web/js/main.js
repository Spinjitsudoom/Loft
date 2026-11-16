// Alcove's web app: a small hash router that draws one screen at a time into #app.
import { api, esc, icon } from "./api.js";
import { renderLogin } from "./login.js";
import { renderHome } from "./home.js";
import { renderGrid } from "./grid.js";
import { renderBook } from "./book.js";
import { renderAdmin } from "./admin.js";
import { renderReader } from "./reader.js";

const app = document.getElementById("app");
export const state = { me: null };

function topbar(query = "") {
  return `<header class="topbar">
    <a class="brand" href="#/">Alcove</a>
    <form class="search" role="search" data-search>
      ${icon("search")}
      <input type="search" name="q" value="${esc(query)}" placeholder="Search books" aria-label="Search the library" autocomplete="off">
    </form>
    <nav class="top-actions">
      ${state.me && state.me.admin ? `<a class="icon-btn" href="#/admin" title="Library settings" aria-label="Library settings">${icon("gear")}</a>` : ""}
      <button class="icon-btn" type="button" data-signout title="Sign out" aria-label="Sign out">${icon("out")}</button>
    </nav>
  </header>`;
}

function parse() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = raw.split("?");
  return { parts: path.split("/").filter(Boolean), params: new URLSearchParams(qs || "") };
}

let renderToken = 0;
let cleanup = null;

async function route() {
  const token = ++renderToken;
  const { parts, params } = parse();
  const [page, arg] = parts;
  if (cleanup) { cleanup(); cleanup = null; }

  if (page === "login" || page === "setup") {
    return renderLogin(app, page === "setup");
  }
  if (!state.me) {
    try {
      const status = await api("/status");
      if (status.setup_needed) { location.hash = "#/setup"; return; }
      state.me = await api("/me");
    } catch {
      location.hash = "#/login";
      return;
    }
  }
  if (token !== renderToken) return;

  if (page === "read" && arg) {
    try {
      const done = await renderReader(app, Number(arg), params);
      if (token === renderToken) cleanup = done; else done();
    } catch (e) {
      if (e.status !== 401) app.innerHTML = `<main class="reader-message"><div><p>${esc(e.message)}</p><a class="btn" href="#/">Back to the library</a></div></main>`;
    }
    return;
  }

  const query = page === "search" ? params.get("q") || "" : "";
  app.innerHTML = `${topbar(query)}<main id="main" tabindex="-1"></main>`;
  const main = app.querySelector("#main");
  wireTopbar();
  window.scrollTo(0, 0);

  try {
    if (!page) await renderHome(main);
    else if (page === "book" && arg) await renderBook(main, Number(arg));
    else if (page === "all") await renderGrid(main, { kind: params.get("kind"), value: params.get("value"), title: params.get("title") });
    else if (page === "search") await renderGrid(main, { query });
    else if (page === "admin" && state.me.admin) await renderAdmin(main);
    else main.innerHTML = `<div class="empty"><p>There’s nothing here.</p><a class="btn" href="#/">Back to the library</a></div>`;
  } catch (e) {
    if (e.status === 401) return;
    main.innerHTML = `<div class="empty"><p>${esc(e.message)}</p><button class="btn" type="button" onclick="location.reload()">Try again</button></div>`;
  }
}

function wireTopbar() {
  const form = app.querySelector("[data-search]");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = form.q.value.trim();
    if (q) location.hash = `#/search?q=${encodeURIComponent(q)}`;
  });
  app.querySelector("[data-signout]").addEventListener("click", async () => {
    await api("/logout", { method: "POST" }).catch(() => {});
    state.me = null;
    location.hash = "#/login";
  });
}

export function signedIn(user) {
  state.me = user;
  location.hash = "#/";
}

window.addEventListener("hashchange", route);
route();
