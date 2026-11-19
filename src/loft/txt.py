"""Plain-text books: paragraphs at blank lines, chapters at "Chapter 1" / "PART TWO" / "IV" lines."""

from __future__ import annotations

import html
import re
from pathlib import Path

from .flow import FlowBook, TocEntry, Unreadable, memory_book

HEADING = re.compile(r"^(?:(?:chapter|part|book|prologue|epilogue)\b.{0,80}|[IVXLC]{1,7}\.?)$", re.I)
PARAGRAPHS_PER_PART = 40


def decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text) if re.search(r"\n\s*\n", text) else text.split("\n")
    return [" ".join(b.split()) for b in blocks if b.strip()]


def open_txt(path: Path) -> FlowBook:
    try:
        paragraphs = _paragraphs(decode(path.read_bytes()))
    except OSError as e:
        raise Unreadable("damaged") from e
    if not paragraphs:
        raise Unreadable("damaged")

    chapters: list[tuple[str, list[str]]] = []
    found_headings = any(HEADING.match(p) for p in paragraphs)
    if found_headings:
        current = ("Opening", [])
        for p in paragraphs:
            if HEADING.match(p):
                if current[1] or current[0] != "Opening":
                    chapters.append(current)
                current = (p, [])
            else:
                current[1].append(p)
        chapters.append(current)
    else:
        for i in range(0, len(paragraphs), PARAGRAPHS_PER_PART):
            chapters.append((f"Part {i // PARAGRAPHS_PER_PART + 1}", paragraphs[i:i + PARAGRAPHS_PER_PART]))

    built = []
    for title, body in chapters:
        # Headings found in the text are shown; "Opening" and made-up "Part N" chunks aren't in the text.
        heading = f"<h2>{html.escape(title)}</h2>" if found_headings and title != "Opening" else ""
        built.append((title, heading + "".join(f"<p>{html.escape(p)}</p>" for p in body)))
    toc = [TocEntry(title, n, "", 0) for n, (title, _) in enumerate(chapters)]
    return memory_book(built, toc)
