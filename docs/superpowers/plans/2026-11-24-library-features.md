# Going to a page, ratings, checking out, and the activity log: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four things to Loft:
- typing a page number in the reader;
- 1–5 star ratings;
- library-style loans (checked out and returned);
- an admin activity log.

They ship as 0.2.0, with the spines plan (`2026-11-23-spines.md`) and the polish fixes.

**Architecture:**
- **New modules.** Three new server modules, each owning its own table:
  - `activity.py`, written to from everywhere else;
  - `ratings.py`;
  - `loans.py`, kept in step with reading through hooks in `reading.save_progress` and `statuses`.
- **Logging.** User actions are logged at the API routes in `app.py`, where the person is known. Loft's own actions (scans, backups, updates, filling in details) are logged in their modules.
- **Web app.** New pieces on the book page and in the reader, plus two new pages: the library card (`#/card`) and Activity (`#/activity`).

**Tech Stack:** Python 3.14, FastAPI, SQLite; vanilla JS ES modules; pytest; `node --test`; Playwright for the end-to-end check.

**Spec:** `docs/superpowers/specs/2026-11-24-library-features-design.md`

## Global Constraints

- **Ratings:** whole stars from 1 to 5, one per person per book. Tapping your own rating again clears it. The average shows as `"4.2 from 3 readers"` (one decimal; "1 reader" when there is one), and only when the count is at least 1. Members never see individual ratings.
- **Loans:**
  - `how` is one of `finished`, `abandoned` or `returned`, and NULL while the book is out.
  - A person has at most one open loan per book.
  - Abandoned means 30 days without reading: `statuses.ABANDONED_AFTER`, never a new constant.
  - It is closed with `returned_at` set to the quiet start plus `ABANDONED_AFTER`.
- **Checking out doesn't lock:** a checked-out book is never blocked for anyone.
- **Activity log:**
  - Admins only. Kept for 365 days, trimmed at most once a day, when an entry is written.
  - A failure to write an entry never fails the action. It is logged with `log.exception` and the action goes ahead.
  - Reading (page turns, progress saves) is never logged.
- **Activity groups and labels:** `{"sign_in": "Sign-ins", "people": "People", "books": "Books", "loans": "Loans", "ratings": "Ratings", "requests": "Requests", "discussion": "Discussion", "loft": "Loft"}`.
- **Kinds** are `"<group>.<what>"`. Only these are used:
  - `sign_in.ok`, `sign_in.failed`;
  - `people.asked`, `people.approved`, `people.added`, `people.removed`, `people.admin`;
  - `books.added`, `books.removed`, `books.edited`, `books.cover`, `books.filled`, `books.unfilled`;
  - `loans.out`, `loans.returned`;
  - `ratings.rated`, `ratings.cleared`;
  - `requests.asked`, `requests.fulfilled`, `requests.submitted`;
  - `discussion.comment`;
  - `loft.scan`, `loft.backup`, `loft.restore`, `loft.update_ready`, `loft.update_installed`, `loft.settings`.
- **Going to a page:** page numbers are Loft's own (1-based, as "Page 12 of 340" shows). Out of range is clamped to the first or last page. `G` opens the box when focus isn't in a text field. On phones it uses `inputmode="numeric"`.
- **Copy:** sentence case, plain verbs, Loft's existing voice. No new fonts. The service worker cache goes up once for the whole update (to `loft-shell-v10`, shared with the spines plan).
- **Version** 0.2.0 (Task 7).
- **Commits:**
  - End each one with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - author them with the noreply email `229893545+Spinjitsudoom@users.noreply.github.com`;
  - commit locally only; push and release only when the user says.
- **Test server:** after Python changes, run `systemctl --user restart loft-test` (port 4545, which uses the user's real accounts). End-to-end checks use a throwaway Loft on port 4610 with its own data folder.

## Review Focus

1. **A finished book read again.** Turning back from the last page opens a new loan. Saving the last page again on a finished book with no open loan must not create a loan and close it each time. *(Task 4 test)*
2. **A book or person deleted after activity about them.** The log still reads right (names copied in), and links to the missing book or person are dropped, not broken. *(Task 1 test)*
3. **A first scan adding thousands of books.** At most 50 `books.added` entries per scan, then one summary entry "added N more books". *(Task 2 test)*
4. **Two tabs rating, or checking out, at the same time.** One rating row and one open loan per person and book, enforced by the database, not by checking first. *(Tasks 3 and 4 tests)*
5. **Going to a page in a flowing book still being laid out.** The count isn't final yet, so the page number clamps to what's known and the reader carries on. *(Task 5 test, on the pure helper)*

---

### Task 1: The activity log's store and API

**Files:**
- Create: `src/loft/activity.py`
- Modify: `src/loft/db.py` (SCHEMA: the `activity` table, plus indexes on `at` and on `(user_id, at)`), `src/loft/app.py` (route)
- Test: `tests/test_activity.py`

**Interfaces:**
- Produces:
  - `activity.GROUPS: dict[str, str]`, as in Global Constraints.
  - `activity.record(con, kind: str, text: str, *, user_id: int | None = None, user_name: str = "", book_id: int | None = None, book_title: str = "", details: dict | None = None, at: float | None = None) -> None`:
    - takes a missing `user_name` or `book_title` from the database by id;
    - never raises: it catches `Exception` and calls `log.exception`;
    - calls `trim` when it's due.
  - `activity.trim(con, now: float) -> int`: removes entries older than 365 days, at most once a day (meta key `activity_trimmed_at`); returns how many it removed.
  - `activity.listing(cfg, *, before: int | None = None, user_id: int | None = None, group: str | None = None, limit: int = 50) -> dict`:
    - returns `{"entries": [...], "more": bool, "people": [{"id", "name"}], "groups": GROUPS}`;
    - each entry is `{"id", "at", "kind", "group", "text", "user": {"id", "name", "exists"}, "book": {"id", "title", "exists"} | None, "details"}`;
    - ordered newest first; `before` is an entry id, for paging.
  - Route: `GET /api/activity?before=&user=&group=`, for admins only; a member gets 403.
- Table: `activity(id INTEGER PRIMARY KEY, at REAL NOT NULL, user_id INTEGER, user_name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, book_id INTEGER, book_title TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, details TEXT)`. It has **no** foreign keys, so entries outlive what they name.

- [ ] **Step 1: Write the failing tests** in `tests/test_activity.py`:
  - `test_entries_come_newest_first_and_page`:
    1. record 60 entries;
    2. `listing(limit=50)` gives 50 entries with `more` true;
    3. `listing(before=<last id>)` gives the other 10 with `more` false.
  - `test_names_outlive_what_they_name`:
    1. record an entry for a user and a book;
    2. delete both;
    3. the entry still has the names, and `user.exists` and `book.exists` are false.
  - `test_filter_by_person_and_group`.
  - `test_a_year_is_kept`:
    1. entries at now−400 days and now−10 days;
    2. `trim(con, now)` removes 1;
    3. a second `trim` the same day removes 0 without querying the entries (assert it returns 0).
  - `test_a_failed_write_never_stops_the_action`: `record` on a closed connection doesn't raise, and `caplog` shows the error.
  - `test_only_admins_see_the_log`: through the `client` fixture, admin → 200, member → 403.
- [ ] **Step 2: Run them; they fail.** Command: `bash test.sh tests/test_activity.py -q`. Expected: ImportError.
- [ ] **Step 3: Implement** the table, `activity.py` and the route.
- [ ] **Step 4: Run them; they pass.** Then run `bash test.sh -q`; expected: all pass.
- [ ] **Step 5: Commit:** "Activity log: where it's kept, and the admins' API".

---

### Task 2: Logging what happens

**Files:**
- Modify:
  - `src/loft/app.py`, in the routes listed below;
  - `src/loft/scanner.py`: `scan`, and `_scan_root` collecting the added and removed books;
  - `src/loft/backups.py`: `make`, `restore`;
  - `src/loft/updates.py`: `check` when a download becomes ready; `_start_setup` and `_restart_into` for installed;
  - `src/loft/autofill.py`: `fill_book` when it returns "filled", and `undo`.
- Test: `tests/test_activity.py`

**Interfaces:**
- Consumes: `activity.record` (Task 1).
- Produces: nothing new. Text values are a verb phrase without the person; the page shows the person first.

**What each route logs** (kind: text):

| Route | Kind and text |
|---|---|
| `/api/login` ok | `sign_in.ok`: "signed in" |
| `/api/login` failed | `sign_in.failed`: "couldn’t sign in", with `user_name` = the name tried and `details={"ip"}` |
| `/api/join` | `people.asked`: "asked to join" |
| join approve | `people.approved`: "approved <name>", with `details={"person"}` |
| `POST /api/users` | `people.added`: "added <name>" |
| `DELETE /api/users/{id}` | `people.removed`: "removed <name>" |
| `PATCH /api/users/{id}` (admin flag) | `people.admin`: "made <name> an admin" or "made <name> a member" |
| `PATCH /api/books/{id}` | `books.edited`: "edited the details", with `details={"fields": [...]}` (the keys changed) |
| cover put/delete/lookup | `books.cover`: "changed the cover" / "removed the cover" |
| uploads save | `books.added`: "added (upload)" |
| submission approve | `books.added`: "added (from <submitter>’s suggestion)" |
| uploads submit | `requests.submitted`: "suggested a book" |
| `POST /api/requests` | `requests.asked`: "asked for <title>" |
| request fulfil | `requests.fulfilled`: "fulfilled the request for <title>" |
| `POST /api/books/{id}/discussion` | `discussion.comment`: "commented on" |
| `PATCH /api/library` | `loft.settings`: "changed library settings", with `details={"fields"}` |
| backups POST and restore | `loft.backup` / `loft.restore` (also logged from the module when the keeper makes one: `user_id` None, "made a backup (scheduled)") |
| updates install | `loft.update_installed`: "restarted into Loft <v>" |
| merging books | `books.edited`: "merged in another copy" |

**Loft's own actions:**
- **Scan:**
  - one `books.added` per added book and one `books.removed` per removed book, up to 50 of each per scan;
  - past 50, one more entry: "added N more books" / "removed N more books";
  - when anything changed, one `loft.scan` entry with `details=report counts`.
- **Updates:** `loft.update_ready`: "downloaded Loft <v>".
- **Autofill:** `books.filled`: "filled in <fields> automatically"; `books.unfilled`: "undid the automatic details".

- [ ] **Step 1: Write the failing tests**, one per row group above, through the `client` fixture (the existing `test_api.py` shows how to sign in as admin and as member). Each asserts the newest entry's `kind`, `user.name` and `book.title`:
  - `test_sign_ins_are_logged_and_failures_name_who_was_tried`
  - `test_people_changes_are_logged`
  - `test_book_edits_name_the_fields`
  - `test_uploads_and_suggestions_are_logged`
  - `test_requests_and_comments_are_logged`: the comment's text is **not** in the entry or its details.
  - `test_settings_backups_and_updates_are_logged`
  - `test_a_big_scan_logs_50_books_then_a_summary`: 60 books in `tmp_path`, scanned. Expect 50 `books.added`, one "added 10 more books", and one `loft.scan`.
  - `test_a_scan_that_changed_nothing_logs_nothing`
  - `test_reading_is_never_logged`: a progress save leaves the log as it was (Task 4 adds loans; this test then expects only `loans.out`, so write it as "no kind outside `loans`").
- [ ] **Step 2: Run them; they fail.** Command: `bash test.sh tests/test_activity.py -q`.
- [ ] **Step 3: Implement.** Write each entry in the same session as the action where the route has one; otherwise open a short `session` just for the record.
- [ ] **Step 4: Run them; they pass.** Then run `bash test.sh -q`.
- [ ] **Step 5: Commit:** "The activity log records sign-ins, people, books, requests, comments and Loft's own work".

---

### Task 3: Ratings

**Files:**
- Create: `src/loft/ratings.py`
- Modify: `src/loft/db.py` (SCHEMA), `src/loft/library.py` (`get_book` adds `rating`; `SORTS["rating"]`), `src/loft/app.py` (route)
- Test: `tests/test_ratings.py`

**Interfaces:**
- Consumes: `activity.record`.
- Produces:
  - Table: `ratings(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE, stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5), rated_at REAL NOT NULL, PRIMARY KEY (user_id, book_id))`.
  - `ratings.rate(cfg, user_id: int, book_id: int, stars: int | None) -> dict`:
    - `None` clears the rating;
    - stars outside 1–5 raise `ValueError`; a missing book raises `LookupError`;
    - logs `ratings.rated` ("rated it ★★★★☆", `details={"stars"}`) or `ratings.cleared`;
    - returns `summary`.
  - `ratings.summary(con, book_id: int, user_id: int) -> dict`: `{"mine": int | None, "average": float | None, "count": int}`, with the average rounded to 1 decimal.
  - `library.get_book(...)["rating"]` is that summary.
  - `SORTS["rating"]` orders by average (books never rated last), then count descending, then title.
  - Route: `PUT /api/books/{book_id}/rating`, body `{"stars": int | null}`, returns the summary. It gives 422 for a bad number and 404 for no such book.

- [ ] **Step 1: Write the failing tests:**
  - `test_rating_and_the_average`: two people rate 4 and 5 → `{"mine": 4, "average": 4.5, "count": 2}` for the first.
  - `test_rating_again_replaces_and_none_clears`.
  - `test_only_whole_stars_from_one_to_five`: 0, 6 and 3.5 each raise.
  - `test_ratings_go_with_the_book_or_person`: delete the book, and no rows are left.
  - `test_highest_rated_sort`: books rated 5 (one reader), 4.5 (two readers) and unrated sort as [5, 4.5, unrated].
  - `test_rating_is_logged`.
  - `test_the_api_rates_and_members_see_only_the_average`: the book JSON for a member has no other people's stars anywhere.
  - `test_two_ratings_at_once_leave_one_row`: two threads rating the same person and book → `COUNT(*) == 1`.
- [ ] **Step 2: Run them; they fail.** Command: `bash test.sh tests/test_ratings.py -q`.
- [ ] **Step 3: Implement.** Use upsert with `ON CONFLICT(user_id, book_id) DO UPDATE`.
- [ ] **Step 4: Run them; they pass.** Then run `bash test.sh -q`.
- [ ] **Step 5: Commit:** "Ratings: one to five stars, and the library's average".

---

### Task 4: Checking out and returning

**Files:**
- Create: `src/loft/loans.py`
- Modify:
  - `src/loft/db.py`: SCHEMA, plus a partial unique index: `CREATE UNIQUE INDEX loans_open ON loans(user_id, book_id) WHERE returned_at IS NULL`;
  - `src/loft/reading.py`: `save_progress` calls the hook;
  - `src/loft/statuses.py`: `set_status` and `opened` call the hooks;
  - `src/loft/library.py`: `get_book` adds `loan`;
  - `src/loft/app.py`: routes; a one-off fill-in at startup.
- Test: `tests/test_loans.py`

**Interfaces:**
- Consumes: `activity.record`; `statuses.ABANDONED_AFTER`; `statuses.status_for`.
- Produces:
  - Table: `loans(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE, out_at REAL NOT NULL, returned_at REAL, how TEXT)`.
  - `loans.out(con, user_id, book_id, at) -> bool`: opens a loan if none is open. Returns whether it opened one, and logs `loans.out` ("checked out") when it did. It uses `INSERT ... ON CONFLICT DO NOTHING` against the partial index.
  - `loans.back(con, user_id, book_id, how: str, at) -> bool`: closes the open loan, if any, and logs `loans.returned`: "returned (finished)", "returned (abandoned)" or "returned early".
  - `loans.reading(con, user_id, book_id, at, finished: bool) -> None`: called by `save_progress`.
    - When not finished, it opens a loan.
    - When finished, it closes the open loan as `finished`, and never opens one.
  - `loans.marked(con, user_id, book_id, status, at) -> None`: called by `set_status`.
    - reading or incomplete → open;
    - finished → close `finished`;
    - abandoned → close `abandoned`;
    - unread or want → close `returned`.
  - `statuses.opened` calls `loans.out` when it turns a book back to Reading.
  - `loans.settle(con, user_id: int | None, now) -> int`: closes open loans quiet for `ABANDONED_AFTER` as `abandoned`, at quiet start + `ABANDONED_AFTER`. Quiet start is the latest of `out_at`, that person's progress `updated_at` for the book, and their `book_status.set_at` when it's reading or incomplete. `user_id` None means everyone. Every function below that reads loans calls it first.
  - `loans.check_out(cfg, user_id, book_id) -> dict` and `loans.give_back(cfg, user_id, book_id) -> dict`: the button actions; each returns `loan_for`.
  - `loans.loan_for(con, viewer_id, book_id) -> dict`: `{"mine": {"out_at"} | None, "others": [names of others with it out, sorted]}`; this is `get_book(...)["loan"]`.
  - `loans.card(cfg, user_id) -> dict`:
    - `"out"`: `[{book card..., "out_at"}]`, the oldest first;
    - `"returned"`: `[{book card..., "out_at", "returned_at", "how"}]`, the newest first, all of them.
  - `loans.out_now(cfg) -> list[dict]`: `[{"book": card, "people": [names], "since"}]`, for the Activity page.
  - `loans.fill_in(cfg) -> int`: runs once (meta key `loans_filled_in`). For every person and book whose status is reading or incomplete, it opens a loan dated from that reading: the progress `updated_at`, or the hand mark's `set_at`. It doesn't log these.
  - Routes:
    - `POST /api/books/{id}/loan` (check out) and `DELETE /api/books/{id}/loan` (return): both return `loan_for`;
    - `GET /api/me/loans`: the card;
    - `GET /api/activity` also returns `"out_now"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_reading_checks_out_and_the_last_page_returns`: `save_progress` page 3 of 10 → one open loan; then page 9 of 10 → returned, how `finished`.
  - `test_a_finished_book_read_again`:
    1. after finishing, saving page 9 again creates no loan;
    2. saving page 2 opens a new loan;
    3. the card shows 1 returned and 1 out.
  - `test_thirty_quiet_days_return_it_as_abandoned`: read at t, `settle` at t + 30 days + 1 → returned at exactly t + 30 days, how `abandoned`, and a `loans.returned` entry in the log with that `at`.
  - `test_checked_out_by_button_and_never_read_is_abandoned_after_30_days`.
  - `test_return_early_keeps_the_place_and_status`: after `give_back`, `get_progress` and `status_for` are as before, and how is `returned`.
  - `test_status_by_hand_moves_the_loan`: covers all five mappings in `marked`.
  - `test_reopening_an_abandoned_book_checks_it_out_again`: via `statuses.opened`.
  - `test_others_see_who_has_it_but_can_still_read`:
    1. Ann checks out;
    2. Ben's `loan_for` gives `others == ["ann"]`;
    3. Ben's `save_progress` works and gives Ben his own loan.
  - `test_two_check_outs_at_once_leave_one_open_loan`: threads; `COUNT(*) WHERE returned_at IS NULL == 1`.
  - `test_fill_in_once_from_current_reading`: one reading, one incomplete, one finished and one unread → 2 open loans. A second call adds none.
  - `test_the_card_and_routes`.
- [ ] **Step 2: Run them; they fail.** Command: `bash test.sh tests/test_loans.py -q`.
- [ ] **Step 3: Implement.** Call `fill_in` from `create_app` after the database is opened, in a `try` that logs and carries on.
- [ ] **Step 4: Run them; they pass.** Then run `bash test.sh -q`. `test_reading_is_never_logged` (Task 2) must still pass.
- [ ] **Step 5: Commit:** "Checking out and returning, kept in step with reading".

---

### Task 5: The web app: stars, loans and going to a page

**Files:**
- Create:
  - `src/loft/web/js/pagejump.js`: pure helpers;
  - `src/loft/web/js/stars.js`: the stars control;
  - `tests/js/pagejump.test.mjs`.
- Modify:
  - `src/loft/web/js/reader.js`: the "Page x of y" button and box, `G`, the finish prompt;
  - `src/loft/web/js/book.js`: stars and the loan line;
  - `src/loft/web/js/grid.js`: the sort option;
  - `src/loft/web/style.css`.

**Interfaces:**
- Consumes:
  - `PUT /api/books/{id}/rating` → `{mine, average, count}`;
  - `POST`/`DELETE /api/books/{id}/loan` → `{mine, others}`;
  - `get_book` fields `rating` and `loan`.
- Produces:
  - `pagejump.js` exports:
    - `targetPage(text: string, count: number): number | null`: the 0-based page index. It clamps to `[0, count-1]`, returns null for text without a number, and treats `count < 1` as unknown (returns null).
    - `averageText(average, count): string`: e.g. `"4.2 from 3 readers"`, `"5 from 1 reader"`, or `""` when count is 0.
  - `stars.js` exports `starsHTML(mine: number | null, { label })` and `wireStars(root, onPick: (stars | null) => Promise<void>)`:
    - five buttons with `aria-pressed`, each labelled "1 star" … "5 stars";
    - arrow keys move between them;
    - picking the current rating sends null.

- [ ] **Step 1: Write the failing JS tests** for `targetPage` and `averageText`:
  - `targetPage("12", 340) === 11`, `("0", 340) === 0`, `("999", 340) === 339`, `("p. 7", 340) === 6`, `("", 340) === null`, `("12", 0) === null`;
  - `averageText(4.25, 3) === "4.3 from 3 readers"` (the server already rounds; the client shows one decimal and drops ".0", so `averageText(5, 1) === "5 from 1 reader"`);
  - `averageText(null, 0) === ""`.
- [ ] **Step 2: Run them; they fail.** Command: `node --test tests/js/pagejump.test.mjs`.
- [ ] **Step 3: Implement**, in this order.
  1. **Helpers:** `pagejump.js` and `stars.js`.
  2. **Reader:**
     - `.reader-where` becomes a `<button>`.
     - Clicking it, or `G`, replaces it with `<input inputmode="numeric" aria-label="Go to page">` holding the current page number.
     - Enter → `goTo(targetPage(...))`; Escape or blur → put the button back.
     - In Scroll mode it scrolls to that page.
     - While a flowing book is still being laid out (the bar shows "Chapter x of y"), the box uses the count known so far.
  3. **Finish prompt:** when `goTo` reaches the last page and the book has no rating of yours, show a bar with "How was it?", `starsHTML(null)` and a close button.
     - Don't show it again for that book on this device: localStorage `loft-asked-rating-<bookId>`, wrapped in try/catch.
     - Rating there calls the API.
  4. **Book page:**
     - stars under the title, with `averageText` beside them;
     - a loan line: "Checked out to you since 3 November" with a **Return** button, or a **Check out** button;
     - when `others` is not empty, "Also checked out by Cassidy" ("Cassidy and Ben"; three or more: "Cassidy, Ben and 2 others").
  5. **Grid:** add "Highest rated" to the sort choices.
  6. **CSS:** stars in `--brass`, unpicked stars as outlines; the page box the size of the text it replaces; everything fits at 390px wide.
- [ ] **Step 4: Run the tests; they pass.** Command: `node --test tests/js/*.test.mjs && bash test.sh -q`.
- [ ] **Step 5: See it.** Start the throwaway Loft on 4610 with a fresh data folder: the e2e scripts in the scratchpad's `e2e/` and `smoke/` do this. Then:
  1. Rate a book. Check out and return one. Go to page 30 of the PDF and of the EPUB. Reach the end of a short book and see the prompt.
  2. Run `smoke.py` (desktop and phone, as admin and as member).
  Expected: no console errors and no sideways scrolling.
- [ ] **Step 6: Commit:** "Stars, checking out and going to a page in the web app".

---

### Task 6: The library card and the Activity page

**Files:**
- Create: `src/loft/web/js/card.js` (`#/card`), `src/loft/web/js/activity.js` (`#/activity`)
- Modify:
  - `src/loft/web/js/main.js`: the routes; `#/activity` for admins only;
  - `src/loft/web/js/settings.js`: a link to the library card in the Account section;
  - the account menu in the top bar (`main.js`): "Library card";
  - `src/loft/web/js/admin.js`: an "Activity" link at the top of Library settings;
  - `src/loft/web/style.css`;
  - `src/loft/web/sw.js`: add `"card"`, `"activity"`, `"pagejump"` and `"stars"` to SHELL.

**Interfaces:**
- Consumes: `GET /api/me/loans`; `GET /api/activity` (with `out_now`, `people` and `groups`).

**Library card page:**
- Heading "Your library card".
- **Checked out** list: cover, title and "since 3 November".
- **Returned** list: cover, title, "3 – 20 November" and how ("Finished", "Abandoned", "Returned early").
- Empty states:
  - nothing out: "Nothing checked out. Open a book to check it out."
  - nothing returned: "Books you finish or return show here."

**Activity page:**
- Heading "Activity".
- **Checked out now** at the top: "4 books are checked out", expandable to book → people and since.
- Filters: two selects, Person and Kind (`groups`).
- Entries grouped under day headings ("Today", "Yesterday", "Monday 22 November"). Each line reads: time, then person, then text, then book link.
  - Missing people or books show their names without links.
  - `books.edited` details list the fields.
- "Show more" loads the next page with `before`.

- [ ] **Step 1: Write the failing tests:**
  - `tests/test_api.py::test_activity_page_routes_need_admin`: the API is already tested, so this only asserts that `/api/activity` returns `out_now` (Task 4) and `people`.
  - A `tests/js` test for a pure `dayHeading(at, now)` exported from `activity.js`:
    - same day → "Today"; the day before → "Yesterday";
    - older → `"Monday 22 November"`, adding the year when it isn't this year.
- [ ] **Step 2: Run them; they fail.** Command: `node --test tests/js/*.test.mjs`.
- [ ] **Step 3: Implement both pages and the links.**
- [ ] **Step 4: Run the tests; they pass.** Then see both pages on the throwaway Loft at 1280px and 390px, as admin and as member: the member gets "There’s nothing here." for `#/activity`. Run `smoke.py` with `#/card` and `#/activity` added to its routes.
- [ ] **Step 5: Commit:** "Your library card, and the admins' Activity page".

---

### Task 7: 0.2.0 notes and version

**Files:**
- Modify:
  - the version in `pyproject.toml`, `uv.lock`, `desktop/package.json`, `desktop/package-lock.json` (2 places), `android-lite/build.sh` (`VERSION_NAME` 0.2.0, `VERSION_CODE` 10) and `docker/zimaos.yaml`;
  - `src/loft/web/whatsnew.json`: a 0.2.0 entry;
  - `CHANGELOG.md`;
  - `docs/releases/0.2.0.md`;
  - `src/loft/web/sw.js`: `loft-shell-v10`, if the spines plan hasn't already set it.

**Notes:** the 0.2.0 notes cover the spines, going to a page, ratings, checking out and the library card, and the Activity page (admin). The fixes are:
- long titles no longer push pages wider than a phone;
- Kindle books show their own title and author;
- a new library's first scan no longer fails;
- the Windows tray's Restart no longer starts two servers;
- clearer messages for an empty library.

- [ ] **Step 1:** Make the changes above.
- [ ] **Step 2: Run everything.** Command: `bash test.sh -q && node --test tests/js/*.test.mjs`. `test_every_part_has_the_same_version` and `test_whatsnew` must pass.
- [ ] **Step 3: Commit:** "Loft 0.2.0". Don't tag or push; releasing waits for the user.
