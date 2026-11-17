# The Stacks (browse by section, author or series) Implementation Plan

> Executed inline. Branch `m5-downloads-members`. Spec: design doc, "The stacks" under calls made.

**Goal:** a Browse page that feels like walking a library: bookcases of spines, signed by series,
section or author, narrowed by filters across the top.

## Tasks
1. **Sections** (libsettings): `sections` setting (None = suggested from the library's tags);
   `effective_sections(cfg)`; validation (≤30 sections, names ≤40 unique, ≤50 tags each).
   `/api/library` returns `sections` and `sections_suggested`. Tests in test_stacks.py.
2. **browse.py**: `stacks(cfg, user, by, status, section, author, fmt)` → {cases: [{title, key, kind,
   books}], total, facets: {status, section, author, format}: counts ignoring their own filter}.
   Book entries: card + `section`, `size`, `pages` (page_info count when known), `progress`.
   Route GET /api/stacks. Tests.
3. **stacks.js** + route #/stacks + top-bar link: toolbar (Shelve by, filter selects, Spines/
   Covers; phone: Filters sheet), cases with sideways-scrolling shelves, spines (cover colour,
   readable text colour, thickness, height jitter), pull-out panel (cover, title, author, Read,
   About), covers mode; choices kept in the URL and remembered on the device.
4. **Sections editor** in Library settings: list (name, tags, up/down, remove), add a section,
   "Use the suggestions again"; shows how many books each takes.
Verify: tests; Chromium on :4548 (desktop + phone), and on the real library copy for the look.
