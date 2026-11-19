"""The library check: one list of what needs the admin's attention, each with a direct fix.

Files are tried once after each scan (only new or changed ones), so damaged and protected books
show up without anyone having to open them. Everything else is worked out on request. Anything can
be ignored so the list stays useful.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from . import flowbooks, pages
from .config import Config
from .db import session
from .filemeta import read_file_meta
from .flow import READABLE_FLOW
from .pages import Unreadable
from .scanner import last_report

log = logging.getLogger(__name__)

KINDS = ("damaged", "protected", "unreachable_folder", "unreadable_folder", "calibre_missing",
         "no_cover", "no_author", "no_tags", "filename_title", "duplicate", "series_gap")
MAX_MISSING = 50
ARTICLE = re.compile(r"^(the|a|an)\s+")


def check_files(cfg: Config) -> None:
    """Try each new or changed book file, and remember whether it opens."""
    with session(cfg.db_path) as con:
        todo = con.execute(
            "SELECT f.id, f.format, f.mtime FROM book_files f LEFT JOIN file_checks c ON c.file_id = f.id "
            "WHERE c.file_id IS NULL OR c.mtime != f.mtime").fetchall()
    for f in todo:
        if f["format"] not in pages.READABLE and f["format"] not in READABLE_FLOW:
            continue
        try:
            if f["format"] in pages.READABLE:
                pages.manifest(cfg, f["id"])
            else:
                flowbooks.open_flow(cfg, f["id"])
            status = "ok"
        except Unreadable as e:
            status = e.kind if e.kind in ("damaged", "protected") else "ok"
        except LookupError:
            continue  # gone since the scan
        except Exception:
            log.info("Couldn't open book file %s", f["id"], exc_info=True)
            status = "damaged"
        with session(cfg.db_path) as con:
            con.execute("INSERT INTO file_checks(file_id, mtime, status) VALUES (?, ?, ?) ON CONFLICT(file_id) "
                        "DO UPDATE SET mtime = excluded.mtime, status = excluded.status", (f["id"], f["mtime"], status))
    _work_out_title_sources(cfg)


def _work_out_title_sources(cfg: Config) -> None:
    """Books scanned before Loft noted where titles came from: read their files once to find out."""
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET title_from_name = 0 WHERE title_from_name IS NULL AND calibre_id IS NOT NULL")
        todo = con.execute(
            "SELECT b.id, (SELECT f.path || char(0) || f.format FROM book_files f WHERE f.book_id = b.id "
            "ORDER BY f.id LIMIT 1) AS file FROM books b WHERE b.title_from_name IS NULL").fetchall()
    for row in todo:
        if not row["file"]:
            continue
        path, fmt = row["file"].split("\0", 1)
        from_name = read_file_meta(Path(path), fmt).title_from_name
        with session(cfg.db_path) as con:
            con.execute("UPDATE books SET title_from_name = ? WHERE id = ?", (int(from_name), row["id"]))


def _ignored(con) -> set[tuple[str, str]]:
    return {(r["kind"], r["key"]) for r in con.execute("SELECT kind, key FROM check_ignored")}


def _norm(text: str) -> str:
    t = ARTICLE.sub("", " ".join((text or "").casefold().split()))
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def problems(cfg: Config) -> dict:
    from .library import book_card

    items: list[dict] = []
    report = last_report(cfg)
    with session(cfg.db_path) as con:
        ignored = _ignored(con)
        cards = {r["id"]: (book_card(r), r) for r in con.execute("SELECT * FROM books")}

        for r in con.execute("SELECT c.file_id, c.status, f.book_id, f.format FROM file_checks c "
                             "JOIN book_files f ON f.id = c.file_id WHERE c.status != 'ok' ORDER BY f.path"):
            if r["book_id"] in cards:
                items.append({"kind": r["status"], "key": str(r["file_id"]), "book": cards[r["book_id"]][0],
                              "file_id": r["file_id"], "format": r["format"]})

        if report:
            for kind, field in (("unreachable_folder", "unreachable"), ("unreadable_folder", "unreadable"),
                                ("calibre_missing", "calibre_missing")):
                items += [{"kind": kind, "key": path, "path": path} for path in report.get(field, [])]

        ordered = sorted(cards.values(), key=lambda c: (c[1]["sort_title"].casefold(), c[1]["id"]))
        for kind, test in (
                ("no_cover", lambda r: not r["has_cover"]),
                ("no_author", lambda r: not json.loads(r["authors"] or "[]")),
                ("no_tags", lambda r: not json.loads(r["tags"] or "[]")),  # they can only stand in Other
                ("filename_title", lambda r: r["title_from_name"] == 1 and "title" not in json.loads(r["locked"] or "[]"))):
            items += [{"kind": kind, "key": str(card["id"]), "book": card} for card, r in ordered if test(r)]

        groups: dict[tuple, list[dict]] = {}
        for card, r in ordered:
            authors = tuple(sorted(a.casefold().strip() for a in json.loads(r["authors"] or "[]")))
            groups.setdefault((_norm(r["title"]), authors, r["series"].casefold(), r["series_index"]), []).append(card)
        for books in groups.values():
            if len(books) > 1:
                ids = sorted(b["id"] for b in books)
                items.append({"kind": "duplicate", "key": ",".join(map(str, ids)),
                              "books": sorted(books, key=lambda b: b["id"])})

        series: dict[str, list] = {}
        for card, r in ordered:
            if r["series"]:
                series.setdefault(r["series"], []).append((r["series_index"], card))
        for name in sorted(series, key=str.casefold):
            entries = series[name]
            whole = {int(i) for i, _ in entries if i is not None and float(i).is_integer() and i >= 1}
            if len(entries) < 2 or not whole:
                continue
            missing = [n for n in range(1, max(whole) + 1) if n not in whole]
            if missing:
                items.append({"kind": "series_gap", "key": name, "series": name, "missing": missing[:MAX_MISSING],
                              "books": [c for _, c in sorted(entries, key=lambda e: (e[0] is None, e[0] or 0))]})

    shown = [i for i in items if (i["kind"], i["key"]) not in ignored]
    shown.sort(key=lambda i: KINDS.index(i["kind"]))
    return {"items": shown, "ignored": len(items) - len(shown), "last_scan": report}


def _check_kind(kind: str, key: str) -> None:
    if kind not in KINDS or not isinstance(key, str) or not key or len(key) > 4096:
        raise ValueError("That isn’t something the library check lists")


def ignore(cfg: Config, kind: str, key: str) -> None:
    _check_kind(kind, key)
    with session(cfg.db_path) as con:
        con.execute("INSERT OR IGNORE INTO check_ignored(kind, key) VALUES (?, ?)", (kind, key))


def unignore(cfg: Config, kind: str, key: str) -> None:
    _check_kind(kind, key)
    with session(cfg.db_path) as con:
        con.execute("DELETE FROM check_ignored WHERE kind = ? AND key = ?", (kind, key))


def list_ignored(cfg: Config) -> list[dict]:
    """What's been ignored, each with a label people can read (a book's title rather than its number)."""
    with session(cfg.db_path) as con:
        def title(book_id) -> str:
            row = con.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
            return row["title"] if row else ""

        def label(kind: str, key: str) -> str:
            if kind in ("no_cover", "no_author", "no_tags", "filename_title") and key.isdigit():
                return title(int(key))
            if kind in ("damaged", "protected") and key.isdigit():
                row = con.execute("SELECT book_id FROM book_files WHERE id = ?", (int(key),)).fetchone()
                return title(row["book_id"]) if row else ""
            if kind == "duplicate":
                return " and ".join(t for t in (title(int(k)) for k in key.split(",") if k.isdigit()) if t)
            return key

        return [{"kind": r["kind"], "key": r["key"], "label": label(r["kind"], r["key"]) or r["key"]}
                for r in con.execute("SELECT kind, key FROM check_ignored ORDER BY kind, key")]
