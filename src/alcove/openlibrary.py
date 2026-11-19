"""Book details and covers from Open Library (openlibrary.org), for the admin to choose from.

Only the title, author and ISBN are sent, and nothing at all while online lookups are off in
Library settings. Covers are only ever downloaded from covers.openlibrary.org, or from AniList's
Google Books', Hardcover's or ISBNdb's image servers for matches found there (see anilist.py,
googlebooks.py, hardcover.py, isbndb.py).
"""

from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import urlencode, urlparse

from .config import Config
from .libsettings import get_library

SEARCH = "https://openlibrary.org/search.json"
WORKS = "https://openlibrary.org"
COVER_HOST = "covers.openlibrary.org"
# host: where its covers live
COVER_HOSTS = {COVER_HOST: "/b/", "s4.anilist.co": "/file/anilistcdn/", "books.google.com": "/books/content",
               "assets.hardcover.app": "/", "images.isbndb.com": "/"}
FIELDS = "key,title,author_name,first_publish_year,publisher,language,subject,isbn,cover_i"
RESULTS = 6
MAX_TAGS = 8
MAX_JSON = 2 * 1024 * 1024
MAX_COVER = 10 * 1024 * 1024
TIMEOUT = 10
USER_AGENT = "Alcove/0.1 (self-hosted ebook library)"
WORK_KEY = re.compile(r"^/works/OL\d+W$")


class LookupFailed(Exception):
    """Open Library couldn't be asked; the message is for people."""


class LookupsOff(LookupFailed):
    def __init__(self) -> None:
        super().__init__("Online lookups are turned off in Library settings")


FAILED = "Open Library didn’t answer; try again in a moment, or fill the details in by hand"


def _get(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response too big")
    return data


def _allowed(cfg: Config) -> None:
    if not get_library(cfg)["online_lookups"]:
        raise LookupsOff()


def _json(url: str):
    try:
        value = json.loads(_get(url, MAX_JSON))
    except Exception as e:
        raise LookupFailed(FAILED) from e
    if not isinstance(value, dict):
        raise LookupFailed(FAILED)
    return value


def normal_isbn(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value or "").upper()


def _text_list(value) -> list[str]:
    return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _candidate(doc: dict) -> dict:
    cover = doc.get("cover_i")
    year = doc.get("first_publish_year")
    publishers, languages, isbns = (_text_list(doc.get(k)) for k in ("publisher", "language", "isbn"))
    key = doc.get("key") if isinstance(doc.get("key"), str) and WORK_KEY.match(doc.get("key")) else ""
    return {
        "key": key,
        "title": doc.get("title").strip() if isinstance(doc.get("title"), str) else "",
        "authors": _text_list(doc.get("author_name")),
        "published": str(year) if isinstance(year, int) and not isinstance(year, bool) else "",
        # A work lists every edition's publishers and languages; only one of each says something.
        "publisher": publishers[0] if len(publishers) == 1 else "",
        "language": languages[0] if len(languages) == 1 else "",
        "tags": _text_list(doc.get("subject"))[:MAX_TAGS],
        "isbn": next((i for i in isbns if len(normal_isbn(i)) == 13), isbns[0] if isbns else ""),
        "cover_url": (f"https://{COVER_HOST}/b/id/{cover}-L.jpg?default=false"
                      if isinstance(cover, int) and not isinstance(cover, bool) and cover > 0 else None),
    }


def search(cfg: Config, *, title: str = "", author: str = "", isbn: str = "") -> list[dict]:
    """Up to six books that might be this one: by ISBN if there is one, else by title and author."""
    isbn = normal_isbn(isbn)
    title, author = " ".join((title or "").split()), " ".join((author or "").split())
    if len(isbn) in (10, 13):
        query = {"isbn": isbn}
    elif title:
        query = {"title": title, **({"author": author} if author else {})}
    else:
        raise ValueError("Give a title or an ISBN to look for")
    _allowed(cfg)
    found = _json(f"{SEARCH}?{urlencode({**query, 'fields': FIELDS, 'limit': RESULTS})}")
    docs = found.get("docs")
    if not isinstance(docs, list):
        raise LookupFailed(FAILED)
    return [_candidate(d) for d in docs[:RESULTS] if isinstance(d, dict) and isinstance(d.get("title"), str)]


def description(cfg: Config, key: str) -> str:
    if not isinstance(key, str) or not WORK_KEY.match(key):
        raise ValueError("That isn’t an Open Library work")
    _allowed(cfg)
    value = _json(f"{WORKS}{key}.json").get("description")
    if isinstance(value, dict):
        value = value.get("value")
    if not isinstance(value, str):
        return ""
    from .editing import _paragraphs
    return _paragraphs(value)


def fetch_cover(cfg: Config, url: str) -> bytes:
    parsed = urlparse(url or "")
    folder = COVER_HOSTS.get(parsed.hostname or "")
    if (parsed.scheme != "https" or not folder or not parsed.path.startswith(folder)
            or parsed.port not in (None, 443) or parsed.username):
        raise ValueError("Covers can only come from Open Library, Google Books, Hardcover, ISBNdb or AniList")
    _allowed(cfg)
    try:
        return _get(url, MAX_COVER)
    except Exception as e:
        raise LookupFailed("That cover didn’t download; try another") from e
