"""Book details and covers from Google Books, for the admin to choose from.

Google Books knows the editions themselves (an English manga volume with its own cover, ISBN and
release date), which Open Library and AniList often don't. It needs an API key, which the admin
saves in Library settings; without one it isn't asked. The title, author and ISBN are sent, with the
key, and nothing at all while online lookups are off. Covers come from books.google.com.
"""

from __future__ import annotations

import json
import re
import urllib.error
from urllib.parse import urlencode

from . import openlibrary
from .config import Config
from .libsettings import google_books_key
from .openlibrary import MAX_JSON, MAX_TAGS, RESULTS, LookupFailed, _allowed, normal_isbn

API = "https://www.googleapis.com/books/v1/volumes"
COVER = "https://books.google.com/books/content?id={id}&printsec=frontcover&img=1&{size}"
FIELDS = ("items(id,volumeInfo(title,authors,publisher,publishedDate,description,industryIdentifiers,"
          "categories,language,imageLinks))")
VOLUME_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
KEY_SHAPE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
FAILED = "Google Books didn’t answer; try again in a moment, or fill the details in by hand"
REFUSED = "Google Books refused the key saved in Library settings; check it there"
LIMIT = "Google Books’ daily limit for this key is used up; try again tomorrow"


class KeyRefused(LookupFailed):
    pass


def key(cfg: Config) -> str:
    return google_books_key(cfg)


def _ask(q: str, api_key: str, most: int) -> dict:
    url = f"{API}?{urlencode({'q': q, 'maxResults': most, 'printType': 'books', 'fields': FIELDS, 'key': api_key})}"
    try:
        value = json.loads(openlibrary._get(url, MAX_JSON))
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            raise KeyRefused(REFUSED) from None  # `from None`: the error would carry the URL, key and all
        raise LookupFailed(LIMIT if e.code == 429 else FAILED) from None
    except Exception:
        raise LookupFailed(FAILED) from None
    if not isinstance(value, dict):
        raise LookupFailed(FAILED)
    return value


def _str(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _published(value) -> str:
    from .editing import PUBLISHED
    day = _str(value)[:10]  # "2003-05-01T00:00:00Z" happens
    return day if PUBLISHED.match(day) else (day[:4] if re.match(r"^\d{4}", day) else "")


def _tags(categories) -> list[str]:
    """"Comics & Graphic Novels / Manga / Horror" is three tags."""
    tags: list[str] = []
    for category in categories if isinstance(categories, list) else []:
        for part in _str(category).split("/"):
            part = part.strip()
            if part and part.casefold() != "general" and part not in tags:
                tags.append(part)
    return tags[:MAX_TAGS]


def _candidate(item: dict) -> dict:
    from .editing import text_from_html
    info = item.get("volumeInfo") or {}
    vid = item["id"] if isinstance(item.get("id"), str) and VOLUME_ID.match(item["id"]) else ""
    has_cover = bool(vid and isinstance(info.get("imageLinks"), dict) and info["imageLinks"])
    ids = {i.get("type"): _str(i.get("identifier")) for i in info.get("industryIdentifiers") or [] if isinstance(i, dict)}
    authors = info.get("authors")
    return {
        "key": "",  # the description comes with the match
        "source": "Google Books",
        "title": _str(info.get("title")),
        "authors": [a.strip() for a in authors if isinstance(a, str) and a.strip()] if isinstance(authors, list) else [],
        "published": _published(info.get("publishedDate")),
        "publisher": _str(info.get("publisher")),
        "language": _str(info.get("language")),
        "isbn": normal_isbn(ids.get("ISBN_13") or ids.get("ISBN_10") or ""),
        "tags": _tags(info.get("categories")),
        "description": text_from_html(_str(info.get("description"))),
        "cover_url": COVER.format(id=vid, size="fife=w1200-h1800") if has_cover else None,
        "thumb_url": COVER.format(id=vid, size="zoom=1") if has_cover else None,
    }


def search(cfg: Config, *, title: str = "", author: str = "", isbn: str = "") -> list[dict]:
    """Up to six editions that might be this book: by ISBN if there is one, else by title and author."""
    isbn = normal_isbn(isbn)
    title, author = (" ".join((v or "").replace('"', " ").split()) for v in (title, author))
    if len(isbn) in (10, 13):
        q = f"isbn:{isbn}"
    elif title:
        q = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else "")
    else:
        raise ValueError("Give a title or an ISBN to look for")
    _allowed(cfg)
    api_key = key(cfg)
    if not api_key:
        raise LookupFailed("Google Books needs a key; add one in Library settings")
    items = _ask(q, api_key, RESULTS).get("items", [])  # no "items" means no matches
    if not isinstance(items, list):
        raise LookupFailed(FAILED)
    found = [_candidate(i) for i in items[:RESULTS] if isinstance(i, dict)]
    return [c for c in found if c["title"]]


def check_key(api_key: str) -> None:
    """Try a key once before it's saved. Raises ValueError, for the admin, if Google won't take it."""
    try:
        _ask("isbn:9780140449136", api_key, 1)
    except KeyRefused:
        raise ValueError("Google Books refused that key. Check it was copied whole, "
                         "and that the Books API is turned on for it.") from None
    except LookupFailed as e:
        if str(e) == LIMIT:
            return  # a real key, just busy today
        raise ValueError("Alcove couldn’t reach Google Books to check that key; try again in a moment") from None
