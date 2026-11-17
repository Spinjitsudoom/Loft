"""Manga details and covers from AniList (anilist.co), for the admin to choose from.

AniList knows manga, manhwa and light novels that Open Library often doesn't. It needs no key.
Only the title is sent, and nothing at all while online lookups are off in Library settings.
Adult-only entries are left out. Covers come from s4.anilist.co (see openlibrary.fetch_cover).
"""

from __future__ import annotations

import json
import re
import urllib.request

from .config import Config
from .openlibrary import MAX_JSON, MAX_TAGS, RESULTS, TIMEOUT, USER_AGENT, LookupFailed, _allowed

API = "https://graphql.anilist.co"
FAILED = "AniList didn’t answer; try again in a moment, or fill the details in by hand"
QUERY = """query ($search: String) {
  Page(perPage: %d) {
    media(search: $search, type: MANGA, isAdult: false) {
      title { romaji english }
      startDate { year }
      description(asHtml: false)
      genres
      coverImage { extraLarge large }
      staff(perPage: 8, sort: RELEVANCE) { edges { role node { name { full } } } }
    }
  }
}""" % RESULTS
# The people who made it, not its translators, letterers or assistants.
CREATOR = re.compile(r"^(Story|Art|Original)\b")
NOTE = re.compile(r"^(\(Source:[^)]*\)|<i>.*</i>)$", re.S)  # AniList's own notes under a description


def _post(url: str, body: bytes, limit: int) -> bytes:
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response too big")
    return data


def _str(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _description(value) -> str:
    from .editing import text_from_html
    text = re.sub(r"<br\s*/?>\n?", "\n", _str(value), flags=re.I)
    kept = [p for p in re.split(r"\n\s*\n", text) if p.strip() and not NOTE.match(p.strip())]
    return text_from_html("\n\n".join(kept))


def _creators(media: dict) -> list[str]:
    names: list[str] = []
    edges = (media.get("staff") or {}).get("edges")
    for edge in edges if isinstance(edges, list) else []:
        if not isinstance(edge, dict) or not CREATOR.match(_str(edge.get("role"))):
            continue
        name = _str((((edge.get("node") or {}).get("name")) or {}).get("full"))
        if name and name not in names:
            names.append(name)
    return names


def _cover(url) -> str | None:
    url = _str(url)
    return url if url.startswith("https://s4.anilist.co/file/anilistcdn/") else None


def _candidate(media: dict) -> dict:
    titles = media.get("title") or {}
    year = (media.get("startDate") or {}).get("year")
    covers = media.get("coverImage") or {}
    genres = media.get("genres")
    return {
        "key": "",  # the description comes with the match; there's nothing more to fetch
        "source": "AniList",
        "title": _str(titles.get("english")) or _str(titles.get("romaji")),
        "authors": _creators(media),
        "published": str(year) if isinstance(year, int) and not isinstance(year, bool) else "",
        "publisher": "",
        "language": "",  # AniList gives the original's language, not this edition's
        "isbn": "",
        "tags": [g.strip() for g in genres if isinstance(g, str) and g.strip()][:MAX_TAGS] if isinstance(genres, list) else [],
        "description": _description(media.get("description")),
        "cover_url": _cover(covers.get("extraLarge")),
        "thumb_url": _cover(covers.get("large")),
    }


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", text.casefold()) if len(w) >= 3]


def _by(author: str, candidate: dict) -> bool:
    """Loosely the same person: AniList spells names its own way (Junji Ito is "Junji Itou")."""
    wanted = _words(author)
    have = _words(" ".join(candidate["authors"]))
    return bool(wanted) and any(h.startswith(w) or w.startswith(h) for w in wanted for h in have)


def search(cfg: Config, *, title: str, author: str = "") -> list[dict]:
    """Up to six manga that might be this one, those by the given author first."""
    title = " ".join((title or "").split())
    if not title:
        raise ValueError("Give a title to look for")
    _allowed(cfg)
    body = json.dumps({"query": QUERY, "variables": {"search": title}}).encode()
    try:
        value = json.loads(_post(API, body, MAX_JSON))
        media = value["data"]["Page"]["media"]
    except Exception as e:
        raise LookupFailed(FAILED) from e
    if not isinstance(media, list):
        raise LookupFailed(FAILED)
    found = [_candidate(m) for m in media[:RESULTS] if isinstance(m, dict)]
    found = [c for c in found if c["title"]]
    return sorted(found, key=lambda c: not _by(author, c))
