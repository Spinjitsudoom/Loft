"""Calibre's library: a one-way import of its details (titles, authors, series, tags, covers).

Calibre's metadata.db is opened read-only and "immutable", so Alcove never writes to it or leaves
lock files next to it (it usually sits on a network share).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

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
