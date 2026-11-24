# Going to a page, ratings, checking out, and the activity log — design

## Why

The user wants Loft to feel more like a digital library: you borrow a book and give it back, you say what you thought of it, and the admin can see what's going on. Separately, they want to jump straight to a page instead of dragging the slider.

These ship in one update with the spines redesign (`2026-11-23-spines-design.md`) and the polish fixes already made.

## Goals

1. **Go to a page:** type a page number in the reader and go there.
2. **Ratings:** each person rates a book from 1 to 5 stars. Everyone sees the average.
3. **Checking out:** a book you're reading is checked out to you. It is returned when you finish it or it's abandoned. Each person keeps a record of what they borrowed and when.
4. **Activity log:** admins see what happened in the library, newest first. That covers people signing in and joining, books added, removed or edited, loans and returns, ratings, and the like.

## Non-goals

- **Locks and waiting lists.** A checked-out book can still be read by everyone else (the user's choice). There are no copies, holds or waiting lists.
- **Printed page numbers.** Some EPUBs carry the printed book's page numbers. Going to a page uses Loft's own page numbers, as shown in the reader.
- **Written reviews.** Ratings are stars only. The book's Discussion is where people write.
- **Logging page turns.** Reading itself isn't logged; it would bury everything else.
- **Logging the past.** The log starts when this version is installed, apart from the loan fill-in described below.

## Anti-goals

- A log that slows Loft down or grows without end.
- Members seeing the log. It is for admins only.
- Loans that disagree with the reading status in ways a person would notice. For example, "Reading" on the book's page while the library card says it was returned.

## Constraints

- No background jobs are added for loans. Like reading statuses, abandonment is worked out when it's asked for.
- Everything works offline in the reader as it does now. Ratings and checkouts need the server, like the status menu.
- The database gains tables through `db.SCHEMA` / `db.MIGRATIONS`. Existing libraries upgrade in place.

## Approaches considered

**Checking out:**

1. **A loans table, kept in step with reading (chosen).** A row per loan records who, which book, when it went out, when it came back and how. History and dates come for free, and the log can name each loan.
2. **Worked out from reading statuses only, no table.** Less code, but no history ("you borrowed this in March"). It also can't tell "returned early" from "abandoned".
3. **Loans as their own state, with a daily job closing abandoned ones.** Loft has no such job for statuses, and adding one only for loans would make the two drift apart.

**Activity log:**

1. **One `activity` table, written where each thing happens (chosen).** Each entry keeps the names as they were, so it still reads right after a book or person is deleted.
2. **Reading the server log.** Rejected: it's a log for diagnosing problems, it's rotated, and it doesn't say who did what.

## Design

### 1. Go to a page

**Opening the box.** In the reader's bottom bar, the "Page 12 of 340" text becomes a button. Tapping it (or pressing `G` on a keyboard) swaps it for a number box holding the current page.

**Going there.**
- Enter goes to that page. Escape or tapping away cancels.
- A number past the end goes to the last page; 0 or less goes to the first.

**Where it works.** In every reader: flowing books, comics, PDFs and picture books, in both page and Scroll mode.

**On a phone,** the number box opens the number keypad (`inputmode="numeric"`).

### 2. Ratings

**Rating a book.**
- On the book's page, under the title, there are five stars: your rating.
- Tapping a star sets it. Tapping the star you already gave clears it.
- Ratings are whole stars, 1 to 5.

**The average.**
- It shows beside your stars, as "4.2 from 3 readers", and only once someone has rated the book.
- *My call:* individual ratings are private. Members see only the average and count. Admins see who rated what in the activity log.

**Asking when you finish.** When you reach the last page, a small bar at the bottom of the reader asks "How was it?" with the five stars.
- It can be dismissed, and it isn't asked again for that book.
- It's not shown if you already rated the book.

**Sorting.** Book lists ("See all", search results) gain a **Highest rated** sort, by average and then by how many rated.

**Stored** in `ratings(user_id, book_id, stars, rated_at)`, one row per person per book. Deleting a person or book deletes their ratings.

### 3. Checking out

**Stored** in `loans(id, user_id, book_id, out_at, returned_at, how)`:
- `how` is `finished`, `abandoned` or `returned`, and is NULL while the book is out.
- A person has at most one open loan per book.

**When a book goes out:**
- **Opening a book to read** checks it out, if it isn't already out to you. It happens at the same moment opening a book makes its status Reading: when the reader saves your place.
- **The Check out button** on the book's page checks it out without opening it. It is shown when the book isn't out to you.

**When it comes back:**
- **Finished:** reaching the last page. Setting the status to Finished by hand counts too.
- **Abandoned:** when the reading status turns Abandoned, i.e. 30 days without reading. Setting it to Abandoned by hand counts too.
  - The loan is closed when this is next worked out, with `returned_at` set to when it became abandoned (last reading + 30 days).
  - A loan checked out with the button and never read is abandoned 30 days after it went out.
- **Returned:** the **Return** button on the book's page, shown while the book is out to you.
  - It ends the loan without changing the reading status or your place.
  - Opening the book again later starts a new loan.

**The book's page shows:**
- your loan: "Checked out to you since 3 November", with **Return**;
- or the **Check out** button;
- and who else has it out: "Also checked out by Cassidy".
  - *My call:* the names are shown to everyone in the library, as a library would show who has a book out, and as the Discussion already shows who's reading.

**Your library card.** A new page, reached from Your settings and from the account menu, lists:
- **Checked out now:** each book with the date it went out.
- **Returned:** newest first, with the date and how it came back (Finished, Abandoned, Returned early).

**Existing libraries.** When upgrading, every book a person has as Reading or Incomplete gets an open loan dated from their last reading. Finished and abandoned books get no history, because it isn't known when they were borrowed.

### 4. Activity log

**Stored** in `activity(id, at, user_id, user_name, kind, book_id, book_title, text, details)`:
- The names are copied in when the entry is written.
- `user_id` is NULL for Loft itself (scans, backups, updates).
- `details` is JSON for kinds that need more, such as which fields an edit changed.

**What's logged:**

| Kind | Entry |
|---|---|
| Sign-ins | signed in; failed sign-in (with the name tried) |
| People | asked to join; approved; added by an admin; removed; made admin or not |
| Books | added (scan, upload, approved submission); removed (deleted, or gone from the folder); details edited (which fields); cover changed; details filled in automatically (and undone) |
| Loans | checked out; returned (finished, abandoned, early) |
| Ratings | rated a book (the stars); cleared a rating |
| Requests | asked for a book; request fulfilled; book submitted |
| Discussion | commented on a book (not the text) |
| Loft | library scan (how many added, changed, removed, and only when something changed); backup made or restored; new version downloaded; installed; library settings changed (which ones) |

**The Activity page** (`#/activity`, admins only) is linked from Library settings.
- Newest first, grouped by day, loading more as you scroll.
- Filters: person, and kind (Sign-ins, People, Books, Loans, Ratings, Requests, Discussion, Loft).
- Each entry links to its book or person when they still exist.
- At the top, **Checked out now** shows how many books are out and to whom.

**Kept for a year.** Older entries are removed when new ones are written, at most once a day.

**Writing never stands in the way.** A log entry that can't be written is itself logged to the server log, and the action it records goes ahead.

### Version

All of this, with the spines and the polish fixes, ships as **0.2.0**. *My call:* this is the first update that changes what Loft is, not only how well it works.

## Left to the builder

- Exact markup and styling of the stars, the page box, the library card and the Activity page, in Loft's existing look.
- How loan closing is wired into `statuses`. It is worked out wherever statuses are, kept in one module.
- Batch sizes and paging for the Activity page; the indexes the tables need.
