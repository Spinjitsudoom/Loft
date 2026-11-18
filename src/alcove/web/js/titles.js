// Text helpers with no screen of their own (so they can be tested on their own: tests/js).

// A title as files leave it ("#04 Assassin's Creed - Revelations (90)") made fit to search for.
export function searchTitle(title) {
  return String(title || "")
    .replace(/_\s/g, ": ")                             // files can't hold ":", so "Avatar_ The…" was "Avatar: The…"
    .replace(/_+/g, " ")
    .replace(/^\s*#?\d+\s*[-.:)]?\s+(?=\D)/, "")   // a leading "#04 " or "12 - "
    .replace(/\s*[([]\d+[)\]]\s*$/, "")              // a trailing "(90)"
    .replace(/\s+[-–—]\s+/g, ": ")                    // "Series - Title" reads "Series: Title"
    .replace(/\s{2,}/g, " ")
    .trim();
}

// Inside a series' case the spine needn't repeat the series: "Assassin's Creed: Brotherhood" → "Brotherhood".
export function spineTitle(b, inSeries) {
  if (!inSeries || !b.series) return b.title;
  // Match the series at the start of the title letter by letter, ignoring punctuation and spaces:
  // "Avatar: The Last Airbender - North and South" starts with "Avatar: The Last Airbender: North and South".
  const want = b.series.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  let i = 0, got = "";
  const title = b.title;
  while (i < title.length && got.length < want.length) {
    const ch = title[i].toLowerCase();
    if (/[\p{L}\p{N}]/u.test(ch)) {
      if (ch !== want[got.length]) return b.title;
      got += ch;
    }
    i += 1;
  }
  if (got !== want) return b.title;
  const rest = title.slice(i).replace(/^[\s:.,#–—-]+/, "");
  // Only a number left: like a numbered volume, the spine shows the series (the number sits below).
  if (!rest || /^(no\.?\s*|vol(ume)?\.?\s*|#)?\d+(\.\d+)?$/i.test(rest)) return b.series;
  return rest;
}
