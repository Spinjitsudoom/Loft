"""Flow books: books whose text is laid out to fit the screen (EPUB, Kindle, FB2, plain text).

Every such format is turned into the same shape: chapters in reading order (XHTML, sanitised before
it reaches the browser), a table of contents pointing at chapters and anchors, and the images the
chapters use. Paths are the book's own (for EPUB, paths inside the zip).
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote, urldefrag

from .pages import Unreadable  # noqa: F401  (re-exported: flow formats use the same reasons)

READABLE_FLOW = {"epub", "mobi", "azw", "azw3", "fb2", "txt"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"}


@dataclass
class Chapter:
    href: str
    title: str = ""


@dataclass
class TocEntry:
    title: str
    chapter: int
    anchor: str
    level: int


@dataclass
class Resource:
    path: str
    media_type: str


@dataclass
class FlowBook:
    chapters: list[Chapter]
    toc: list[TocEntry]
    resources: dict[str, Resource]
    read: Callable[[str], bytes]
    _index: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._index = {c.href: i for i, c in enumerate(self.chapters)}

    @staticmethod
    def resolve(base: str, href: str) -> str | None:
        """A link or image path in the document at `base`, as a path in the book (no fragment)."""
        target, _ = urldefrag(href or "")
        if not target:
            return base
        if "://" in target or target.startswith(("data:", "mailto:", "javascript:")):
            return None
        path = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(target)))
        return None if path.startswith("../") or path == ".." else path

    def chapter_of(self, path: str | None) -> int | None:
        return self._index.get(path) if path else None

    def images(self) -> dict[str, Resource]:
        return {p: r for p, r in self.resources.items() if r.media_type in IMAGE_TYPES}
