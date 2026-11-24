"""Filling in new books' details by themselves: after each scan, every new book that's missing a
description, tags, an author or a cover (or whose title is only its file name) is looked up online.

Only a sure match is used: the same title, near enough (a letter or two apart), and when the book
has an author, the same author. Without an author the whole title has to match, or the match has
to say it's in the series the file name gives. Only what's missing is filled in, and fields the
admin set are left alone. What was filled is remembered, so each book can be put back as it was.

Books that were already in the library when this first ran aren't looked up by themselves; the
admin can send them through it from Library settings. Each book is looked up once (a source that
doesn't answer is tried again on later scans, up to three times).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from difflib import SequenceMatcher

from . import activity, editing, libsettings, lookups, openlibrary
from .config import Config
from .covers import remove_cover
from .db import session
from .notifications import admins, notify
from .openlibrary import LookupFailed, LookupsOff
from .scanner import index_book, locked_fields
from .titles import search_title, series_from_title

log = logging.getLogger(__name__)

STARTED = "autofill_started"   # meta key: set once the books already there were put aside
TRIES = 3
PAUSE = 1.0                    # seconds between books, to go easy on the services
COMICS = {"cbz", "cbr", "cb7"}
DETAILS = ("title", "authors", "series", "series_index", "description", "publisher", "published", "language", "tags")
SAME_TITLE, SAME_NAME = 0.9, 0.85
ARTICLE = re.compile(r"^(the|a|an) ")


# ---------- is this match the book? ----------

def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).casefold()
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).replace("&", " and ")
    t = re.sub(r"['’]", "", t)
    t = " ".join(re.sub(r"[^\w\s]", " ", t).split())
    return ARTICLE.sub("", t)


def _similar(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or SequenceMatcher(None, a, b).ratio() >= SAME_TITLE)


def _name(name: str) -> str:
    """"Ito, Junji" is Junji Ito."""
    if name.count(",") == 1:
        last, first = name.split(",")
        name = f"{first} {last}"
    return _norm(name)


def same_person(a: str, b: str) -> bool:
    a, b = _name(a), _name(b)
    if not a or not b:
        return False
    if a == b or SequenceMatcher(None, a, b).ratio() >= SAME_NAME:
        return True
    pa, pb = a.split(), b.split()
    return pa[-1] == pb[-1] and pa[0][0] == pb[0][0]  # "J. R. R. Tolkien" and "John Ronald Reuel Tolkien"


NUMBER_BIT = re.compile(r"^.*?(?:#|\bvol\.?|\bvolume|\bbook|\bno\.?)\s*\d+(?:\.\d+)?\s*[:\-–—]\s*", re.I)
BRACKETS = re.compile(r"\s*\([^()]*\)\s*$")


def _whole(title: str) -> set[str]:
    """A title said its usual ways: as given, without a bracketed "(Geronimo Stilton #53)", and without a
    leading "Geronimo Stilton #53:"."""
    t = search_title(title)
    return {_norm(v) for v in (t, BRACKETS.sub("", t), NUMBER_BIT.sub("", t))} - {""}


def _part(title: str) -> str:
    """"Revelations", of "Assassin's Creed: Revelations"."""
    t = BRACKETS.sub("", search_title(title))
    return _norm(t.rsplit(":", 1)[1]) if ":" in t else ""


def is_sure(title: str, authors: list[str], cand: dict) -> bool:
    theirs = cand.get("title") or ""
    their_authors = cand.get("authors") or []
    if not their_authors:
        return False
    ours_n, theirs_n = series_from_title(title), series_from_title(theirs)
    if ours_n and theirs_n and ours_n[1] != theirs_n[1]:
        return False  # #1 and #2 of the same thing
    ours = _whole(title)
    names = _whole(theirs) | {_norm(BRACKETS.sub("", search_title(theirs)).split(":", 1)[0])}
    if authors:
        if not any(same_person(a, b) for a in authors for b in their_authors):
            return False
        return any(_similar(o, t) for o in ours | {_part(title)} for t in names | {_part(theirs)})
    if any(_similar(o, t) for o in ours for t in names):
        return True
    # Only the part title matches ("Revelations" for "#04 Assassin's Creed - Revelation"): sure only
    # when the match itself names the series.
    part, tidy = _part(title), search_title(title)
    series = _norm(ours_n[0] if ours_n else tidy.rsplit(":", 1)[0] if part else "")
    said = _norm(f"{theirs} {cand.get('description') or ''}")
    return bool(part and series) and any(_similar(part, t) for t in names | {_part(theirs)}) \
        and f" {series} " in f" {said} "


def series_for(title: str, theirs: str) -> tuple[str, float] | None:
    """The series the book's own title gives, else the match's title; but not "Mighty Mount
    Kilimanjaro #41" making a series of the book's own name."""
    found = series_from_title(title)
    if found:
        return found
    found = series_from_title(theirs)
    if found and _norm(found[0]) not in _whole(title):
        return found
    return None


# ---------- the queue ----------

def needs_details(row, locked: set[str]) -> bool:
    return (not row["description"] or not json.loads(row["tags"] or "[]") or not json.loads(row["authors"] or "[]")
            or not row["has_cover"] or (row["title_from_name"] == 1 and "title" not in locked))


def _enqueue(cfg: Config) -> None:
    """New books join the queue. The first time, the books already there are put aside instead."""
    with session(cfg.db_path) as con:
        started = con.execute("SELECT 1 FROM meta WHERE key = ?", (STARTED,)).fetchone()
        state = "waiting" if started else "before"
        con.execute("INSERT INTO autofill(book_id, state) SELECT id, ? FROM books "
                    "WHERE id NOT IN (SELECT book_id FROM autofill)", (state,))
        if not started:
            con.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (STARTED, str(time.time())))


def _next(cfg: Config, after: int) -> int | None:
    """The next waiting book past `after`: each run asks about a book once."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT book_id FROM autofill WHERE state = 'waiting' AND book_id > ? "
                          "ORDER BY book_id LIMIT 1", (after,)).fetchone()
    return row["book_id"] if row else None


def _record(cfg: Config, book_id: int, state: str, **values) -> None:
    values = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in values.items()}
    sets = ", ".join(f"{k} = ?" for k in ("state", "at", *values))
    with session(cfg.db_path) as con:
        con.execute(f"UPDATE autofill SET {sets} WHERE book_id = ?", (state, time.time(), *values.values(), book_id))


def run(cfg: Config, pause: float = PAUSE) -> int:
    """Look up every waiting book. Returns how many were filled in."""
    lib = libsettings.get_library(cfg)
    if not lib["online_lookups"] or not lib["auto_lookup"]:
        return 0
    _enqueue(cfg)
    filled = book_id = 0
    while (book_id := _next(cfg, book_id)) is not None:
        try:
            filled += fill_book(cfg, book_id) == "filled"
        except LookupsOff:
            break
        except Exception:
            log.exception("Couldn't fill in book %s", book_id)
            _record(cfg, book_id, "unsure")
        if not libsettings.get_library(cfg)["auto_lookup"]:
            break  # switched off part way
        time.sleep(pause)
    if filled:
        with session(cfg.db_path) as con:
            notify(con, admins(con), "autofill",
                   f"Filled in details for {filled} new {'book' if filled == 1 else 'books'}", "#/filled")
    return filled


# ---------- filling one book ----------

def _fit(field: str, value):
    """A looked-up value cut to what a book's details may hold."""
    if field in ("authors", "tags"):
        most, longest = (editing.MAX_AUTHORS, editing.MAX_AUTHOR) if field == "authors" else (editing.MAX_TAGS, editing.MAX_TAG)
        return [v for v in value if isinstance(v, str) and 0 < len(v.strip()) <= longest][:most]
    return value[:editing.LIMITS[field]] if field in editing.LIMITS else value


def _valid(field: str, value) -> bool:
    try:
        editing.clean_details({field: value})
        return True
    except ValueError:
        return False


def _current(row, field: str):
    if field in ("authors", "tags"):
        return json.loads(row[field] or "[]")
    return row[field]


def fill_book(cfg: Config, book_id: int) -> str:
    """Look the book up and fill in what it's missing from a sure match. Returns the new state."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if row is None:
            return "gone"
        locked = locked_fields(con, book_id)
        formats = {r["format"] for r in con.execute("SELECT format FROM book_files WHERE book_id = ?", (book_id,))}
        tries = con.execute("SELECT tries FROM autofill WHERE book_id = ?", (book_id,)).fetchone()["tries"]
    if not needs_details(row, locked):
        _record(cfg, book_id, "complete")
        return "complete"

    authors = json.loads(row["authors"] or "[]")
    query = {"title": search_title(row["title"]), "comic": bool(formats & COMICS), "lang": row["language"] or "en"}
    try:
        found = lookups.search(cfg, author=authors[0] if authors else "", **query)
        if not found and authors:
            found = lookups.search(cfg, author="", **query)
    except LookupFailed:
        state = "unsure" if tries + 1 >= TRIES else "waiting"
        _record(cfg, book_id, state, tries=tries + 1)
        return state
    sure = [c for c in found if is_sure(row["title"], authors, c)]
    if not sure:
        _record(cfg, book_id, "unsure")
        return "unsure"

    patch: dict = {}
    sources: list[str] = []
    can = lambda f: f not in locked and f not in patch and not _current(row, f)  # noqa: E731
    for c in sure:
        before = len(patch)
        if row["title_from_name"] == 1 and "title" not in locked and "title" not in patch and _valid("title", c["title"]):
            patch["title"] = c["title"]
        for f in ("authors", "tags", "publisher", "published", "language"):
            if can(f) and c.get(f) and _valid(f, _fit(f, c[f])):
                patch[f] = _fit(f, c[f])
        if can("description"):
            text = c.get("description") or ""
            if not text and c.get("key"):
                try:
                    text = openlibrary.description(cfg, c["key"])
                except (LookupFailed, ValueError):
                    text = ""
            if text and _valid("description", _fit("description", text)):
                patch["description"] = _fit("description", text)
        if len(patch) > before and c["source"] not in sources:
            sources.append(c["source"])
    if can("series"):
        # A source that knows the series (Hardcover) says it best; else the titles do.
        told = next((c for c in sure if c.get("series") and _valid("series", c["series"])), None)
        s = (told["series"], told.get("series_index")) if told else series_for(row["title"], sure[0]["title"])
        if told and told["source"] not in sources:
            sources.append(told["source"])
        if s:
            patch["series"], patch["series_index"] = s[0], None if s[1] is None else float(s[1])
    patch = {k: v for k, v in patch.items() if v not in ("", [], None) or k == "series_index"}

    previous = {f: _current(row, f) for f in patch}
    if patch:
        editing.edit_book(cfg, book_id, patch)
    filled = list(patch)
    cover_colour = None
    if not row["has_cover"] and "cover" not in locked:
        for c in sure:
            if not c.get("cover_url"):
                continue
            try:
                editing.set_cover(cfg, book_id, openlibrary.fetch_cover(cfg, c["cover_url"]))
            except (LookupFailed, ValueError):
                continue
            filled.append("cover")
            if c["source"] not in sources:
                sources.append(c["source"])
            with session(cfg.db_path) as con:
                cover_colour = con.execute("SELECT cover_color FROM books WHERE id = ?", (book_id,)).fetchone()[0]
            break
    if not filled:
        _record(cfg, book_id, "complete")
        return "complete"
    after = {**patch, **({"cover": cover_colour} if "cover" in filled else {})}
    _record(cfg, book_id, "filled", tries=tries + 1, sources=sources, filled=filled, previous=previous, after=after)
    activity.note(cfg, "books.filled", f"filled in {', '.join(filled)} automatically", book_id=book_id,
                  details={"fields": filled})
    return "filled"


# ---------- what was done, and undoing it ----------

def undo(cfg: Config, book_id: int, by=None) -> None:
    """Put the book back as it was: each field still as it was filled in goes back (and is free for
    scans again); anything changed since stays. The book isn't looked up by itself again. `by` is
    the admin who asked, for the activity log."""
    with session(cfg.db_path) as con:
        rec = con.execute("SELECT * FROM autofill WHERE book_id = ? AND state = 'filled'", (book_id,)).fetchone()
        row = con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if rec is None or row is None:
            raise LookupError(book_id)
        previous, after = json.loads(rec["previous"]), json.loads(rec["after"])
        columns: dict = {}
        freed: set[str] = set()
        for field, old in previous.items():
            now = _current(row, field)
            if field == "series_index" or now != after.get(field):
                continue
            freed.add(field)
            if field == "title":
                from .scanner import sort_title
                columns.update(title=old, sort_title=sort_title(old))
            elif field == "authors":
                columns.update(authors=json.dumps(old), author_sort=old[0] if old else "")
            elif field == "tags":
                columns["tags"] = json.dumps(old)
            else:
                columns[field] = old
                if field == "series":
                    columns["series_index"] = previous.get("series_index")
                    freed.add("series_index")
        if "cover" in after and row["has_cover"] and row["cover_color"] == after["cover"]:
            remove_cover(cfg, book_id)
            columns.update(has_cover=0, cover_color=None, spine_colors=None)
            freed.add("cover")
        columns.update(locked=json.dumps(sorted(locked_fields(con, book_id) - freed)), updated_at=time.time())
        con.execute(f"UPDATE books SET {', '.join(f'{k} = ?' for k in columns)} WHERE id = ?",
                    (*columns.values(), book_id))
        index_book(con, book_id)
        con.execute("UPDATE autofill SET state = 'undone', at = ? WHERE book_id = ?", (time.time(), book_id))
        activity.record(con, "books.unfilled", "undid the automatic details", book_id=book_id,
                        user_id=by.id if by else None, user_name=by.username if by else "")


def overview(cfg: Config, most: int = 100) -> dict:
    from .library import book_card
    with session(cfg.db_path) as con:
        filled = [{"book": book_card(r), "fields": json.loads(r["filled"]), "sources": json.loads(r["sources"]),
                   "at": r["at"]}
                  for r in con.execute("SELECT b.*, a.filled, a.sources, a.at FROM autofill a JOIN books b ON b.id = a.book_id "
                                       "WHERE a.state = 'filled' ORDER BY a.at DESC LIMIT ?", (most,))]
        unsure = [book_card(r) for r in con.execute(
            "SELECT b.* FROM autofill a JOIN books b ON b.id = a.book_id WHERE a.state = 'unsure' "
            "ORDER BY a.at DESC LIMIT ?", (most,))]
        before = sum(needs_details(r, locked_fields(con, r["id"])) for r in con.execute(
            "SELECT b.* FROM autofill a JOIN books b ON b.id = a.book_id WHERE a.state = 'before'"))
        waiting = con.execute("SELECT COUNT(*) FROM autofill WHERE state = 'waiting'").fetchone()[0]
    return {"filled": filled, "unsure": unsure, "before": before, "waiting": waiting}


def look_up_the_rest(cfg: Config) -> int:
    """The books that were there before, and those without a sure match: into the queue."""
    _enqueue(cfg)
    with session(cfg.db_path) as con:
        return con.execute("UPDATE autofill SET state = 'waiting', tries = 0 WHERE state IN ('before', 'unsure')").rowcount


class AutoFiller:
    """Runs the queue in the background whenever it's woken (after each scan, or when asked)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.running = False
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def trigger(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="loft-autofill", daemon=True)
            self._thread.start()
        self._wake.set()

    def _loop(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            self.running = True
            try:
                run(self.cfg)
            except Exception:
                log.exception("Filling in new books failed")
            finally:
                self.running = False
