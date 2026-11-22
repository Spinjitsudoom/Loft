"""Flow books: books whose text is laid out to fit the screen (EPUB, Kindle, FB2, plain text).

A fixed-layout EPUB (or Kindle book) is one too, with `fixed` set: its chapters are its pages.

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
# The most one file inside a book may unpack to. A chapter or picture bigger than this is a zip bomb
# (a tiny file that unpacks to gigabytes), not a book.
MAX_MEMBER = 48 * 1024 * 1024
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
class FixedLayout:
    """A book laid out page by page (a picture book): each chapter is a page of this size, in CSS px."""
    sizes: list[tuple[int, int]]
    spread: bool = True    # two pages side by side when there's room (false: the book says none)
    rtl: bool = False      # pages turn right to left


@dataclass
class FlowBook:
    chapters: list[Chapter]
    toc: list[TocEntry]
    resources: dict[str, Resource]
    read: Callable[[str], bytes]
    fixed: FixedLayout | None = None
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


def memory_book(chapters: list[tuple[str, str]], toc: list[TocEntry],
                images: dict[str, tuple[str, bytes]] | None = None) -> FlowBook:
    """A flow book made by Loft itself (FB2, plain text): chapters are (title, body XHTML),
    stored as chapter-0.xhtml, chapter-1.xhtml…; images are {path: (media type, bytes)}."""
    images = images or {}
    files: dict[str, bytes] = {}
    for n, (_, body) in enumerate(chapters):
        files[f"chapter-{n}.xhtml"] = f"<html><body>{body}</body></html>".encode()
    for path, (_, data) in images.items():
        files[path] = data
    resources = {path: Resource(path, media) for path, (media, _) in images.items()}

    def read(path: str) -> bytes:
        return files[path]

    return FlowBook(chapters=[Chapter(f"chapter-{n}.xhtml", title) for n, (title, _) in enumerate(chapters)],
                    toc=toc, resources=resources, read=read)
