// Library settings, for admins: the library itself, its folders and scanning, and the people in it.
import { api, esc, icon } from "./api.js";
import { state } from "./main.js";
import { saved } from "./settings.js";

const INTERVALS = [[5, "5 minutes"], [10, "10 minutes"], [30, "30 minutes"], [60, "hour"], [360, "6 hours"], [1440, "day"]];

function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} minutes ago`;
  if (s < 129600) return `${Math.round(s / 3600)} hours ago`;
  return `${Math.round(s / 86400)} days ago`;
}

function scanText(scan) {
  if (scan.running) return "Scanning…";
  const r = scan.report;
  if (!r) return "Alcove checks the folders for new, changed and removed books every few minutes.";
  const counts = !r.added && !r.updated && !r.removed ? "everything was already up to date"
    : `${r.added} added, ${r.updated} updated, ${r.removed} removed`;
  const trouble = r.unreachable.length + r.unreadable.length;
  return `Last scan ${ago(r.at)}: ${counts}.${trouble ? ` ${trouble} ${trouble === 1 ? "folder" : "folders"} couldn’t be read (see the library check).` : ""}`;
}

export async function renderAdmin(main) {
  const [users, scan, lib, check] = await Promise.all([api("/users"), api("/scan"), api("/library"), api("/check")]);
  const admins = users.filter((u) => u.admin).length;
  const attention = check.items.length;
  const interval = INTERVALS.some(([m]) => m === lib.scan_interval_minutes) ? INTERVALS
    : [...INTERVALS, [lib.scan_interval_minutes, `${lib.scan_interval_minutes} minutes`]].sort((a, b) => a[0] - b[0]);

  main.innerHTML = `<section class="page narrow">
    <header class="page-head"><h1>Library settings</h1></header>

    <a class="check-link ${attention ? "" : "quiet"}" href="#/check">
      ${icon("check")}<span><strong>Library check</strong>
      <span class="muted">${attention ? `${attention} ${attention === 1 ? "thing needs" : "things need"} attention` : "Nothing needs attention"}</span></span>
      ${icon("right")}</a>

    <section class="panel">
      <h2>The library</h2>
      <form class="inline-form" data-name novalidate>
        <label>Name<input name="name" value="${esc(lib.name)}" placeholder="Alcove" maxlength="40" autocomplete="off"></label>
        <button class="btn" type="submit">Save name</button>
      </form>
      <p class="field-hint">Shown at the top of every page and on the sign-in page.</p>
      <label class="switch"><input type="checkbox" data-lib="allow_txt" ${lib.allow_txt ? "checked" : ""}>
        <span>Show plain-text (.txt) files as books</span></label>
      <p class="field-hint indent">Off by default: a notes or passwords file in the books folder would show up for everyone.</p>
      <label class="switch"><input type="checkbox" data-lib="online_lookups" ${lib.online_lookups ? "checked" : ""}>
        <span>Look up details and covers on Open Library</span></label>
      <p class="field-hint indent">Sends only titles, authors and ISBNs, and only when you ask for a lookup.</p>
    </section>

    <section class="panel">
      <h2>Books folders</h2>
      <ul class="folders">${lib.books_dirs.map((d) => `<li>
        <code>${esc(d)}</code>
        <span class="folder-actions">
          ${d === lib.upload_dir ? `<span class="badge">New books go here</span>`
            : `<button class="btn btn-small" type="button" data-upload-dir="${esc(d)}">Put new books here</button>`}
          ${lib.books_dirs.length > 1 ? `<button class="btn btn-small" type="button" data-remove-dir="${esc(d)}">Remove</button>` : ""}
        </span></li>`).join("")}</ul>
      <form class="inline-form" data-add-dir novalidate>
        <label>Add a folder<input name="path" placeholder="/path/to/more/books" autocomplete="off" spellcheck="false"></label>
        <button class="btn" type="submit">Add folder</button>
      </form>
      <p class="form-error" data-dir-error role="alert" hidden></p>
      <h3>Scanning</h3>
      <div class="scan-row">
        <label class="select-label">Look for changes every
          <select data-interval>${interval.map(([m, label]) => `<option value="${m}" ${m === lib.scan_interval_minutes ? "selected" : ""}>${label}</option>`).join("")}</select></label>
        <button class="btn" type="button" data-rescan>Rescan now</button>
      </div>
      <p class="muted scan-status" data-scan-status>${scanText(scan)}</p>
    </section>

    <section class="panel">
      <h2>People</h2>
      <ul class="people">${users.map((u) => `<li data-user="${u.id}">
        <span class="person">${esc(u.username)}${u.admin ? ` <span class="badge">Admin</span>` : ""}${u.id === state.me.id ? ` <span class="muted">(you)</span>` : ""}</span>
        <span class="person-actions">
          ${u.admin
            ? (admins > 1 ? `<button class="btn btn-small" type="button" data-admin="false">Make member</button>` : "")
            : `<button class="btn btn-small" type="button" data-admin="true">Make admin</button>`}
          ${u.id === state.me.id ? "" : `<button class="btn btn-small" type="button" data-reset>Reset password</button>
          <button class="btn btn-small" type="button" data-remove data-name="${esc(u.username)}">Remove</button>`}
        </span>
        <form class="reset-form" novalidate hidden>
          <label>New password for ${esc(u.username)}<input name="password" type="text" autocomplete="new-password" minlength="6"></label>
          <button class="btn btn-primary btn-small" type="submit">Set password</button>
          <p class="form-error" role="alert" hidden></p>
        </form>
      </li>`).join("")}</ul>
      <p class="form-error" data-people-error role="alert" hidden></p>
      <form class="add-person" novalidate>
        <h3>Add a person</h3>
        <div class="row">
          <label>Name<input name="username" autocomplete="off" required></label>
          <label>Password<input name="password" type="text" autocomplete="new-password" required></label>
          <button class="btn btn-primary" type="submit">Add person</button>
        </div>
        <p class="form-error" role="alert" hidden></p>
      </form>
    </section>
  </section>`;

  const fail = (el, message) => { el.textContent = message; el.hidden = false; };
  const patch = async (body, errorBox) => {
    try {
      const updated = await api("/library", { method: "PATCH", body });
      saved();
      return updated;
    } catch (e) {
      if (errorBox) fail(errorBox, e.message); else saved(e.message);
      return null;
    }
  };

  main.querySelector("[data-name]").addEventListener("submit", async (e) => {
    e.preventDefault();
    const updated = await patch({ name: e.target.name.value });
    if (updated) {
      state.libraryName = updated.name;
      const brand = document.querySelector(".brand");
      if (brand) brand.textContent = updated.name || "Alcove";
      document.title = updated.name || "Alcove";
    }
  });
  main.querySelectorAll("[data-lib]").forEach((c) => c.addEventListener("change", async () => {
    if (!(await patch({ [c.dataset.lib]: c.checked }))) c.checked = !c.checked;
  }));

  const dirError = main.querySelector("[data-dir-error]");
  main.querySelectorAll("[data-upload-dir]").forEach((b) => b.addEventListener("click", async () => {
    if (await patch({ upload_dir: b.dataset.uploadDir }, dirError)) renderAdmin(main);
  }));
  main.querySelectorAll("[data-remove-dir]").forEach((b) => b.addEventListener("click", async () => {
    const dir = b.dataset.removeDir;
    if (!confirm(`Take ${dir} out of the library?\n\nIts books leave Alcove, along with everyone’s reading progress, bookmarks and shelf places in them. The files themselves aren’t touched.`)) return;
    if (await patch({ books_dirs: lib.books_dirs.filter((d) => d !== dir) }, dirError)) renderAdmin(main);
  }));
  main.querySelector("[data-add-dir]").addEventListener("submit", async (e) => {
    e.preventDefault();
    dirError.hidden = true;
    const path = e.target.path.value.trim();
    if (!path) return;
    if (await patch({ books_dirs: [...lib.books_dirs, path] }, dirError)) {
      await api("/scan", { method: "POST" }).catch(() => {});
      renderAdmin(main);
    }
  });
  main.querySelector("[data-interval]").addEventListener("change", (e) => patch({ scan_interval_minutes: Number(e.target.value) }));

  main.querySelector("[data-rescan]").addEventListener("click", async (e) => {
    e.target.disabled = true;
    await api("/scan", { method: "POST" });
    const status = main.querySelector("[data-scan-status]");
    status.textContent = "Scanning…";
    const poll = setInterval(async () => {
      if (!document.body.contains(status)) return clearInterval(poll);
      const s = await api("/scan").catch(() => null);
      if (!s || s.running) return;
      clearInterval(poll);
      status.textContent = scanText(s);
      e.target.disabled = false;
    }, 1500);
  });

  const peopleError = main.querySelector("[data-people-error]");
  main.querySelectorAll("[data-user]").forEach((row) => {
    const id = Number(row.dataset.user);
    const name = row.querySelector(".person").firstChild.textContent;
    row.querySelector("[data-admin]")?.addEventListener("click", async (e) => {
      const admin = e.target.dataset.admin === "true";
      if (id === state.me.id && !confirm("Make yourself a member? You won’t be able to change library settings any more.")) return;
      try {
        await api(`/users/${id}`, { method: "PATCH", body: { admin } });
        if (id === state.me.id) { state.me = null; location.hash = "#/"; return; }
        renderAdmin(main);
      } catch (err) { fail(peopleError, err.message); }
    });
    row.querySelector("[data-remove]")?.addEventListener("click", async () => {
      if (!confirm(`Remove ${name}? They won’t be able to sign in any more, and their progress and shelves go.`)) return;
      try { await api(`/users/${id}`, { method: "DELETE" }); renderAdmin(main); }
      catch (err) { fail(peopleError, err.message); }
    });
    const reset = row.querySelector(".reset-form");
    row.querySelector("[data-reset]")?.addEventListener("click", () => { reset.hidden = !reset.hidden; if (!reset.hidden) reset.password.focus(); });
    reset.addEventListener("submit", async (e) => {
      e.preventDefault();
      const error = reset.querySelector(".form-error");
      error.hidden = true;
      try {
        await api(`/users/${id}/password`, { method: "POST", body: { password: reset.password.value } });
        reset.hidden = true;
        reset.reset();
        saved(`New password set. ${name} is signed out everywhere.`);
      } catch (err) { fail(error, err.message); }
    });
  });

  const form = main.querySelector(".add-person");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const error = form.querySelector(".form-error");
    error.hidden = true;
    try {
      await api("/users", { method: "POST", body: { username: form.username.value, password: form.password.value } });
      renderAdmin(main);
    } catch (err) { fail(error, err.message); }
  });
}
