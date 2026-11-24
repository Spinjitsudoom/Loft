import { test } from "node:test";
import assert from "node:assert/strict";
import { BRONZE, GILT, INK, PAPER, contrast, fitTitle, spineColours } from "../../src/loft/web/js/spines.js";

const measure = (text, size) => text.length * size * 0.6;   // a stand-in for the canvas

test("a short title stays big on one line", () => {
  assert.deepEqual(fitTitle("Unity", 120, 30, measure), { size: 12, lines: 1, fits: true });
});

test("a long title shrinks or wraps, but never past three lines or the spine's width", () => {
  const r = fitTitle("The Secret Crusade: Assassin's Creed Book 3", 110, 40, measure);
  assert.ok(r.fits && r.lines <= 3 && r.size < 12);
  assert.ok(r.lines * r.size * 1.12 <= 40 - 5);
});

test("a title wraps onto a second line where the spine is wide enough", () => {
  const r = fitTitle("Brotherhood Revelations", 100, 40, measure);
  assert.equal(r.fits, true);
  assert.equal(r.lines, 2);
});

test("a word too long for the label even at 7px falls back to 7px, cut", () => {
  assert.deepEqual(fitTitle("A".repeat(40), 60, 20, measure), { size: 7, lines: 1, fits: false });
});

test("the fallback still uses the lines a wide spine has room for", () => {
  assert.deepEqual(fitTitle("A".repeat(40), 60, 40, measure), { size: 7, lines: 3, fits: false });
});

test("an empty title is fine", () => {
  assert.equal(fitTitle("", 100, 20, measure).fits, true);
});

test("contrast is WCAG's", () => {
  assert.equal(Math.round(contrast("#000000", "#ffffff")), 21);
  assert.equal(contrast("#123456", "#123456"), 1);
});

test("letters and trim stay readable on dark and light spines", () => {
  const dark = spineColours({ title: "x", spine: ["#5a1010", "#1a1a40"] });
  assert.equal(dark.c, "#5a1010"); assert.equal(dark.label, "#1a1a40");
  assert.equal(dark.letter, PAPER); assert.equal(dark.trim, GILT);   // paper beats gilt on a dark label, as in the mockup
  const cream = spineColours({ title: "x", spine: ["#efe6d2", "#f5f0e6"] });
  assert.equal(cream.letter, INK); assert.equal(cream.trim, BRONZE);
});

test("a book with no palette still gets a whole spine", () => {
  const old = spineColours({ title: "x", spine: null, color: "#402020" });
  assert.equal(old.c, "#402020"); assert.equal(old.label, "#1d0e0e");   // × 0.45
  assert.ok([GILT, INK].includes(old.letter));
  const bare = spineColours({ title: "Untitled", spine: null, color: null });
  assert.match(bare.c, /^hsl\(\d+ 32% 32%\)$/);
  assert.match(bare.label, /^#[0-9a-f]{6}$/);
  assert.ok([GILT, INK].includes(bare.letter));
  assert.ok([GILT, BRONZE].includes(bare.trim));
});
