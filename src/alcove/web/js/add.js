// Adding books (admin): drop files, check each one's details (read from the file, filled from Open
// Library if wanted), then save it into the books folder.
import { api, esc } from "./api.js";
import { coverHTML, generatedStyle } from "./cover.js";
import { clearErrors, detailFields, fillEmpty, readDetails, showError, showLookup } from "./edit.js";

const ACCEPT = ".epub,.pdf,.cbz,.cbr,.cb7,.mobi,.azw,.azw3,.fb2,.txt";
const queue = [];
let sending = false;

function mb(bytes) {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(0.1, bytes / 1e6).toFixed(1)} MB`;
}

export async function renderAdd(main) {
  const lib = await api("/library");
  main.innerHTML = `<section class="page narrow add-page">
    <header class="page-head"><h1>Add books</h1>
      <p class="muted">Each book is saved into <code>${esc(lib.upload_dir || "your books folder")}</code> as Author / Title / file,
        once you’ve checked its details. Your existing files are never changed.</p></header>
    <label class="drop" data-drop>
      <input type="file" multiple accept="${ACCEPT}" hidden data-files>
      <span class="drop-title">Drop books here</span>
      <span class="drop-sub">or <span class="drop-link">choose files</span></span>
      <span class="drop-sub">EPUB, PDF, comics (CBZ, CBR, CB7), Kindle and FB2${lib.allow_txt ? ", and plain text" : ""}</span>
    </label>
    <ol class="add-list" data-list></ol>
  </section>`;

  const drop = main.querySelector("[data-drop]");
  const list = main.querySelector("[data-list]");
  const take = (files) => { for (const f of files) addFile(list, f); };
  main.querySelector("[data-files]").addEventListener("change", (e) => { take(e.target.files); e.target.value = ""; });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); take(e.dataTransfer.files); });
}

function addFile(list, file) {
  const li = document.createElement("li");
  li.className = "add-card";
  li.innerHTML = `<div class="add-status"><strong>${esc(file.name)}</strong><span class="muted">${mb(file.size)} · waiting</span></div>
    <span class="add-bar"><i style="width:0"></i></span>`;
  list.prepend(li);
  queue.push({ file, li });
  pump();
}

async function pump() {
  if (sending) return;
  sending = true;
  while (queue.length) {
    const { file, li } = queue.shift();
    if (!document.body.contains(li)) continue;
    try {
      review(li, await send(file, li));
    } catch (e) {
      li.innerHTML = `<div class="add-status"><strong>${esc(file.name)}</strong><span class="form-error">${esc(e.message)}</span></div>
        <button class="btn btn-small" type="button">Dismiss</button>`;
      li.querySelector("button").addEventListener("click", () => li.remove());
    }
  }
  sending = false;
}

function send(file, li) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const note = li.querySelector(".muted");
    const bar = li.querySelector(".add-bar i");
    xhr.open("PUT", `/api/uploads?name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      bar.style.width = `${(e.loaded / e.total) * 100}%`;
      note.textContent = e.loaded < e.total ? `${mb(e.loaded)} of ${mb(e.total)}` : "Reading its details…";
    };
    xhr.onload = () => {
      let json = null;
      try { json = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status === 200 && json) resolve(json);
      else reject(new Error((json && typeof json.detail === "string" && json.detail) || "The upload didn’t finish; try again"));
    };
    xhr.onerror = () => reject(new Error("The upload didn’t finish; check the connection and try again"));
    xhr.send(file);
  });
}

function review(li, draft) {
  let coverUrl = null;
  const cover = () => draft.has_cover && !coverUrl
    ? `<div class="book" style="${generatedStyle(draft.details.title)}"><img src="/api/uploads/${draft.token}/cover" alt=""></div>`
    : coverUrl
      ? `<div class="book" style="${generatedStyle(draft.details.title)}"><img src="${esc(coverUrl)}" alt=""></div>`
      : coverHTML({ title: draft.details.title || draft.filename, authors: draft.details.authors });
  li.classList.add("reviewing");
  li.innerHTML = `<div class="add-cover" data-cover>${cover()}</div>
    <form class="add-form" novalidate>
      <p class="add-file"><strong>${esc(draft.filename)}</strong> <span class="muted">${esc(draft.format.toUpperCase())} · ${mb(draft.size)}</span></p>
      ${draft.same_as.length ? `<p class="add-same">This looks like ${draft.same_as.map((b) =>
        `<a href="#/book/${b.id}">${esc(b.title)}</a>`).join(", ")}, already in the library. Save it anyway to keep both.</p>` : ""}
      ${detailFields(draft.details, { required: true })}
      <div class="edit-actions">
        <button class="btn btn-primary" type="submit">Save to the library</button>
        <button class="btn" type="button" data-fill>Fill from Open Library</button>
        <button class="btn" type="button" data-discard>Discard</button>
      </div>
      <p class="form-error" role="alert" hidden></p>
      <div class="lookup" hidden></div>
    </form>`;

  const form = li.querySelector("form");
  const error = form.querySelector(".form-error");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearErrors(form);
    error.hidden = true;
    const button = form.querySelector("[type=submit]");
    button.disabled = true;
    const details = readDetails(form);
    try {
      const { book_id } = await api(`/uploads/${draft.token}/save`, { method: "POST", body: { details, cover_url: coverUrl } });
      li.classList.remove("reviewing");
      li.innerHTML = `<div class="add-status"><strong>${esc(details.title)}</strong><span class="muted">Added to the library</span></div>
        <a class="btn btn-small" href="#/book/${book_id}">Open book</a>`;
    } catch (err) {
      const left = showError(form, err.message);
      if (left) { error.textContent = left; error.hidden = false; }
      button.disabled = false;
    }
  });
  form.querySelector("[data-fill]").addEventListener("click", () => {
    const d = readDetails(form);
    showLookup(form.querySelector(".lookup"), { title: d.title, author: d.authors[0] || "", isbn: draft.isbn }, async (c) => {
      await fillEmpty(form, c);
      if (!draft.has_cover && c.cover_url) {
        coverUrl = c.cover_url;
        li.querySelector("[data-cover]").innerHTML = cover();
      }
      form.querySelector(".lookup").hidden = true;
    });
  });
  form.querySelector("[data-discard]").addEventListener("click", async () => {
    await api(`/uploads/${draft.token}`, { method: "DELETE" }).catch(() => {});
    li.remove();
  });
  form.elements.title.focus({ preventScroll: true });
}

