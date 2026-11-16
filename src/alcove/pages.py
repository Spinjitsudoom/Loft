"""Pages for the reader: what a book file holds (its manifest) and each page as an image.

PDF pages are rendered with PDFium; comic pages come straight out of the archive. Both are stored
as JPEGs in the data dir (keyed by the file's version, so a replaced file never shows old pages) and
pruned when the cache grows past page_cache_mb.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
from pathlib import Path

from PIL import Image

from . import comics
from .config import Config
from .db import session
from .pdfium import open_pdf

log = logging.getLogger(__name__)

READABLE = {"pdf", "cbz", "cbr", "cb7"}
PAGE_WIDTHS = (600, 900, 1200, 1800, 2400)
MAX_PIXELS = 16_000_000
JPEG_QUALITY = 88


class Unreadable(Exception):
    """kind: "format" (can't be read here yet), "protected" (DRM/password) or "damaged"."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def _file(cfg: Config, file_id: int):
    with session(cfg.db_path) as con:
        row = con.execute("SELECT id, path, format, mtime FROM book_files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise LookupError(file_id)
    return row


def _pdf_manifest(path: Path) -> tuple[list[list[float]], list[dict]]:
    import pypdfium2 as pdfium

    try:
        with open_pdf(path) as doc:
            sizes = [[round(w), round(h)] for w, h in (doc.get_page_size(i) for i in range(len(doc)))]
            toc = []
            for b in doc.get_toc():
                dest = b.get_dest()
                index = dest.get_index() if dest is not None else None
                if index is not None and 0 <= index < len(sizes):
                    toc.append({"title": (b.get_title() or "").strip() or f"Page {index + 1}",
                                "page": index, "level": b.level})
    except pdfium.PdfiumError as e:
        raise Unreadable("protected" if "password" in str(e).lower() else "damaged") from e
    if not sizes:
        raise Unreadable("damaged")
    return sizes, toc


def _comic_manifest(path: Path) -> list[list[int]]:
    try:
        names = comics.page_names(path)
        sizes = []
        for name in names:
            with Image.open(io.BytesIO(comics.read_member(path, name))) as img:
                sizes.append(list(img.size))
    except (comics.ComicError, OSError) as e:
        raise Unreadable("damaged") from e
    if not sizes:
        raise Unreadable("damaged")
    return sizes


def manifest(cfg: Config, file_id: int) -> dict:
    f = _file(cfg, file_id)
    if f["format"] not in READABLE:
        raise Unreadable("format")
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM page_info WHERE file_id = ?", (file_id,)).fetchone()
    if row is None or row["mtime"] != f["mtime"]:
        path = Path(f["path"])
        if f["format"] == "pdf":
            sizes, toc = _pdf_manifest(path)
        else:
            sizes, toc = _comic_manifest(path), []
        with session(cfg.db_path) as con:
            con.execute("INSERT INTO page_info(file_id, mtime, count, sizes, toc) VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(file_id) DO UPDATE SET mtime = excluded.mtime, count = excluded.count, "
                        "sizes = excluded.sizes, toc = excluded.toc",
                        (file_id, f["mtime"], len(sizes), json.dumps(sizes), json.dumps(toc)))
    else:
        sizes, toc = json.loads(row["sizes"]), json.loads(row["toc"])
    return {"file_id": file_id, "format": f["format"], "count": len(sizes), "sizes": sizes, "toc": toc,
            "version": int(f["mtime"])}


def snap_width(width: int) -> int:
    """The smallest stored width at least as wide as asked (never blurrier than the screen)."""
    return next((w for w in PAGE_WIDTHS if w >= width), PAGE_WIDTHS[-1])


def render_page(cfg: Config, file_id: int, index: int, width: int) -> Path:
    m = manifest(cfg, file_id)
    if not 0 <= index < m["count"]:
        raise IndexError(index)
    w = snap_width(width)
    folder = cfg.page_dir / f"{file_id}-{m['version']}"
    target = folder / f"{index}-{w}.jpg"
    if target.is_file():
        return target

    for old in cfg.page_dir.glob(f"{file_id}-*"):
        if old != folder:
            shutil.rmtree(old, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)

    path = Path(_file(cfg, file_id)["path"])
    page_w, page_h = m["sizes"][index]
    if m["format"] == "pdf":
        scale = w / page_w
        if (page_w * scale) * (page_h * scale) > MAX_PIXELS:
            scale = (MAX_PIXELS / (page_w * page_h)) ** 0.5
        with open_pdf(path) as doc:
            page = doc[index]
            image = page.render(scale=scale).to_pil()
            page.close()
    else:
        name = comics.page_names(path)[index]
        image = Image.open(io.BytesIO(comics.read_member(path, name)))
        image.load()
        if image.width > w:
            image = image.resize((w, max(1, round(image.height * w / image.width))), Image.Resampling.LANCZOS)
        if image.width * image.height > MAX_PIXELS:
            f = (MAX_PIXELS / (image.width * image.height)) ** 0.5
            image = image.resize((int(image.width * f), int(image.height * f)), Image.Resampling.LANCZOS)

    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    image.convert("RGB").save(tmp, "JPEG", quality=JPEG_QUALITY)
    os.replace(tmp, target)  # two readers rendering the same page never see half a file
    return target


def prune_page_cache(cfg: Config) -> None:
    """Keep the page cache under page_cache_mb: drop the oldest pages until it's at 80%."""
    if not cfg.page_dir.is_dir():
        return
    files = [(p.stat().st_mtime, p.stat().st_size, p) for p in cfg.page_dir.rglob("*.jpg")]
    total = sum(size for _, size, _ in files)
    limit = cfg.page_cache_mb * 1024 * 1024
    if total <= limit:
        return
    goal = limit * 0.8
    for _, size, p in sorted(files):
        if total <= goal:
            break
        p.unlink(missing_ok=True)
        total -= size
    for folder in cfg.page_dir.iterdir():
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
