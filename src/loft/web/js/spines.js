// The stacks' spines: their colours, and the size at which a title fits on the label. Pure, so it
// can be tested without a browser; the stacks hand fitTitle a measurer that uses a canvas.

export const GILT = "#e2c27a", INK = "#1d150e", PAPER = "#f4ede2", BRONZE = "#4a3a22";
const SHADE = 0.45;           // a label without a second colour: a deep shade of the spine

export const LINE_HEIGHT = 1.12;
const SPACING = 0.05;         // letter-spacing, in ems
const LABEL_PADDING = 13;     // the label's length less this is what the lettering may use (a pixel to spare)
const WIDTH_MARGIN = 6;       // the spine's width less this is what the lines may use (a pixel to spare)
const BIGGEST = 12, SMALLEST = 7, STEP = 0.5, MOST_LINES = 3;

// Curly quotes as straight ones: in vertical lettering browsers stand curly quotes upright, a whole
// em tall, which the fitting (measured on a line) can't foresee; straight ones lie with the text.
export function plainQuotes(text) {
  return String(text).replace(/[\u2018\u2019\u201a\u201b\u2032]/g, "'").replace(/[\u201c\u201d\u201e\u201f\u2033]/g, '"');
}

export function hash(text) {
  let h = 2166136261;
  for (const ch of String(text)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

const hex = (rgb) => "#" + rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

function hslRGB(h, s, l) {
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  return [0, 8, 4].map((n) => 255 * (l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))));
}

// "#rrggbb" or "hsl(h s% l%)" as [r, g, b]; anything else is black.
function rgb(colour) {
  const m = /^#([0-9a-f]{6})$/i.exec(colour || "");
  if (m) { const n = parseInt(m[1], 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
  const h = /^hsl\((\d+(?:\.\d+)?) (\d+(?:\.\d+)?)% (\d+(?:\.\d+)?)%\)$/.exec(colour || "");
  if (h) return hslRGB(+h[1], h[2] / 100, h[3] / 100);
  return [0, 0, 0];
}

function luminance(colour) {
  return rgb(colour).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
}

// The WCAG contrast ratio of two colours, 1 to 21.
export function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const clearest = (on, ...choices) => choices.reduce((best, c) => (contrast(on, c) > contrast(on, best) ? c : best));

// A spine's colours: the cloth (c), the title label, its lettering, and the trim (ribs, ornament, number).
// With a palette from the cover, the label takes the cover's second colour; without one, a deep shade
// of the cover's colour (or of a colour made from the title, for a book with no cover).
export function spineColours(b) {
  const trimOn = (c) => clearest(c, GILT, BRONZE);
  if (b.spine && b.spine.length === 2) {
    const [c, label] = b.spine;
    return { c, label, letter: clearest(label, GILT, INK, PAPER), trim: trimOn(c) };
  }
  const c = b.color || `hsl(${hash(b.title) % 360} 32% 32%)`;
  const label = hex(rgb(c).map((v) => v * SHADE));
  return { c, label, letter: clearest(label, GILT, INK), trim: trimOn(c) };
}

// The largest lettering at which the whole title fits on a label `length` long, on a spine `width`
// wide: on one line, or wrapped onto two or three. measure(text, size) is the width of the uppercase
// text at that size without letter-spacing, which is added here.
export function fitTitle(title, length, width, measure) {
  const words = String(title).toUpperCase().split(/\s+/).filter(Boolean);
  const room = length - LABEL_PADDING;
  for (let size = BIGGEST; size >= SMALLEST; size -= STEP) {
    const w = (s) => measure(s, size) + s.length * size * SPACING;
    const space = w(" ");
    let lines = 1, run = 0, ok = true;
    for (const word of words) {
      const ww = w(word);
      if (ww > room) { ok = false; break; }
      if (run && run + space + ww > room) { lines += 1; run = ww; } else run += (run ? space : 0) + ww;
    }
    if (ok && lines <= MOST_LINES && lines * size * LINE_HEIGHT <= width - WIDTH_MARGIN) return { size, lines, fits: true };
  }
  const lines = Math.max(1, Math.min(MOST_LINES, Math.floor((width - WIDTH_MARGIN) / (SMALLEST * LINE_HEIGHT))));
  return { size: SMALLEST, lines, fits: false };
}
