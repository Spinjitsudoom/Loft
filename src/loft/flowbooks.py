"""Opening flowing books for the reader, whatever their format, with a small cache of open books."""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image

from .config import Config
from .db import session
from .epub import open_epub
from .fb2 import open_fb2
from .flow import READABLE_FLOW, FlowBook, Unreadable
from .kindle import open_kindle
from .txt import open_txt

CACHE_SIZE = 8
_cache: OrderedDict[tuple[int, float], FlowBook] = OrderedDict()
_sizes: dict[tuple[int, float, str], tuple[int, int] | None] = {}
_lock = threading.Lock()


def open_flow(cfg: Config, file_id: int) -> tuple[FlowBook, int]:
    """The flow book for a file, and its version. LookupError for an unknown file."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT path, format, mtime FROM book_files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise LookupError(file_id)
    if row["format"] not in READABLE_FLOW:
        raise Unreadable("format")
    key = (file_id, row["mtime"])
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key], int(row["mtime"])
    path, fmt, version = Path(row["path"]), row["format"], int(row["mtime"])
    if fmt == "epub":
        book = open_epub(path)
    elif fmt in ("mobi", "azw", "azw3"):
        book = open_kindle(cfg, file_id, version, path)
    elif fmt == "fb2":
        book = open_fb2(path)
    else:
        book = open_txt(path)
    with _lock:
        _cache[key] = book
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return book, version


def image_size(file_id: int, version: int, book: FlowBook, path: str) -> tuple[int, int] | None:
    key = (file_id, version, path)
    if key not in _sizes:
        try:
            with Image.open(io.BytesIO(book.read(path))) as img:
                _sizes[key] = img.size
        except Exception:  # an image Pillow can't read (or SVG) just has no size
            _sizes[key] = None
    return _sizes[key]
