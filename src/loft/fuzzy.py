"""Forgiving search: books found from the words someone remembers, best matches first.

Each word typed is matched with some slack against every word in the library (the start of a word,
part of one, a typo or two), and books are ranked by how much of what was typed they match: a word
counts fully when it's a whole word or the start of one in the title, series or authors, less as part
of a word or a typo, half in the tags and a quarter in the description (so a common word added to a
search, "book" or "novel", can't lift loosely matching books over the one meant), each word scaled
by how rare it is in the library. Then
by how well and where (a title counts more than an author), then by title. Apostrophes and hyphens
don't split words ("assassins" is "Assassin's"), and neighbouring words also count joined
("spiderman" is "Spider-Man"). Pure Python, no dependencies; an Index is built once and reused while
the library doesn't change (library.search).
"""

from __future__ import annotations

import math
import re
import unicodedata
from bisect import bisect_left, bisect_right
from typing import Iterable

WEIGHTS = {"title": 3.0, "series": 2.0, "authors": 2.0, "tags": 1.0, "description": 0.5}
JOINED = {"title", "series", "authors"}   # fields whose neighbouring words also count joined
LITTLE = frozenset("the a an of and or in on at to by for with".split())  # don't count, unless alone

PART_MIN = 3        # a part of a word counts from this many letters
EXACT, PREFIX, PART, TYPO = 1.0, 0.9, 0.75, 0.7
# How much a word typed counts towards a book's place: by how it matched, and by where. Words naming
# the book (title, series, authors) count fully; tags describe it, half; the description, a quarter.
STRENGTH = {EXACT: 1.0, PREFIX: 0.9, TYPO: 0.6, PART: 0.5}


def field_reach(weight: float) -> float:
    return min(1.0, weight / 2)   # title 3, series and authors 2 → 1; tags 1 → 0.5; description 0.5 → 0.25
MAX_WORDS, MAX_CHARS = 12, 300   # a pasted paragraph is cut short: each word costs a scan

_APOSTROPHES = re.compile(r"['’ʼ‘`]")
_NOT_WORD = re.compile(r"[\W_]+")


def normalize(text: str) -> str:
    """Lower case, no accents, no apostrophes; anything else that isn't a letter or digit is a space."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return _NOT_WORD.sub(" ", _APOSTROPHES.sub("", text)).strip()


def words(text: str) -> list[str]:
    return normalize(text).split()


def allowance(typed: str) -> int:
    """How many typos a word typed may have: none when short, one from 4 letters, two from 8."""
    return 2 if len(typed) >= 8 else 1 if len(typed) >= 4 else 0


def distance(a: str, b: str, limit: int) -> int:
    """Edits (a letter changed, missing, extra, or two swapped) from a to b; limit + 1 once past limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    before, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = i
        for j in range(1, len(b) + 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, before[j - 2] + 1)
            cur[j] = v
            best = min(best, v)
        if best > limit:
            return limit + 1
        before, prev = prev, cur
    return prev[-1]


def _close_start(a: str, b: str) -> bool:
    """A cheap first look before counting typos: the two words share a letter among their first two."""
    return bool(set(a[:2]) & set(b[:2]))


def word_score(typed: str, word: str) -> float:
    """How well a word typed matches a word in the library: exactly, its start, part of it, or a typo."""
    if typed == word:
        return EXACT
    if word.startswith(typed):
        return PREFIX
    if len(typed) >= PART_MIN and typed in word:
        return PART
    limit = allowance(typed)
    if limit and _close_start(typed, word) and distance(typed, word, limit) <= limit:
        return TYPO
    return 0.0


class Index:
    """Every word in the library, with the books (and how much the field it's in counts) it's in."""

    def __init__(self, books: Iterable[dict]) -> None:
        postings: dict[str, dict[int, float]] = {}
        alone: set[str] = set()   # words as they are (not only two words joined)
        self.sort: dict[int, str] = {}
        for b in books:
            bid = b["id"]
            self.sort[bid] = b.get("sort_title") or ""
            fields = (("title", [b.get("title")]), ("series", [b.get("series")]), ("authors", b.get("authors") or []),
                      ("tags", b.get("tags") or []), ("description", [b.get("description")]))
            for field, texts in fields:
                weight = WEIGHTS[field]
                for text in texts:
                    ws = words(text or "")
                    alone.update(ws)
                    joined = [x + y for x, y in zip(ws, ws[1:]) if x not in LITTLE and y not in LITTLE]
                    for t in ws + (joined if field in JOINED else []):
                        p = postings.setdefault(t, {})
                        if p.get(bid, 0.0) < weight:
                            p[bid] = weight
        self.vocab = sorted(postings)
        self.postings = [postings[w] for w in self.vocab]
        # Two words joined ("spider" "man": "spiderman") match only whole or from the start, never a
        # part across the join ("her" isn't in "blithe rover") or as a typo.
        self.joined_only = {i for i, w in enumerate(self.vocab) if w not in alone}
        # The whole vocabulary as one string, so a word's parts are found by the C string search.
        self.blob = "".join(w + "\n" for w in self.vocab)
        self.starts, at = [], 0
        for w in self.vocab:
            self.starts.append(at)
            at += len(w) + 1
        # Typo candidates: by length, and by each of the first two letters (see _close_start).
        self.near: dict[tuple[int, int, str], list[int]] = {}
        for i, w in enumerate(self.vocab):
            for pos in (0, 1):
                if pos < len(w):
                    self.near.setdefault((len(w), pos, w[pos]), []).append(i)

    def _matches(self, typed: str) -> dict[int, float]:
        """The vocabulary words (by index) a word typed matches, and how well."""
        found: dict[int, float] = {}
        if len(typed) >= PART_MIN:   # exact, start or part: wherever it is in the vocabulary
            at = self.blob.find(typed)
            while at >= 0:
                i = bisect_right(self.starts, at) - 1
                w = self.vocab[i]
                score = EXACT if w == typed else PREFIX if at == self.starts[i] else PART
                if score > found.get(i, 0.0) and not (score == PART and i in self.joined_only):
                    found[i] = score   # the best place in the word: "ent" starts "entertainment"
                at = self.blob.find(typed, at + 1)
        else:                        # short: exact or the start of a word only
            lo = bisect_left(self.vocab, typed)
            hi = bisect_left(self.vocab, typed + "￿")
            for i in range(lo, hi):
                found[i] = EXACT if self.vocab[i] == typed else PREFIX
        limit = allowance(typed)
        if limit:
            starts = set(typed[:2])
            checked: set[int] = set()
            for length in range(len(typed) - limit, len(typed) + limit + 1):
                for pos in (0, 1):
                    for ch in starts:
                        for i in self.near.get((length, pos, ch), ()):
                            if i not in found and i not in checked and i not in self.joined_only:
                                checked.add(i)
                                if distance(typed, self.vocab[i], limit) <= limit:
                                    found[i] = TYPO
        return found

    def rank(self, query: str, limit: int) -> list[int]:
        """Book ids, best match first: most words typed matched, then how well and where, then title."""
        typed = list(dict.fromkeys(words((query or "")[:MAX_CHARS])))
        typed = ([w for w in typed if w not in LITTLE] or typed)[:MAX_WORDS]
        reach: dict[int, float] = {}    # how much of what was typed the book matches (see STRENGTH)
        total: dict[int, float] = {}    # how well, and where
        for t in typed:
            strong: dict[int, float] = {}
            best: dict[int, float] = {}
            for i, score in self._matches(t).items():
                for bid, weight in self.postings[i].items():
                    s = STRENGTH[score] * field_reach(weight)
                    if s > strong.get(bid, 0.0):
                        strong[bid] = s
                    if score * weight > best.get(bid, 0.0):
                        best[bid] = score * weight
            # A word few books have says more about which one is meant than one many have ("graphic",
            # "novel", "book"): its part is scaled by how rare it is (1 + the usual BM25 rarity).
            rarity = 1.0 + math.log(1.0 + (len(self.sort) - len(strong) + 0.5) / (len(strong) + 0.5))
            for bid, s in strong.items():
                reach[bid] = reach.get(bid, 0.0) + s * rarity
                total[bid] = total.get(bid, 0.0) + best[bid]
        ranked = sorted(reach, key=lambda bid: (-round(reach[bid], 6), -total[bid], self.sort.get(bid, ""), bid))
        return ranked[:limit]
