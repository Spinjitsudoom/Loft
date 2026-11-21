// When the "What's new" pop-up shows, and what's in it (src/loft/web/js/whatsnew.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { newer, notesSince, toShowOnOpen, forReader } from "../../src/loft/web/js/whatsnew.js";

const all = ["0.2.0", "0.1.10", "0.1.9", "0.1.4", "0.1.3"].map((version) => ({ version, new: [], fixed: ["x"] }));
const versions = (list) => list.map((n) => n.version);

test("versions compare by number, not as text", () => {
  assert.ok(newer("0.1.10", "0.1.9") && newer("0.2.0", "0.1.10"));
  assert.ok(!newer("0.1.4", "0.1.4") && !newer("0.1.3", "0.1.4"));
});

test("after an update: the releases since the last notes shown, at most three", () => {
  assert.deepEqual(versions(toShowOnOpen(all, "0.1.4", "0.1.10", true)), ["0.1.10", "0.1.9"]);
  assert.deepEqual(versions(toShowOnOpen(all, "0.1.3", "0.2.0", true)), ["0.2.0", "0.1.10", "0.1.9"]);
  assert.deepEqual(versions(notesSince(all, "0.1.3", "0.1.9")), ["0.1.9", "0.1.4"]);
});

test("nothing without an update, or on a device that never had Loft", () => {
  assert.deepEqual(toShowOnOpen(all, "0.1.9", "0.1.9", true), []);
  assert.deepEqual(toShowOnOpen(all, "0.1.10", "0.1.9", true), []);   // went back a version
  assert.deepEqual(toShowOnOpen(all, null, "0.1.9", false), []);
  assert.deepEqual(toShowOnOpen(all, "0.1.4", "", true), []);
});

test("a device that used Loft before the pop-up existed sees this version's notes", () => {
  assert.deepEqual(versions(toShowOnOpen(all, null, "0.1.9", true)), ["0.1.9"]);
});

test("members don't see what only admins can use", () => {
  const n = { version: "0.1.4", new: [{ title: "Tray", text: "…", admin: true }, { title: "Shelves", text: "…" }] };
  assert.deepEqual(forReader(n, false).new.map((i) => i.title), ["Shelves"]);
  assert.deepEqual(forReader(n, true).new.map((i) => i.title), ["Tray", "Shelves"]);
  assert.deepEqual(forReader(n, false).fixed, []);
  const fixes = { version: "0.1.4", fixed: ["Covers load faster.", { text: "The Windows server starts in the tray.", admin: true }] };
  assert.deepEqual(forReader(fixes, false).fixed, ["Covers load faster."]);
  assert.deepEqual(forReader(fixes, true).fixed, ["Covers load faster.", "The Windows server starts in the tray."]);
});
