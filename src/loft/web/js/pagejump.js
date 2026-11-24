// Small helpers for the reader's "Go to page" box and the ratings' average, kept apart from the
// page code so Node can test them (tests/js/pagejump.test.mjs).

/** The page (from 0) a typed number asks for, kept inside the book; null for no number or no pages yet. */
export function targetPage(text, count) {
  const m = /-?\d+/.exec(String(text ?? ""));
  if (!m || !(count >= 1)) return null;
  return Math.min(count - 1, Math.max(0, Number(m[0]) - 1));
}

/** "4.2 from 3 readers", or "" when no one has rated the book. */
export function averageText(average, count) {
  if (!count || average == null) return "";
  const shown = String(Math.round(average * 10) / 10);
  return `${shown} from ${count} ${count === 1 ? "reader" : "readers"}`;
}
