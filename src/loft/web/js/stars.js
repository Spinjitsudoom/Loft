// Five stars for rating a book: tap one to rate, tap your rating again to clear it. Arrow keys move
// between the stars. Used on the book's page and when you reach the end of a book.

const STAR = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.2l2.6 5.6 6.1.7-4.5 4.2 1.2 6-5.4-3.1-5.4 3.1 1.2-6-4.5-4.2 6.1-.7z"/></svg>`;

export function starsHTML(mine, { label = "Your rating" } = {}) {
  return `<span class="stars" role="group" aria-label="${label}" data-mine="${mine || ""}">${[1, 2, 3, 4, 5].map((n) =>
    `<button type="button" class="star${mine && n <= mine ? " is-on" : ""}" data-star="${n}" aria-pressed="${mine === n}"
      aria-label="${n} ${n === 1 ? "star" : "stars"}">${STAR}</button>`).join("")}</span>`;
}

function show(group, mine) {
  group.dataset.mine = mine || "";
  group.querySelectorAll(".star").forEach((b) => {
    const n = Number(b.dataset.star);
    b.classList.toggle("is-on", Boolean(mine && n <= mine));
    b.setAttribute("aria-pressed", String(mine === n));
  });
}

/** Call `onPick(stars or null)` when a star is chosen; the stars change at once and go back if it fails. */
export function wireStars(root, onPick) {
  const group = root.querySelector(".stars");
  if (!group) return;
  group.addEventListener("click", async (e) => {
    const b = e.target.closest(".star");
    if (!b || group.classList.contains("is-busy")) return;
    const before = Number(group.dataset.mine) || null;
    const n = Number(b.dataset.star);
    const pick = before === n ? null : n;
    show(group, pick);
    group.classList.add("is-busy");
    try { await onPick(pick); } catch { show(group, before); } finally { group.classList.remove("is-busy"); }
  });
  group.addEventListener("keydown", (e) => {
    const stars = [...group.querySelectorAll(".star")];
    const at = stars.indexOf(document.activeElement);
    if (at < 0) return;
    const move = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (!move) return;
    e.preventDefault();
    e.stopPropagation();  // in the reader, arrow keys would turn the page too
    stars[Math.max(0, Math.min(4, at + move))].focus();
  });
}
