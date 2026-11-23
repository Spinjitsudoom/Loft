# Reading status: design

## Why

Loft only knows Not started, Reading and Finished, all worked out from where you are in a book. You
can't say you've stopped a book or given up on it, and a dropped book sits in "Continue reading" for
good. Each person should have a status for each book that keeps itself up to date, and that they can
set by hand.

## The statuses

Each person's own, for each book: **Want to read, Not started, Reading, Incomplete, Abandoned,
Finished.**

- **Reading**: opening (reading) a book.
- **Incomplete**: automatically, a book not read for **15 days**.
- **Abandoned**: automatically, a book not read for **30 days** (counted from the last reading, as
  Incomplete is).
- **Finished**: reaching the last page, as now.
- **Want to read**: only by hand. It stays the shelf it is (it can't be renamed or removed); a book on
  it shows Want to read.
- **Any status can be set by hand** from the book's page. A status set by hand holds until the book
  is read again. Reading it again makes it Reading (or Finished, at the last page).
  - Set to Reading or Incomplete by hand, it ages from when it was set, as if read then.

## Goals

- **Home:**
  - "Continue reading" (and the big book at the top) shows only books that are Reading.
  - A new **Incomplete** row comes after your shelves, so stopped books are easy to pick up again.
  - The Finished row shows books whose status is Finished, including ones marked by hand.
- **Stacks:** the Reading filter offers every status.
- **Book page:** a status button shows the book's status and changes it.
- **Discussion:** someone whose status is Finished (by hand too) sees every message unblurred.
- Merging two books keeps a status set by hand (the newer one wins).

## Anti-goals

- **No background job.** A status must never be stale because the server was off.
- Want to read is never set automatically.

## Approaches

1. **Work the status out when it's needed (chosen).** Loft already records when each book was last
   read. The status comes from three times: the last reading, the last status set by hand, and when
   the book went on Want to read. The latest one decides it, plus the 15- and 30-day ages. Nothing
   runs in the background.
2. **Store a status and update it daily.** This needs another scheduled job, goes stale while the
   server is off, and lags behind reading.

## How

- **A new `book_status` table:** `user_id`, `book_id`, `status`, `set_at`, holding the statuses set by
  hand (`unread`, `reading`, `incomplete`, `abandoned`, `finished`). Want to read stays the shelf.
  - Setting Want to read (re)adds the book to that shelf.
  - Setting any other status takes the book off it.
  - Reading a book takes it off Want to read, as said in the conversation.
- **A pure function:** given a book's last reading (time, finished), the status set by hand (and when),
  when it went on Want to read, and now, it returns the status. The latest event wins:
  - Want to read: `want`.
  - Set by hand:
    - `unread`, `abandoned` and `finished` hold;
    - `reading` ages from when it was set: Incomplete at 15 days, Abandoned at 30;
    - `incomplete` becomes Abandoned 30 days after it was set.
  - Reading: `finished` at the last page, otherwise it ages from the reading time. With nothing at
    all, the book is Not started.
- **API:**
  - `GET` and `PUT /api/books/{id}/status` take and return `{status, shelves}`;
  - `GET /api/books/{id}` carries `status`;
  - `/api/books?kind=status&value=<status>` lists your books with that status (`kind=finished` still
    works).

## Left to the builder

The look of the status button and menu (alongside the Shelves button), and the wording of its hint.
