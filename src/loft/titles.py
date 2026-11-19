"""Titles as files leave them, read the way the web app reads them (web/js/titles.js does the same)."""

from __future__ import annotations

import re


def search_title(title: str) -> str:
    """"#04 Assassin's Creed - Revelations (90)" made fit to search for: "Assassin's Creed: Revelations"."""
    t = re.sub(r"_\s", ": ", str(title or ""))          # files can't hold ":", so "Avatar_ The…" was "Avatar: The…"
    t = re.sub(r"_+", " ", t)
    t = re.sub(r"^\s*#?\d+\s*[-.:)]?\s+(?=\D)", "", t)    # a leading "#04 " or "12 - "
    t = re.sub(r"\s*[(\[]\d+[)\]]\s*$", "", t)            # a trailing "(90)"
    t = re.sub(r"\s+[-–—]\s+", ": ", t)                   # "Series - Title" reads "Series: Title"
    return re.sub(r"\s{2,}", " ", t).strip()


NUMBERED = r"(?:#\s*|book\s+|vol\.?\s*|volume\s+|no\.?\s*)(\d+(?:\.\d+)?)"


def _has_letter(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def series_from_title(title: str) -> tuple[str, float] | None:
    """The series and number a title carries ("#04 Assassin's Creed - Revelation", "Uprising #8",
    "Geronimo Stilton, Vol. 2: Cat and Mouse"), or None. A number alone ("Fahrenheit 451") isn't one."""
    t = re.sub(r"\s+", " ", re.sub(r"_+", " ", re.sub(r"_\s", ": ", str(title or "")))).strip()
    m = re.match(rf"^.+?\s*\(([^()]+?),?\s+{NUMBERED}\)$", t, re.I)   # "Rumble in the Jungle (Geronimo Stilton #53)"
    if m and _has_letter(m[1]):
        return m[1].strip(), _number(m[2])
    m = re.match(r"^#?(\d+(?:\.\d+)?)\s*[-.:)]?\s+(.+?)\s+[-–—:]\s+\S.*$", t)
    if m and _has_letter(m[2]):
        return m[2].strip(), _number(m[1])
    m = re.match(rf"^(.+?),?\s+{NUMBERED}(?:\s*[-–—:].*)?$", t, re.I)
    if m and _has_letter(m[1]):
        return re.sub(r"[\s,:–—-]+$", "", m[1]).strip(), _number(m[2])
    return None


def _number(text: str) -> float:
    value = float(text)
    return int(value) if value.is_integer() else value
