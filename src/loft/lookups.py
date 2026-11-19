"""Looking a book up online, in every source that might know it, at once.

- Hardcover, when the admin has saved a token: the series a book is in and its number, and
  descriptions for most modern books.
- Google Books, when the admin has saved a key: the editions themselves (English manga volumes too).
- ISBNdb, when the admin has saved a key: editions by ISBN, with publisher, date and synopsis.
- Open Library, always.
- AniList, for comics (books shown page by page). Any other book asks it only when nothing else
  found anything, so ordinary novels don't send their titles to a manga site.

Matches are listed in that order. A source that can't be asked is passed over while others found
something; when nothing was found, the message says which didn't answer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial

from . import anilist, googlebooks, hardcover, isbndb, openlibrary
from .config import Config
from .openlibrary import LookupFailed, LookupsOff, normal_isbn


# Language codes as Open Library gives them (ISO 639-2) said the way the others say them.
LANGUAGES = {"eng": "en", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de", "spa": "es", "ita": "it",
             "por": "pt", "jpn": "ja", "rus": "ru", "dut": "nl", "nld": "nl", "chi": "zh", "zho": "zh",
             "kor": "ko", "pol": "pl", "swe": "sv", "dan": "da", "nor": "no", "fin": "fi", "tur": "tr",
             "ara": "ar", "heb": "he", "gre": "el", "ell": "el", "cze": "cs", "ces": "cs", "hun": "hu"}


def _language(code: str) -> str:
    code = (code or "").strip().lower()
    return LANGUAGES.get(code, code)


def _ranked(found: list[dict], lang: str) -> list[dict]:
    """Within a source: editions in the reader's language first, then those with a description
    (Open Library's come separately, so they count as having one)."""
    want = _language(lang.split("-")[0]) if lang else ""
    for c in found:
        c["language"] = _language(c.get("language", ""))
    return sorted(found, key=lambda c: (bool(want) and c["language"] not in ("", want),
                                        c["source"] != "Open Library" and not c.get("description")))


def _open_library(cfg: Config, **query) -> list[dict]:
    return [{**c, "source": "Open Library"} for c in openlibrary.search(cfg, **query)]


def _attempt(call):
    """(matches, None), or ([], the failure) when the source couldn't be asked."""
    try:
        return call(), None
    except LookupsOff:
        raise
    except LookupFailed as e:
        return [], e


def _ask(sources: list[tuple[str, object]]) -> list[tuple[str, list[dict], LookupFailed | None]]:
    if len(sources) == 1:
        name, call = sources[0]
        return [(name, *_attempt(call))]
    with ThreadPoolExecutor(len(sources)) as pool:
        futures = [(name, pool.submit(_attempt, call)) for name, call in sources]
        return [(name, *f.result()) for name, f in futures]


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def search(cfg: Config, *, title: str = "", author: str = "", isbn: str = "", comic: bool = False,
           lang: str = "") -> list[dict]:
    has_title = bool((title or "").strip())
    if not has_title and len(normal_isbn(isbn)) not in (10, 13):
        raise ValueError("Give a title or an ISBN to look for")
    openlibrary._allowed(cfg)
    query = {"title": title, "author": author, "isbn": isbn}
    ask_anilist = ("AniList", partial(anilist.search, cfg, title=title, author=author))
    sources = []
    if hardcover.key(cfg):
        sources.append(("Hardcover", partial(hardcover.search, cfg, **query)))
    if googlebooks.key(cfg):
        sources.append(("Google Books", partial(googlebooks.search, cfg, **query)))
    if isbndb.key(cfg)[0]:
        sources.append(("ISBNdb", partial(isbndb.search, cfg, **query)))
    sources.append(("Open Library", partial(_open_library, cfg, **query)))
    if comic and has_title:
        sources.append(ask_anilist)
    results = _ask(sources)
    if has_title and not comic and not any(found for _, found, _ in results):
        results += _ask([ask_anilist])

    found = [c for _, matches, _ in results for c in _ranked(matches, lang)]
    if found:
        return found
    failed = [(name, e) for name, _, e in results if e]
    if len(failed) == 1:
        raise failed[0][1]
    if failed:
        raise LookupFailed(f"{_names([n for n, _ in failed])} didn’t answer; "
                           "try again in a moment, or fill the details in by hand")
    return []
