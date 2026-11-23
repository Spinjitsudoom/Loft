# Forgiving search: design

## Why

Search only finds a book when every word typed matches the start of a word in its title, authors,
series or tags. One typo or one extra word gives nothing. In the test library, these searches all come
back empty:

- `weding crashers`
- `crashers geronimo mouse` ("mouse" is only in the description)
- `geronimo stilton wedding book`
- `assassins creed` (the titles say "Assassin's")
- `spiderman` (the title says "Spider-Man")

People search with the keywords they remember, so search should find the book anyway.

## Goals

- Results are ranked:
  1. books matching the most of the words typed come first;
  2. then by how well, and where, they match;
  3. then by sort title.
- A book needs to match at least one word.
- Each word gets slack:
  - an exact word;
  - the start of a word ("nig" finds "Night");
  - a part of a word, 3 letters or more ("crash" finds "Crashers");
  - a typo: one wrong, missing, extra or swapped letter in words of 4 or more letters, two in words of 8
    or more.
- Apostrophes and hyphens don't split words: "assassins" matches "Assassin's". Two neighbouring words also
  match as one ("spiderman" finds "Spider-Man"). Accents are ignored, as now.
- Where a match counts, from most to least: title, series, author, tags, description.
- Little words ("the", "a", "of", "and"…) don't count, unless they're all that was typed.
- The same `/api/search` serves the search page and the book-request form's "you may already have this".

## Non-goals

- Searching inside the books' text.
- Search-as-you-type or suggestions. The pages work as now.

## Anti-goals

- Slow search. A search must stay quick on a library of tens of thousands of books.
- Noise outranking the book. A book whose title has every word typed must come before one that only
  mentions a word in its description.

## Approaches

1. **Ranked matching in Python over a word index, kept in memory (chosen).** On the first search, and
   again after the library changes, Loft builds an index of every distinct word with the books and fields
   it's in. A search scans that word list once per word typed. Every kind of slack above is possible, and
   it needs no new dependency.
2. **SQLite full-text search with OR and a trigram table.** It handles parts of words, but not typos or
   joined words.
3. **A fuzzy-matching library (rapidfuzz).** Fast, but it's a compiled dependency for every platform Loft
   ships on. Option 1 is fast enough without it.

## How

- A new `src/loft/fuzzy.py` holds the matching. It's pure and testable:
  - `normalize`;
  - `words`;
  - `word_score`;
  - an `Index` built from the books' rows, with `rank(query, limit)`.
- `library.search` keeps an index per database. It's rebuilt when a cheap signature changes (book count,
  newest `updated_at`, highest id), and returns book cards in ranked order.
- The `books_fts` table stays as it is (the scanner still writes it) but search no longer uses it.
