"""The stacks: the whole library as bookcases, the way a library shelves it.

Cases are signed by series (then books in no series, by author), by section, or by author (by
surname, as libraries shelve). Filters narrow it: reading status, section, author, format; each
filter's choices come with how many books they'd show given the other filters. Each book carries
what its spine needs: its cover colour, and its size (pages when known, else the file's size).
"""

from __future__ import annotations

import json
from collections import defaultdict

from .config import Config
from .db import session
from .libsettings import get_library
from .library import book_card

KINDS = ("series", "section", "author")
STATUSES = ("unread", "reading", "finished")
OTHER = "Other"


UNKNOWN = "Unknown author"


def surname(name: str) -> tuple[str, str]:
    """How a library files a name: by its last word, then the whole name. No author goes last."""
    if name == UNKNOWN:
        return ("\uffff", "")
    parts = (name or "").split()
    return (parts[-1].casefold() if parts else "", (name or "").casefold())


def _section_of(tags: list[str], sections: list[dict]) -> str:
    have = {t.casefold() for t in tags}
    for s in sections:
        if have & {t.casefold() for t in s["tags"]}:
            return s["name"]
    return OTHER


def _books(cfg: Config, user) -> list[dict]:
    sections = get_library(cfg)["sections"]
    with session(cfg.db_path) as con:
        rows = con.execute("SELECT * FROM books").fetchall()
        files = defaultdict(list)
        for f in con.execute("SELECT f.book_id, f.format, f.size, p.count FROM book_files f "
                             "LEFT JOIN page_info p ON p.file_id = f.id AND p.mtime = f.mtime"):
            files[f["book_id"]].append(f)
        progress = {r["book_id"]: r for r in con.execute(
            "SELECT book_id, page, pages, position, finished FROM progress WHERE user_id = ?", (user.id,))}
    books = []
    for r in rows:
        card = book_card(r)
        tags = json.loads(r["tags"] or "[]")
        mine = files.get(r["id"], [])
        p = progress.get(r["id"])
        books.append({
            **card,
            "section": _section_of(tags, sections),
            "formats": sorted({f["format"] for f in mine}),
            "size": max((f["size"] or 0 for f in mine), default=0),
            "pages": max((f["count"] for f in mine if f["count"]), default=None),
            "progress": {"page": p["page"], "pages": p["pages"], "position": p["position"], "finished": bool(p["finished"])}
            if p else None,
            "status": "finished" if p and p["finished"] else "reading" if p else "unread",
            "_title": (r["sort_title"] or r["title"] or "").casefold(),
        })
    return books


def _order(b: dict) -> tuple:
    """Within a case: by author's surname, then series and number, then title."""
    first = b["authors"][0] if b["authors"] else ""
    index = b["series_index"] if b["series_index"] is not None else 1e9
    return (surname(first), (b["series"] or "").casefold(), index, b["_title"])


def stacks(cfg: Config, user, by: str = "series", status: str | None = None, section: str | None = None,
           author: str | None = None, fmt: str | None = None) -> dict:
    if by not in KINDS:
        raise ValueError(f"Shelve by one of: {', '.join(KINDS)}")
    if status and status not in STATUSES:
        raise ValueError(f"Reading status is one of: {', '.join(STATUSES)}")
    books = _books(cfg, user)
    tests = {
        "status": lambda b: not status or b["status"] == status,
        "section": lambda b: not section or b["section"] == section,
        "author": lambda b: not author or author in b["authors"],
        "format": lambda b: not fmt or fmt in b["formats"],
    }

    def passing(*skip: str) -> list[dict]:
        return [b for b in books if all(t(b) for name, t in tests.items() if name not in skip)]

    # Each filter's choices, counted with every other filter applied (so they say what you'd get).
    sections = [s["name"] for s in get_library(cfg)["sections"]] + [OTHER]
    facets = {
        "status": {s: sum(1 for b in passing("status") if b["status"] == s) for s in STATUSES},
        "section": {s: sum(1 for b in passing("section") if b["section"] == s) for s in sections},
        "author": dict(sorted(_count(a for b in passing("author") for a in b["authors"]).items(),
                              key=lambda kv: surname(kv[0]))),
        "format": dict(sorted(_count(f for b in passing("format") for f in b["formats"]).items())),
    }

    shown = passing()
    cases: list[dict] = []
    if by == "section":
        groups = defaultdict(list)
        for b in shown:
            groups[b["section"]].append(b)
        cases = [{"title": s, "kind": "section", "books": groups[s]} for s in sections if groups.get(s)]
    elif by == "author":
        # One case per letter of the surname, as a library's shelves run; the app puts a name card
        # between one author's books and the next.
        groups = defaultdict(list)
        for b in shown:
            groups[_letter(b)].append(b)
        cases = [{"title": letter, "kind": "letter", "books": groups[letter]} for letter in sorted(groups, key=_letter_order)]
    else:
        series, loose = defaultdict(list), []
        for b in shown:
            (series[b["series"]] if b["series"] else loose).append(b)
        cases = [{"title": s, "kind": "series", "books": series[s]} for s in sorted(series, key=str.casefold)]
        if loose:
            cases.append({"title": "Not in a series", "kind": "loose", "books": loose})

    for case in cases:
        case["books"] = [{k: v for k, v in b.items() if not k.startswith("_")}
                         for b in sorted(case["books"], key=_series_first if case["kind"] == "series" else _order)]
        case["count"] = len(case["books"])
    return {"by": by, "total": len(shown), "cases": cases, "facets": facets}


NO_AUTHOR = "No author"


def _letter(b: dict) -> str:
    if not b["authors"]:
        return NO_AUTHOR
    first = surname(b["authors"][0])[0][:1].upper()
    return first if first.isalpha() else "#"


def _letter_order(letter: str) -> tuple:
    return (letter == NO_AUTHOR, letter == "#", letter)


def _series_first(b: dict) -> tuple:
    index = b["series_index"] if b["series_index"] is not None else 1e9
    return (index, b["_title"])


def _count(items) -> dict:
    out: dict = defaultdict(int)
    for i in items:
        out[i] += 1
    return dict(out)


def sections_report(cfg: Config) -> dict:
    """For the admin arranging sections: how many books each holds, and what the books left in
    Other are tagged (the likeliest tags to give a section of their own)."""
    lib = get_library(cfg)
    sections = lib["sections"]
    counts: dict = defaultdict(int)
    left: dict = defaultdict(int)
    untagged = 0
    with session(cfg.db_path) as con:
        for r in con.execute("SELECT tags FROM books"):
            tags = json.loads(r["tags"] or "[]")
            where = _section_of(tags, sections)
            counts[where] += 1
            if where == OTHER:
                untagged += not tags
                for t in tags:
                    left[t] += 1
    return {"suggested": lib["sections_suggested"],
            "sections": [{**s, "count": counts.get(s["name"], 0)} for s in sections],
            "other": {"count": counts.get(OTHER, 0), "untagged": untagged,
                      "tags": [[t, n] for t, n in sorted(left.items(), key=lambda kv: (-kv[1], kv[0].casefold()))[:30]]}}
