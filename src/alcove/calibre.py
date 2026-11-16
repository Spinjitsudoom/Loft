"""Calibre's library: a one-way import of its details (titles, authors, series, tags, covers).

Calibre's metadata.db is opened read-only and "immutable", so Alcove never writes to it or leaves
lock files next to it (it usually sits on a network share).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr"}
DROP_TAGS = {"script", "style"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_TAGS:
            self.skip += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in DROP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(value: str) -> str:
    """Calibre and EPUB descriptions are HTML; Alcove keeps and shows them as plain paragraphs."""
    if not value:
        return ""
    p = _TextParser()
    p.feed(value)
    p.close()
    text = "".join(p.parts)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass
class CalibreBook:
    calibre_id: int
    title: str
    sort_title: str
    authors: list[str]
    author_sort: str
    series: str = ""
    series_index: float | None = None
    description: str = ""
    publisher: str = ""
    published: str = ""
    language: str = ""
    tags: list[str] = field(default_factory=list)
    cover: Path | None = None
    files: list[Path] = field(default_factory=list)
    added: float | None = None  # when it was added to Calibre (Unix time)


def _many(con, sql: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for book, value in con.execute(sql):
        out.setdefault(book, []).append(value)
    return out


def read_calibre(root: Path) -> dict[Path, CalibreBook]:
    """Every book file Calibre knows about under root, mapped to its details. {} without a usable metadata.db."""
    db = root / "metadata.db"
    if not db.is_file():
        return {}
    try:
        con = sqlite3.connect(f"file:{quote(str(db))}?mode=ro&immutable=1", uri=True)
        try:
            return _read(con, root)
        finally:
            con.close()
    except sqlite3.Error as e:
        log.warning("Couldn't read Calibre's library at %s: %s", db, e)
        return {}


def _read(con: sqlite3.Connection, root: Path) -> dict[Path, CalibreBook]:
    authors = _many(con, "SELECT l.book, a.name FROM books_authors_link l JOIN authors a ON a.id = l.author ORDER BY l.id")
    tags = _many(con, "SELECT l.book, t.name FROM books_tags_link l JOIN tags t ON t.id = l.tag ORDER BY l.id")
    series = {b: v[0] for b, v in _many(con, "SELECT l.book, s.name FROM books_series_link l "
                                              "JOIN series s ON s.id = l.series").items()}
    publishers = {b: v[0] for b, v in _many(con, "SELECT l.book, p.name FROM books_publishers_link l "
                                                 "JOIN publishers p ON p.id = l.publisher").items()}
    languages = {b: v[0] for b, v in _many(con, "SELECT l.book, g.lang_code FROM books_languages_link l "
                                                "JOIN languages g ON g.id = l.lang_code ORDER BY l.id").items()}
    comments = {b: v[0] for b, v in _many(con, "SELECT book, text FROM comments").items()}
    data = _many(con, "SELECT book, format || char(0) || name FROM data")

    result: dict[Path, CalibreBook] = {}
    for bid, title, sort, author_sort, path, has_cover, series_index, pubdate, added in con.execute(
            "SELECT id, title, sort, author_sort, path, has_cover, series_index, pubdate, timestamp FROM books"):
        folder = root / path
        files = []
        for entry in data.get(bid, []):
            fmt, name = entry.split("\0", 1)
            files.append(folder / f"{name}.{fmt.lower()}")
        cover = folder / "cover.jpg"
        in_series = series.get(bid, "")
        book = CalibreBook(
            calibre_id=bid,
            title=title or "",
            sort_title=sort or title or "",
            authors=authors.get(bid, []),
            author_sort=author_sort or "",
            series=in_series,
            series_index=float(series_index) if in_series and series_index is not None else None,
            description=html_to_text(comments.get(bid, "")),
            publisher=publishers.get(bid, ""),
            published=_date(pubdate),
            language=languages.get(bid, ""),
            tags=tags.get(bid, []),
            cover=cover if has_cover and cover.is_file() else None,
            files=files,
            added=_timestamp(added),
        )
        for f in files:
            result[f] = book
    return result


def _timestamp(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def _date(value) -> str:
    """Calibre keeps "0101-01-01" for "no date"."""
    text = str(value or "")[:10]
    return "" if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) or text.startswith("0101") else text
