"""Which files are books. Anything else in the books folders (Word files, Calibre's own files,
images) is never shown."""

from __future__ import annotations

from pathlib import Path

BOOK_FORMATS: dict[str, str] = {ext: ext for ext in (
    "epub", "pdf", "cbz", "cbr", "cb7", "mobi", "azw", "azw3", "fb2", "txt",
)}


def format_of(path: Path) -> str | None:
    """The book format of a file, from its extension, or None if it isn't a book."""
    suffix = path.suffix.lower().lstrip(".")
    return BOOK_FORMATS.get(suffix) if suffix else None
