# Forgiving search: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/api/search` finds books from keywords: ranked, typo-tolerant, apostrophe- and hyphen-proof, and
searching descriptions too.

**Architecture:** A pure `src/loft/fuzzy.py` normalizes text, scores a typed word against an indexed word,
and ranks books from an in-memory word index. `library.search` keeps one index per database, rebuilt when
the books change, and returns book cards in ranked order.

**Tech Stack:** Python 3 standard library only; `pytest` (`bash test.sh -q`).

**Spec:** `docs/superpowers/specs/2026-11-23-fuzzy-search-design.md`

## Global Constraints

- No new dependencies. Don't commit; the user commits when they ask. Work on `master` in place.
- After the Python changes: `systemctl --user restart loft-test`.
- Values from the spec:
  - a part of a word counts from **3** letters;
  - typos: **1** for words of 4 letters or more, **2** for words of 8 or more;
  - fields, most to least: title, series, author, tags, description;
  - at least one word must match.
- Little words: `the a an of and or in on at to by for with`. They're ignored unless they're all that was
  typed.

## Review Focus

1. A huge library: about 20,000 books with descriptions. A search must stay well under a second (target
   under 150 ms after the first). Pinned by a timing test in Task 1 (generous bound).
2. A query of only punctuation or little words returns `[]`, not every book. Pinned in Task 2 (the existing
   `test_search` cases).
3. A book edited, added or removed is reflected in the next search (the index cache). Pinned in Task 2.
4. Short words: `"ost"`, `"nig"` keep working, but a 1–2 letter word must not match the middle of other
   words. Pinned in Task 1.
5. Ranking: a book with all the words in its title comes before one with a word only in its description.
   Pinned in Task 2.

---

### Task 1: `fuzzy.py`, the matching

**Files:**
- Create: `src/loft/fuzzy.py`
- Test: `tests/test_fuzzy.py`

**Interfaces:**
- Produces:
  - `normalize(text: str) -> str`: NFKD, accents dropped, casefolded, apostrophes (`'`, `’`, `ʼ`) removed,
    every other non-letter or digit becomes a space, spaces collapsed.
  - `words(text: str) -> list[str]`
  - `word_score(typed: str, word: str) -> float`:
    - `1.0` exact;
    - `0.9` prefix;
    - `0.75` part of a word (typed ≥ 3 letters);
    - `0.7` within the typo allowance (bounded edit distance with swaps: ≤1 for typed ≥ 4, ≤2 for typed ≥ 8);
    - `0.0` otherwise.
  - `WEIGHTS = {"title": 3.0, "series": 2.0, "authors": 2.0, "tags": 1.0, "description": 0.5}`
  - `class Index`:
    - `__init__(self, books: Iterable[dict])`. Each dict has `id`, `title`, `series`, `authors` (list),
      `tags` (list), `description` and `sort_title`. Each field's words are indexed, plus each pair of
      neighbouring title, series and author words joined.
    - `rank(self, query: str, limit: int) -> list[int]` returns ids ordered by:
      1. the number of the query's (non-little) words matched, high first;
      2. the sum over those words of their best `word_score × WEIGHTS[field]` in that book, high first;
      3. `sort_title`.

      It scans the distinct-word vocabulary once per query word. It skips the edit-distance check when the
      lengths differ by more than the allowance.

- [ ] **Step 1: Write the failing tests.**

```python
from loft.fuzzy import Index, normalize, word_score

def test_normalize():
    assert normalize("Assassin’s Creed: Odyssey") == "assassins creed odyssey"
    assert normalize("Spider-Man  Öst") == "spider man ost"

def test_word_scores():
    assert word_score("wedding", "wedding") == 1.0
    assert word_score("nig", "night") == 0.9
    assert word_score("crash", "crashers") == 0.9 and word_score("rasher", "crashers") == 0.75
    assert word_score("weding", "wedding") == 0.7          # one missing letter
    assert word_score("wdeding", "wedding") == 0.7         # one swap (7 letters: 1 allowed)
    assert word_score("asassinss", "assassins") == 0.7     # two, in a long word
    assert word_score("cat", "cot") == 0.0                 # too short for a typo
    assert word_score("or", "okafor") == 0.0               # too short to match inside a word

def book(i, title, **kw):
    return {"id": i, "title": title, "series": kw.get("series", ""), "authors": kw.get("authors", []),
            "tags": kw.get("tags", []), "description": kw.get("description", ""), "sort_title": title.lower()}

def test_rank():
    ix = Index([book(1, "Wedding Crashers", authors=["Geronimo Stilton"], description="A mouse at a wedding"),
                book(2, "Spider-Man: Blue"), book(3, "Assassin's Creed: Odyssey"),
                book(4, "Mouse Island", description="no weddings here")])
    assert ix.rank("weding crashers", 10)[0] == 1
    assert ix.rank("geronimo stilton wedding book", 10)[0] == 1
    assert ix.rank("crashers geronimo mouse", 10)[0] == 1
    assert ix.rank("spiderman", 10) == [2] and ix.rank("spider man", 10)[0] == 2
    assert ix.rank("assassins creed", 10) == [3]
    assert ix.rank("mouse", 10) == [4, 1]                  # in the title beats in the description
    assert ix.rank("the", 10) == []                        # no book here has "the" as a word
    assert ix.rank("zzzz", 10) == []

def test_a_big_library_is_quick():
    import random, string, time
    rnd = random.Random(1)
    w = lambda: "".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(3, 10)))
    books = [book(i, " ".join(w() for _ in range(4)), authors=[w() + " " + w()],
                  description=" ".join(w() for _ in range(60))) for i in range(20000)]
    ix = Index(books)
    start = time.perf_counter(); ix.rank("quick brwn foxes jumped", 40)
    assert time.perf_counter() - start < 1.0
```
- [ ] **Step 2: Run them.**
  - Run: `~/.local/share/loft/venv/bin/python -m pytest tests/test_fuzzy.py -q`
  - Expected: FAIL (`ModuleNotFoundError: loft.fuzzy`).
- [ ] **Step 3: Implement `fuzzy.py` to the Interfaces above.**
- [ ] **Step 4: Run them.**
  - Expected: PASS. Print the big-library time and record it in the ledger.

### Task 2: `library.search` uses it

**Files:**
- Modify: `src/loft/library.py` (`search`; `FTS_KEYWORDS` goes)
- Test: `tests/test_library.py`

**Interfaces:**
- Consumes: `fuzzy.Index`, `Index.rank` (Task 1).
- Produces: `library.search(cfg, q, limit=40) -> list[dict]`, the same contract (book cards) in ranked order.
  - The index is cached per `cfg.db_path` under a lock.
  - The signature is `SELECT count(*), max(updated_at), max(id) FROM books`.
  - Little words: if every word is a little word, the query is used as typed. If nothing is left after
    `normalize`, it returns `[]`.

- [ ] **Step 1: Write the failing tests** (the existing `test_search` stays as it is):

```python
def test_search_forgives(cfg, add):
    add("Wedding Crashers", authors=["Geronimo Stilton"], description="A mouse wedding goes wrong")
    add("Assassin's Creed: Odyssey", authors=["Gordon Doherty"])
    add("Spider-Man: Blue", authors=["Jeph Loeb"])
    add("Mouse Island", authors=["Geronimo Stilton"])
    assert titles(library.search(cfg, "weding crashers"))[0] == "Wedding Crashers"
    assert titles(library.search(cfg, "crashers geronimo mouse"))[0] == "Wedding Crashers"
    assert titles(library.search(cfg, "geronimo stilton wedding book"))[0] == "Wedding Crashers"
    assert titles(library.search(cfg, "assassins creed")) == ["Assassin's Creed: Odyssey"]
    assert titles(library.search(cfg, "spiderman")) == ["Spider-Man: Blue"]
    assert titles(library.search(cfg, "mouse"))[:2] == ["Mouse Island", "Wedding Crashers"]

def test_search_sees_changes(cfg, add):
    add("Tide Line")
    assert titles(library.search(cfg, "atlas")) == []
    add("Night Atlas")
    assert titles(library.search(cfg, "atlas")) == ["Night Atlas"]
```

- [ ] **Step 2: Run them.**
  - Run: `… -m pytest tests/test_library.py -q -k search`
  - Expected: `test_search_forgives` FAILS (typo / extra word give nothing).
- [ ] **Step 3: Implement.** Read `id, title, sort_title, series, authors, tags, description` (JSON lists
  parsed) to build the index. Fetch the cards for the ranked ids in that order.
- [ ] **Step 4: Run the whole suite, restart the test server, and try the spec's searches against loft-dev.**
  - Run: `bash test.sh -q`, then `systemctl --user restart loft-test`.
  - Check through `library.search` on a copy of `~/.local/share/loft-dev/loft.db` (copied to the
    scratchpad; never written).
  - Expected: all pass. Each of the spec's five searches puts the right book first.

### Task 3: Docs

- [ ] README: in the search line, say search forgives typos and finds books from keywords.
- [ ] CHANGELOG `## Unreleased`: "Search finds books from the words you remember: in any order, with typos,
  without apostrophes or hyphens, and from the description too; the best matches first."
- [ ] Final run: `bash test.sh -q && node --test tests/js/`.
