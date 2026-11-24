// The Activity page's day headings (src/loft/web/js/activity.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { dayHeading } from "../../src/loft/web/js/activity.js";

const at = (y, m, d, h = 12) => new Date(y, m - 1, d, h).getTime() / 1000;

test("entries are grouped under days that read naturally", () => {
  const now = at(2026, 11, 24, 9);
  assert.equal(dayHeading(at(2026, 11, 24, 1), now), "Today");
  assert.equal(dayHeading(at(2026, 11, 23, 23), now), "Yesterday");
  assert.equal(dayHeading(at(2026, 11, 22), now), "Sunday 22 November");
  assert.equal(dayHeading(at(2025, 12, 31), now), "Wednesday 31 December 2025");
});
