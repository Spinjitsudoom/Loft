// The web app's pure text helpers (run by tests/test_js.py with Node, when Node is installed).
import { test } from "node:test";
import assert from "node:assert/strict";
import { searchTitle, spineTitle } from "../../src/alcove/web/js/titles.js";

test("titles are tidied before they're looked up", () => {
  assert.equal(searchTitle("#04 Assassin's Creed - Revelations"), "Assassin's Creed: Revelations");
  assert.equal(searchTitle("Avatar_ The Last Airbender - The Sea (90)"), "Avatar: The Last Airbender: The Sea");
  assert.equal(searchTitle("12 - Brotherhood"), "Brotherhood");
  assert.equal(searchTitle("snake_case_title"), "snake case title");
  assert.equal(searchTitle("1984"), "1984");                     // a title that is a number stays
  assert.equal(searchTitle("Fahrenheit 451"), "Fahrenheit 451");
  assert.equal(searchTitle(""), "");
});

test("a spine in a series' case doesn't repeat the series", () => {
  const book = (title, series) => ({ title, series });
  assert.equal(spineTitle(book("Assassin's Creed: Brotherhood", "Assassin's Creed"), true), "Brotherhood");
  // Punctuation differs between title and series: still the same words.
  assert.equal(spineTitle(book("Avatar: The Last Airbender - North and South Part One", "Avatar: The Last Airbender: North and South"), true), "Part One");
  // Only a number left: the series name, as a numbered volume's spine shows it.
  assert.equal(spineTitle(book("Assassin's Creed: Origins 1", "Assassin's Creed: Origins"), true), "Assassin's Creed: Origins");
  assert.equal(spineTitle(book("Uprising Vol. 2", "Uprising"), true), "Uprising");
  // Not in a series' case, or not starting with the series: the whole title.
  assert.equal(spineTitle(book("Assassin's Creed: Brotherhood", "Assassin's Creed"), false), "Assassin's Creed: Brotherhood");
  assert.equal(spineTitle(book("Desert Oath", "Assassin's Creed: Origins"), true), "Desert Oath");
  assert.equal(spineTitle(book("Uzumaki", ""), true), "Uzumaki");
});

test("a series and its number are read from a title, when it has them", async () => {
  const { seriesFromTitle } = await import("../../src/alcove/web/js/titles.js");
  assert.deepEqual(seriesFromTitle("#04 Assassin's Creed - Revelation"), { series: "Assassin's Creed", index: 4 });
  assert.deepEqual(seriesFromTitle("Assassin's Creed Book 4"), { series: "Assassin's Creed", index: 4 });
  assert.deepEqual(seriesFromTitle("Uprising #8"), { series: "Uprising", index: 8 });
  assert.deepEqual(seriesFromTitle("Geronimo Stilton, Vol. 2: Cat and Mouse"), { series: "Geronimo Stilton", index: 2 });
  assert.deepEqual(seriesFromTitle("Tomie, Volume 1"), { series: "Tomie", index: 1 });
  assert.equal(seriesFromTitle("Fahrenheit 451"), null);           // a number in a title isn't a series
  assert.equal(seriesFromTitle("Catch-22"), null);
  assert.equal(seriesFromTitle("Assassin's Creed: Brotherhood"), null);
  assert.equal(seriesFromTitle("1984"), null);
});
