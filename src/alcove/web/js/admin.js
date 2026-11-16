// Library settings, for admins: who can sign in, and rescanning the books folders.
import { api, esc } from "./api.js";
import { state } from "./main.js";

export async function renderAdmin(main) {
  const [users, scan] = await Promise.all([api("/users"), api("/scan")]);
  main.innerHTML = `<section class="page narrow">
    <header class="page-head"><h1>Library settings</h1></header>

    <section class="panel">
      <h2>People</h2>
      <ul class="people">${users.map((u) => `<li>
        <span>${esc(u.username)}${u.admin ? ` <span class="badge">Admin</span>` : ""}</span>
        ${u.id === state.me.id ? `<span class="muted">You</span>` : `<button class="btn btn-small" type="button" data-remove="${u.id}" data-name="${esc(u.username)}">Remove</button>`}
      </li>`).join("")}</ul>
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

    <section class="panel">
      <h2>Books folders</h2>
      <p class="muted" data-scan-status>${scanText(scan)}</p>
      <button class="btn" type="button" data-rescan>Rescan now</button>
    </section>
  </section>`;

  main.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Remove ${b.dataset.name}? They won’t be able to sign in any more.`)) return;
    await api(`/users/${b.dataset.remove}`, { method: "DELETE" });
    renderAdmin(main);
  }));

  const form = main.querySelector(".add-person");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const error = form.querySelector(".form-error");
    error.hidden = true;
    try {
      await api("/users", { method: "POST", body: { username: form.username.value, password: form.password.value } });
      renderAdmin(main);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });

  main.querySelector("[data-rescan]").addEventListener("click", async (e) => {
    e.target.disabled = true;
    await api("/scan", { method: "POST" });
    const status = main.querySelector("[data-scan-status]");
    status.textContent = "Scanning…";
    const poll = setInterval(async () => {
      const s = await api("/scan").catch(() => null);
      if (!s || s.running || !document.body.contains(status)) return;
      clearInterval(poll);
      status.textContent = scanText(s);
      e.target.disabled = false;
    }, 1500);
  });
}

function scanText(scan) {
  if (scan.running) return "Scanning…";
  if (!scan.last) return "Alcove checks the folders for new, changed and removed books every few minutes.";
  const { added, updated, removed } = scan.last;
  if (!added && !updated && !removed) return "Last scan: everything was already up to date.";
  return `Last scan: ${added} added, ${updated} updated, ${removed} removed.`;
}
