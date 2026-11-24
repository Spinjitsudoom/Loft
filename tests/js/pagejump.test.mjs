// Going to a page, and the ratings' average (src/loft/web/js/pagejump.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { averageText, targetPage } from "../../src/loft/web/js/pagejump.js";

test("a typed page number becomes a page to go to, kept inside the book", () => {
  assert.equal(targetPage("12", 340), 11);
  assert.equal(targetPage(" 12 ", 340), 11);
  assert.equal(targetPage("0", 340), 0);
  assert.equal(targetPage("-4", 340), 0);
  assert.equal(targetPage("999", 340), 339);
  assert.equal(targetPage("p. 7", 340), 6);
  assert.equal(targetPage("", 340), null);
  assert.equal(targetPage("seven", 340), null);
  assert.equal(targetPage("12", 0), null);          // the count isn't known yet
});

test("the average reads naturally", () => {
  assert.equal(averageText(4.25, 3), "4.3 from 3 readers");
  assert.equal(averageText(4.2, 3), "4.2 from 3 readers");
  assert.equal(averageText(5, 1), "5 from 1 reader");
  assert.equal(averageText(4.0, 2), "4 from 2 readers");
  assert.equal(averageText(null, 0), "");
});
