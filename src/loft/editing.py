"""The admin changing a book's details and cover, right on its page.

Changes are stored in Loft's database only (the book's files are never rewritten), and each
field the admin sets is locked: later scans, of a changed file or a changed Calibre library, leave it
as the admin left it.
"""

from __future__ import annotations

import datetime
import html
import io
import json
import math
import re
import time

from PIL import Image

from .config import Config
from .covers import remove_cover, store_cover
from .db import session
from .scanner import index_book, locked_fields, sort_title

FIELDS = ("title", "authors", "series", "series_index", "description", "publisher", "published", "language", "tags")
LIMITS = {"title": 500, "series": 300, "description": 20000, "publisher": 300, "language": 20}
MAX_AUTHORS, MAX_AUTHOR = 20, 200
MAX_TAGS, MAX_TAG = 50, 60
MAX_COVER_BYTES = 20 * 1024 * 1024
MAX_COVER_PIXELS = 50_000_000
PUBLISHED = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _line(value: str) -> str:
    return " ".join(value.split())


def _paragraphs(value: str) -> str:
    paras = re.split(r"\n\s*\n", value.replace("\r\n", "\n").replace("\r", "\n"))
    tidy = ["\n".join(_line(line) for line in p.split("\n") if line.strip()) for p in paras]
    return "\n\n".join(p for p in tidy if p)


def text_from_html(value: str) -> str:
    """Plain paragraphs from a description in simple HTML (<p>, <br>, <b>…), as online sources send them."""
    text = re.sub(r"<br\s*/?>\n?", "\n", value or "", flags=re.I)
    text = re.sub(r"<p\b[^>]*>|</p\s*>", "\n\n", text, flags=re.I)
    return _paragraphs(html.unescape(re.sub(r"<[^>]+>", "", text)))


def _names(key: str, value, most: int, longest: int) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{key} must be a list of names")
    names: list[str] = []
    for v in value:
        v = _line(v)
        if not v:
            raise ValueError(f"{key} can’t have an empty name")
        if len(v) > longest:
            raise ValueError(f"{key}: each can be at most {longest} characters")
        if v.casefold() not in (n.casefold() for n in names):
            names.append(v)
    if len(names) > most:
        raise ValueError(f"{key}: at most {most}")
    return names


def _published(value) -> str:
    if not isinstance(value, str):
        raise ValueError("published must be a date like 2014, 2014-07 or 2014-07-29")
    value = value.strip()
    if not value:
        return ""
    if not PUBLISHED.match(value):
        raise ValueError("published must be a date like 2014, 2014-07 or 2014-07-29")
    parts = [int(p) for p in value.split("-")] + [1, 1]
    try:
        datetime.date(parts[0], parts[1], parts[2])
    except ValueError:
        raise ValueError(f"published: {value} isn’t a real date") from None
    return value


def clean_details(patch: dict, *, require: bool = False) -> dict:
    """Check and tidy book details. Raises ValueError naming the field that's wrong."""
    if not isinstance(patch, dict):
        raise ValueError("Details must be an object")
    clean: dict = {}
    for key, value in patch.items():
        if key not in FIELDS:
            raise ValueError(f"Unknown detail {key}")
        if key == "authors":
            clean[key] = _names(key, value, MAX_AUTHORS, MAX_AUTHOR)
        elif key == "tags":
            clean[key] = _names(key, value, MAX_TAGS, MAX_TAG)
        elif key == "series_index":
            if value is None:
                clean[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
                    or not 0 <= value <= 100000:
                raise ValueError("series_index must be a number from 0 to 100000")
            clean[key] = float(value)
        elif key == "published":
            clean[key] = _published(value)
        else:
            if not isinstance(value, str):
                raise ValueError(f"{key} must be text")
            value = _paragraphs(value) if key == "description" else _line(value)
            if len(value) > LIMITS[key]:
                raise ValueError(f"{key} can be at most {LIMITS[key]} characters")
            if key == "title" and not value:
                raise ValueError("title can’t be empty")
            clean[key] = value
    if require and (not clean.get("title") or not clean.get("authors")):
        raise ValueError("Fill in the title and at least one author")
    return clean


def _lock(con, book_id: int, fields) -> str:
    return json.dumps(sorted(locked_fields(con, book_id) | set(fields)))


def edit_book(cfg: Config, book_id: int, patch: dict) -> None:
    clean = clean_details(patch)
    if clean.get("series") == "":
        clean["series_index"] = None
    columns: dict = {}
    for key, value in clean.items():
        if key == "title":
            columns.update(title=value, sort_title=sort_title(value))
        elif key == "authors":
            columns.update(authors=json.dumps(value), author_sort=value[0] if value else "")
        elif key == "tags":
            columns["tags"] = json.dumps(value)
        else:
            columns[key] = value
    with session(cfg.db_path) as con:
        if not con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
            raise LookupError(book_id)
        columns.update(updated_at=time.time(), locked=_lock(con, book_id, clean))
        sets = ", ".join(f"{k} = ?" for k in columns)
        con.execute(f"UPDATE books SET {sets} WHERE id = ?", (*columns.values(), book_id))
        index_book(con, book_id)


def _exists(con, book_id: int) -> None:
    if not con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
        raise LookupError(book_id)


def check_image(image: bytes) -> None:
    bad = ValueError("That isn’t a picture Loft can use (JPEG, PNG, WebP or GIF, up to 20 MB)")
    if not image or len(image) > MAX_COVER_BYTES:
        raise bad
    try:
        with Image.open(io.BytesIO(image)) as img:
            if img.width * img.height > MAX_COVER_PIXELS:
                raise bad
            img.verify()
    except ValueError:
        raise
    except Exception:
        raise bad from None


def set_cover(cfg: Config, book_id: int, image: bytes) -> None:
    check_image(image)
    with session(cfg.db_path) as con:
        _exists(con, book_id)
    try:
        colour = store_cover(cfg, book_id, image)
    except Exception:
        raise ValueError("That isn’t a picture Loft can use (JPEG, PNG, WebP or GIF, up to 20 MB)") from None
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET has_cover = 1, cover_color = ?, updated_at = ?, locked = ? WHERE id = ?",
                    (colour, time.time(), _lock(con, book_id, ["cover"]), book_id))


def clear_cover(cfg: Config, book_id: int) -> None:
    """No cover: the book shows the one Loft draws from its title."""
    with session(cfg.db_path) as con:
        _exists(con, book_id)
        remove_cover(cfg, book_id)
        con.execute("UPDATE books SET has_cover = 0, cover_color = NULL, updated_at = ?, locked = ? WHERE id = ?",
                    (time.time(), _lock(con, book_id, ["cover"]), book_id))
