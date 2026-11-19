"""Book details from ISBNdb (isbndb.com), for the admin to choose from and for new books.

ISBNdb is strongest for books with an ISBN: publisher, date, language and a synopsis for the
edition itself. It needs an API key from one of ISBNdb's plans (they start with a trial), saved in
Library settings; without one it isn't asked. Each plan answers at its own address, so the one
the key works at is found when it's saved. The title (or the ISBN) is sent with the key; covers
come from images.isbndb.com.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from .config import Config
from .libsettings import isbndb_key
from .openlibrary import MAX_JSON, MAX_TAGS, RESULTS, TIMEOUT, USER_AGENT, LookupFailed, _allowed, normal_isbn

# Basic, Premium and Pro plans, in that order.
HOSTS = ("https://api2.isbndb.com", "https://api.premium.isbndb.com", "https://api.pro.isbndb.com")
COVER_HOST = "images.isbndb.com"
TEST_ISBN = "9780140328721"
FAILED = "ISBNdb didn’t answer; try again in a moment, or fill the details in by hand"
REFUSED = "ISBNdb refused the key saved in Library settings (has the trial ended?); check it there"
LIMIT = "ISBNdb is busy or this key’s limit is used up; try again later"


class KeyRefused(LookupFailed):
    pass


class NotFound(LookupFailed):
    pass


def key(cfg: Config) -> tuple[str, str]:
    """(the key, the address it works at), or ("", "")."""
    return isbndb_key(cfg)


def _get(url: str, api_key: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"Authorization": api_key, "Accept": "application/json",
                                                   "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response too big")
    return data


def _ask(url: str, api_key: str) -> dict:
    try:
        value = json.loads(_get(url, api_key, MAX_JSON))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound("") from None
        if e.code in (401, 403):
            raise KeyRefused(REFUSED) from None  # `from None`: the error would carry the key
        raise LookupFailed(LIMIT if e.code == 429 else FAILED) from None
    except Exception:
        raise LookupFailed(FAILED) from None
    if not isinstance(value, dict):
        raise LookupFailed(FAILED)
    return value


def _str(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strs(value) -> list[str]:
    return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _tags(subjects: list[str]) -> list[str]:
    """"Fiction / Horror" is two tags; "General" says nothing."""
    tags: list[str] = []
    for subject in subjects:
        for part in subject.replace("&amp;", "&").split("/"):
            part = part.strip()
            if part and part.casefold() != "general" and len(part) <= 60 and part not in tags:
                tags.append(part)
    return tags[:MAX_TAGS]


def _candidate(book: dict) -> dict:
    from .editing import text_from_html
    from .googlebooks import _published
    image = _str(book.get("image")) or _str(book.get("image_original"))
    cover = image if image.startswith(f"https://{COVER_HOST}/") else None
    isbn = normal_isbn(_str(book.get("isbn13")) or _str(book.get("isbn")))
    return {
        "key": "",  # the description comes with the match
        "source": "ISBNdb",
        "title": _str(book.get("title")) or _str(book.get("title_long")),
        "authors": _strs(book.get("authors")),
        "published": _published(book.get("date_published")),
        "publisher": _str(book.get("publisher")),
        "language": _str(book.get("language"))[:20],
        "isbn": isbn,
        "tags": _tags(_strs(book.get("subjects"))),
        "description": text_from_html(_str(book.get("synopsis")) or _str(book.get("overview"))),
        "cover_url": cover,
        "thumb_url": cover,
    }


def _same(a: str, b: str) -> bool:
    from .autofill import same_person
    return same_person(a, b)


def search(cfg: Config, *, title: str = "", author: str = "", isbn: str = "") -> list[dict]:
    """Up to six editions that might be this book: by ISBN if there is one, else by title (with those
    by the author given first)."""
    isbn = normal_isbn(isbn)
    title, author = (" ".join((v or "").split()) for v in (title, author))
    if len(isbn) not in (10, 13) and not title:
        raise ValueError("Give a title or an ISBN to look for")
    _allowed(cfg)
    api_key, host = key(cfg)
    if not api_key:
        raise LookupFailed("ISBNdb needs a key; add one in Library settings")
    try:
        if len(isbn) in (10, 13):
            book = _ask(f"{host}/book/{isbn}", api_key).get("book")
            books = [book] if isinstance(book, dict) else []
        else:
            query = urlencode({"page": 1, "pageSize": 20, "column": "title"})
            books = _ask(f"{host}/books/{quote(title, safe='')}?{query}", api_key).get("books")
            books = [b for b in books if isinstance(b, dict)] if isinstance(books, list) else []
    except NotFound:
        return []
    found = [c for c in (_candidate(b) for b in books) if c["title"]]
    if author:
        found.sort(key=lambda c: not any(_same(author, a) for a in c["authors"]))
    return found[:RESULTS]


def check_key(api_key: str) -> str:
    """Try a key before it's saved, at each plan's address. Returns the address it works at; raises
    ValueError, for the admin, if none takes it."""
    unreachable = False
    for host in HOSTS:
        try:
            _ask(f"{host}/book/{TEST_ISBN}", api_key)
            return host
        except NotFound:
            return host  # the key worked; the book just isn't there
        except KeyRefused:
            continue
        except LookupFailed as e:
            if str(e) == LIMIT:
                return host
            unreachable = True
    if unreachable:
        raise ValueError("Loft couldn’t reach ISBNdb to check that key; try again in a moment")
    raise ValueError("ISBNdb refused that key. Check it was copied whole, and that the plan or trial is active.")
