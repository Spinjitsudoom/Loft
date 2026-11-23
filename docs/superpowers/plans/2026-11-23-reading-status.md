# Reading status: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** each person has a reading status for each book (Want to read, Not started, Reading,
Incomplete, Abandoned, Finished). It's worked out from their reading, ages automatically, and can be set
by hand. Home, the stacks, the book page and the discussion use it.

**Architecture:**
- A new `src/loft/statuses.py` holds a pure `status_of` (events in, status out), the `book_status`
  table's reads and writes, and a per-person map of every book's status.
- `reading.save_progress` takes a book off Want to read.
- `library`, `browse` and `discussion` use the map instead of `progress.finished`.
- `app.py` adds `GET`/`PUT /api/books/{id}/status`.
- A new `web/js/statusmenu.js` is the book page's Status button.

**Tech Stack:** Python 3 / FastAPI / SQLite; vanilla JS; pytest (`bash test.sh -q`), `node --test tests/js/`.

**Spec:** `docs/superpowers/specs/2026-11-23-reading-status-design.md`

## Global Constraints

- **Statuses:** `want`, `unread`, `reading`, `incomplete`, `abandoned`, `finished`.
  - Labels: Want to read, Not started, Reading, Incomplete, Abandoned, Finished.
  - Set by hand (stored): `unread reading incomplete abandoned finished`. `want` is the Want to read shelf.
- `INCOMPLETE_AFTER = 15 days`, `ABANDONED_AFTER = 30 days`.
- No background job, and no new dependency. Don't commit. Restart `loft-test` after Python changes.
- Want to read is never set automatically.

## Review Focus

1. **A late save from an offline phone** (its reading time is before a status set by hand): the status set
   by hand holds. Pinned in Task 1.
2. **Bounds:** at exactly 15 or 30 days the status changes; the second before, it doesn't. Pinned in Task 1.
3. **Someone else's book status** is never read or changed (statuses are per person). Pinned in Task 2
   (API, two users).
4. **Continue reading and the big book at the top** never show an Incomplete or Abandoned book. Pinned in
   Task 2.
5. **Merging two books:** a status set by hand moves to the kept book, and the newer one wins. Pinned in
   Task 1.

---

### Task 1: `statuses.py`, the table, and what reading changes

**Files:**
- Create: `src/loft/statuses.py`
- Modify:
  - `src/loft/db.py` (the `book_status` table);
  - `src/loft/reading.py` (`save_progress`);
  - `src/loft/library.py` (`merge_books`).
- Test: `tests/test_statuses.py`

**Interfaces (produces):**
- `STATUSES`, `MARKS`, `LABELS`, `INCOMPLETE_AFTER`, `ABANDONED_AFTER` (seconds).
- `status_of(*, read_at: float|None, finished: bool, mark: str|None, mark_at: float|None,
  want_at: float|None, now: float) -> str`.
  - The latest of the three events wins. At equal times, a mark beats want, and want beats a reading.
  - **want:** `want`.
  - **A mark:**
    - `unread`, `abandoned` and `finished` hold;
    - `reading` ages from `mark_at`;
    - `incomplete` is `abandoned` once `now - mark_at >= ABANDONED_AFTER`, else `incomplete`.
  - **A reading:** `finished` if finished, else it ages from `read_at`.
  - **Ageing:** `>= ABANDONED_AFTER` is abandoned, `>= INCOMPLETE_AFTER` is incomplete, else reading.
  - **No event:** `unread`.
- `statuses_for(con, user_id: int, now: float|None=None) -> dict[int, tuple[str, float]]`: book id →
  (status, time of the deciding event), for every book with any event. A book that's absent is `unread`.
- `status_for(con, user_id, book_id, now=None) -> str`.
- `set_status(cfg, user_id: int, book_id: int, status: str, at: float|None=None) -> dict`:
  - returns `{"status", "shelves"}`;
  - raises `ValueError` for an unknown status and `LookupError` for an unknown book;
  - `want`: deletes the mark, and adds or refreshes the book on Want to read with `added_at = at`;
  - anything else: upserts the mark, and takes the book off Want to read.
- `get_status(cfg, user_id, book_id) -> dict`: `{"status", "shelves"}`. Raises `LookupError` for an
  unknown book.
- `save_progress` deletes this person's Want to read entry for the book when `added_at <= at`.
- `merge_books` moves `book_status` rows. The newer `set_at` wins.

- [ ] **Step 1: Write the failing tests** in `tests/test_statuses.py`:
  - `test_status_of`: a table of cases:
    - no events → `unread`;
    - read now → `reading`;
    - read 15 days − 1 s ago → `reading`; exactly 15 days → `incomplete`; 30 days → `abandoned`;
    - finished 60 days ago → `finished`;
    - mark `abandoned` after the reading → `abandoned`;
    - read after the mark → derived from the reading;
    - mark `reading` 16 days ago, read 40 days ago → `incomplete`;
    - mark `incomplete` 29 days ago → `incomplete`; 30 days → `abandoned`;
    - want after the reading → `want`; reading after want → `reading`;
    - mark and reading at the same time → the mark.
  - `test_reading_ages` (real db):
    - `save_progress(at=now-16d)` → `status_for` is `incomplete`;
    - `at=now-31d` on another book → `abandoned`;
    - the last page → `finished`.
  - `test_set_by_hand_holds_until_read_again`:
    - set `abandoned`, then a save with `at` before the mark (the late phone) → still `abandoned`;
    - a save after it → `reading`.
  - `test_want_to_read`:
    - `set_status(want)` puts the book on the `want` shelf (`shelves.for_book`) and the status is `want`;
    - `save_progress` afterwards takes it off and the status is `reading`;
    - `set_status(want)` again → `want`;
    - `set_status(finished)` takes it off the shelf;
    - adding it with `shelves.add` to Want to read also gives `want`.
  - `test_set_status_errors`: an unknown status gives `ValueError`, an unknown book `LookupError`.
  - `test_merge_keeps_marks`: a mark on the other book only moves over; the newer of two marks wins.
- [ ] **Step 2: Run them.**
  - Run: `~/.local/share/loft/venv/bin/python -m pytest tests/test_statuses.py -q`
  - Expected: FAIL (`ModuleNotFoundError: loft.statuses`).
- [ ] **Step 3: Implement** to the Interfaces.
  - Table: `book_status(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE, status TEXT NOT NULL, set_at REAL NOT NULL, PRIMARY KEY(user_id, book_id))`.
  - `statuses_for` reads progress, marks and the want shelf of one user in three queries.
- [ ] **Step 4: Run them.** Expected: PASS. Then run `bash test.sh -q`. Expected: all pass.

### Task 2: Home, lists, stacks, discussion, API

**Files:**
- Modify:
  - `src/loft/reading.py` (`in_progress`);
  - `src/loft/library.py` (`home`, `_shelf_rows`, `_filter`, `list_books`, `get_book`);
  - `src/loft/browse.py`;
  - `src/loft/discussion.py`;
  - `src/loft/app.py`.
- Test:
  - `tests/test_statuses.py`;
  - `tests/test_stacks.py` (if a status assertion there changes);
  - `tests/test_discussion.py`;
  - `tests/test_api.py`.

**Interfaces:**
- Consumes: `statuses_for`, `status_for`, `set_status`, `get_status` (Task 1).
- Produces:
  - `in_progress` returns only books whose status is `reading`, newest first, limit after filtering.
  - `home` rows, kind `shelves`, in this order:
    1. the shelves;
    2. `{"title": "Incomplete", "kind": "status", "value": "incomplete"}` (most recently read first; only
       if there are any);
    3. `{"title": "Finished", "kind": "finished", "value": ""}` (status `finished`, most recent first).
  - `list_books(kind="status", value=s)`: the user's books with that status. `kind="finished"` is the same
    as `status`/`finished`. An unknown status raises `ValueError`.
  - `get_book(...)["status"]`.
  - `browse.STATUSES = ("want", "unread", "reading", "incomplete", "abandoned", "finished")`. A book's
    `status` comes from `statuses_for`.
  - In `discussion`, a person whose status is `finished` sees nothing as ahead.
  - **API:**
    - `GET /api/books/{id}/status` returns `{status, shelves}`, or 404;
    - `PUT /api/books/{id}/status` with `{"status": s}` returns `{status, shelves}`; an unknown status
      gives 400 and an unknown book 404.

- [ ] **Step 1: Write the failing tests:**
  - `test_home_rows` (`tests/test_statuses.py`), with one book each:
    - read now, read 2 h ago, read 20 days ago, read 40 days ago, finished, and one marked `finished` by
      hand at page 3;
    - the hero is the newest Reading one;
    - "Continue reading" holds exactly the two Reading books;
    - the Incomplete row holds the 20-day one;
    - the Finished row holds both finished books;
    - `list_books(kind="status", value="abandoned")` is the 40-day one;
    - `list_books(kind="status", value="nope")` raises `ValueError`.
  - `test_stacks_filter_by_status` (`tests/test_stacks.py`): `facets["status"]` has all six keys, and
    `status="incomplete"` returns only the 20-day book.
  - `test_finished_by_hand_sees_everything` (`tests/test_discussion.py`): bob at page 19 sees sam's page 80
    message as ahead; after `set_status(bob, finished)`, it isn't.
  - `test_status_api` (`tests/test_api.py`):
    - `PUT` `abandoned` → 200 `{"status": "abandoned"}`;
    - `GET /api/books/{id}` has `"status": "abandoned"`;
    - `PUT` `nope` → 400; book 99999 → 404;
    - a second, non-admin user still sees `unread` for that book.
- [ ] **Step 2: Run them.** Expected: FAIL (no Incomplete row; `kind=status` unknown; etc.).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `bash test.sh -q`. Expected: all pass. Restart `loft-test`.

### Task 3: The web app and docs

**Files:**
- Create: `src/loft/web/js/statusmenu.js`
- Modify:
  - `src/loft/web/js/book.js` (the Status button beside Shelves);
  - `src/loft/web/js/shelfmenu.js` (keep the two in step);
  - `src/loft/web/js/stacks.js` (`STATUS` labels, all six);
  - `src/loft/web/js/grid.js` (an empty message for `kind=status`; a title);
  - `src/loft/web/style.css`;
  - `src/loft/web/sw.js` (CACHE `loft-shell-v8`);
  - `README.md`;
  - `CHANGELOG.md`.

**Interfaces:**
- `statusButtonHTML(book)` and `wireStatusMenu(root, book)`:
  - the button reads the status's label, with a small icon;
  - it opens a pop-up list of the six statuses as radio choices (`role="menuitemradio"`), with the current
    one ticked;
  - a hint under the list: "Loft keeps this up to date as you read: Incomplete after 15 days unread,
    Abandoned after 30.";
  - choosing a status `PUT`s it, updates the label and `book.shelves`, and dispatches `loft:shelves` on
    the page;
  - Escape and an outside click close it.
- The shelf menu's ticks come from `book.shelves` each time it opens. After a change, it dispatches
  `loft:shelves`. The status menu refetches `GET /status` on `loft:shelves` from the shelf menu.

- [ ] **Step 1: Browser check** (Playwright, throwaway server `scratchpad/e2e/fx`): a script
  `status_menu.py` that:
  - opens a book page and sees "Not started";
  - picks Abandoned, sees the label, and confirms `/api/books/{id}/status` says so after a reload;
  - picks Want to read and sees the Shelves menu has Want to read ticked;
  - unticks it in the Shelves menu and sees the label go back to "Not started";
  - opens the stacks and sees all six statuses in the Reading filter;
  - opens home after an Incomplete status is set by hand (`PUT`) and sees an "Incomplete" row whose See
    all opens a grid of that book;
  - finds no console errors.
  - Run it before implementing. Expected: FAIL (no Status button).
- [ ] **Step 2: Implement.** Run the script. Expected: all PASS. Then run `node --test tests/js/` and
  `bash test.sh -q`.
- [ ] **Step 3: Docs.**
  - README: one line under reading, on statuses and their ages.
  - CHANGELOG `## Unreleased`: "Reading status for every book: Want to read, Not started, Reading,
    Incomplete (after 15 days unread), Abandoned (after 30), Finished; set any by hand from the book's
    page. Continue reading shows only what you're reading; a new Incomplete row on home."
