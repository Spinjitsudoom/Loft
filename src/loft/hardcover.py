"""Book details from Hardcover (hardcover.app), for the admin to choose from and for new books.

Hardcover knows the series a book is in and its number there, which none of the other sources say,
and it has descriptions for most modern books. It needs the admin's own API token (Hardcover,
Settings, Hardcover API), saved in Library settings; without one it isn't asked. The title and
author (or the ISBN) are sent with the token, from the server only, never the browser. Covers come
from assets.hardcover.app. Its API is in beta: tokens expire, and it may change.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import Config
from .libsettings import hardcover_token
from .openlibrary import MAX_JSON, MAX_TAGS, RESULTS, TIMEOUT, USER_AGENT, LookupFailed, _allowed, normal_isbn

API = "https://api.hardcover.app/v1/graphql"
COVER_HOST = "assets.hardcover.app"
QUERY = ('query Find($q: String!, $n: Int!) { search(query: $q, query_type: "Book", per_page: $n, page: 1) '
         '{ results } }')
FAILED = "Hardcover didn’t answer; try again in a moment, or fill the details in by hand"
REFUSED = "Hardcover refused the token saved in Library settings (they expire); make a new one there"
LIMIT = "Hardcover’s limit for this token is used up for now; try again later"


class KeyRefused(LookupFailed):
    pass


def key(cfg: Config) -> str:
    return hardcover_token(cfg)


def _post(url: str, body: bytes, token: str, limit: int) -> bytes:
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response too big")
    return data


def _ask(q: str, token: str, most: int) -> list[dict]:
    body = json.dumps({"query": QUERY, "variables": {"q": q, "n": most}}).encode()
    try:
        value = json.loads(_post(API, body, token, MAX_JSON))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise KeyRefused(REFUSED) from None  # `from None`: the error would carry the token
        raise LookupFailed(LIMIT if e.code == 429 else FAILED) from None
    except Exception:
        raise LookupFailed(FAILED) from None
    try:
        results = value["data"]["search"]["results"]
        if isinstance(results, str):
            results = json.loads(results)
        hits = results.get("hits") or []
    except (KeyError, TypeError, AttributeError, ValueError):
        raise LookupFailed(FAILED) from None
    return [h["document"] for h in hits if isinstance(h, dict) and isinstance(h.get("document"), dict)]


def _str(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strs(value) -> list[str]:
    return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _series(doc: dict) -> tuple[str, float | None]:
    """The book's main series and its number there, said a few ways in the search index."""
    featured = doc.get("featured_series")
    name, position = "", None
    if isinstance(featured, dict):
        inner = featured.get("series")
        name = _str(inner.get("name")) if isinstance(inner, dict) else _str(featured.get("name"))
        position = featured.get("position")
    if not name:
        names = _strs(doc.get("series_names"))
        name = names[0] if len(names) == 1 else ""
    if position is None:
        position = doc.get("featured_series_position")
    if isinstance(position, bool) or not isinstance(position, (int, float)) or not 0 <= position <= 100000:
        position = None
    return name, (float(position) if name and position is not None else None)


def _candidate(doc: dict) -> dict:
    from .editing import text_from_html
    image = doc.get("image")
    url = _str(image.get("url")) if isinstance(image, dict) else ""
    cover = url if url.startswith(f"https://{COVER_HOST}/") else None
    year = doc.get("release_year")
    isbns = [normal_isbn(i) for i in _strs(doc.get("isbns"))]
    series, index = _series(doc)
    return {
        "key": "",  # the description comes with the match
        "source": "Hardcover",
        "title": _str(doc.get("title")),
        "authors": _strs(doc.get("author_names")),
        "published": str(year) if isinstance(year, int) and not isinstance(year, bool) and 0 < year < 10000 else "",
        "publisher": "",
        "language": "",
        "isbn": next((i for i in isbns if len(i) == 13), next((i for i in isbns if len(i) == 10), "")),
        "tags": (_strs(doc.get("genres")) or _strs(doc.get("tags")))[:MAX_TAGS],
        "description": text_from_html(_str(doc.get("description"))),
        "series": series,
        "series_index": index,
        "cover_url": cover,
        "thumb_url": cover,
    }


def search(cfg: Config, *, title: str = "", author: str = "", isbn: str = "") -> list[dict]:
    """Up to six books that might be this one: by ISBN if there is one, else by title and author."""
    isbn = normal_isbn(isbn)
    title, author = (" ".join((v or "").split()) for v in (title, author))
    if len(isbn) in (10, 13):
        q = isbn
    elif title:
        q = f"{title} {author}".strip()
    else:
        raise ValueError("Give a title or an ISBN to look for")
    _allowed(cfg)
    token = key(cfg)
    if not token:
        raise LookupFailed("Hardcover needs a token; add one in Library settings")
    found = [_candidate(d) for d in _ask(q, token, RESULTS)[:RESULTS]]
    return [c for c in found if c["title"]]


def check_key(token: str) -> None:
    """Try a token once before it's saved. Raises ValueError, for the admin, if Hardcover won't take it."""
    try:
        _ask("dune", token, 1)
    except KeyRefused:
        raise ValueError("Hardcover refused that token. Check it was copied whole, that it hasn’t expired, "
                         "and that it may read books.") from None
    except LookupFailed as e:
        if str(e) == LIMIT:
            return  # a real token, just busy
        raise ValueError("Loft couldn’t reach Hardcover to check that token; try again in a moment") from None
