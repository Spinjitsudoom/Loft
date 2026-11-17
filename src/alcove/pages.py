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
import tempfile
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
        row = con.execute("SELECT id, path, format, mtime, layout, layout_rev FROM book_files WHERE id = ?",
                          (file_id,)).fetchone()
    if row is None:
        raise LookupError(file_id)
    return row


SPREAD_MIN_RATIO = 1.15          # wider than this is a two-page scan...
HALF_RATIOS = (0.5, 0.9)         # ...if each half is page-shaped
TEXT_CHARS = 20                  # a PDF page with real text isn't a scan


def _is_spread(w: float, h: float) -> bool:
    return w / h > SPREAD_MIN_RATIO and HALF_RATIOS[0] <= (w / 2) / h <= HALF_RATIOS[1]


def split_plan(sizes: list[list[float]], scanned: bool = True, *, split: bool | None = None,
               wraparound: bool | None = None) -> list[tuple[int, int | None]]:
    """Which source page (and which half of it) each reader page shows.

    Scanned comics often hold two printed pages per image. When at least half of a book's pages
    are such spreads (and they're scans, not text), each one becomes a left and a right page, so
    the pages turn one at a time like the printed book. Single pages (a cover) stay whole.
    The admin can override this per book: split (always / never) and wraparound (False keeps a
    wide first scan in its scanned order)."""
    spreads = [_is_spread(w, h) for w, h in sizes]
    automatic = scanned and sum(spreads) * 2 >= len(sizes)
    if not (automatic if split is None else split):
        return [(i, None) for i in range(len(sizes))]
    plan: list[tuple[int, int | None]] = []
    for i, is_spread in enumerate(spreads):
        plan.extend([(i, 0), (i, 1)] if is_spread else [(i, None)])
    if spreads and spreads[0] and wraparound is not False:
        # A wide first scan is a wraparound cover (the inside of a comic never opens on a spread):
        # like the printed comic, the front (right half) comes first and the back (left half) last.
        plan = [(0, 1)] + plan[2:] + [(0, 0)]
    return plan


def _pdf_is_scanned(doc, sizes: list[list[float]]) -> bool:
    """Look at the first wide page: scans have no text layer."""
    i = next((i for i, (w, h) in enumerate(sizes) if _is_spread(w, h)), None)
    if i is None:
        return False
    page = doc[i]
    try:
        text = page.get_textpage()
        try:
            return text.count_chars() < TEXT_CHARS
        finally:
            text.close()
    finally:
        page.close()


def _pdf_manifest(path: Path) -> tuple[list[list[float]], list[dict], bool]:
    import pypdfium2 as pdfium

    try:
        with open_pdf(path) as doc:
            sizes = [[round(w), round(h)] for w, h in (doc.get_page_size(i) for i in range(len(doc)))]
            scanned = _pdf_is_scanned(doc, sizes)
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
    return sizes, toc, scanned


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
            source, toc, scanned = _pdf_manifest(path)
        else:
            source, toc, scanned = _comic_manifest(path), [], True
        layout = file_layout(f)
        plan = split_plan(source, scanned, split=layout["split"], wraparound=layout["wraparound"])
        first = {}
        for n, (src, _) in enumerate(plan):
            first.setdefault(src, n)
        toc = [{**t, "page": first[t["page"]]} for t in toc]
        sizes = [[source[src][0] / 2, source[src][1]] if half is not None else source[src] for src, half in plan]
        sizes = [[round(w), round(h)] for w, h in sizes]
        with session(cfg.db_path) as con:
            con.execute("INSERT INTO page_info(file_id, mtime, count, sizes, toc) VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(file_id) DO UPDATE SET mtime = excluded.mtime, count = excluded.count, "
                        "sizes = excluded.sizes, toc = excluded.toc",
                        (file_id, f["mtime"], len(sizes), json.dumps({"pages": sizes, "plan": plan, "source": source}),
                         json.dumps(toc)))
    else:
        stored = json.loads(row["sizes"])
        if isinstance(stored, list):  # stored before pages could be split: work it out again
            with session(cfg.db_path) as con:
                con.execute("DELETE FROM page_info WHERE file_id = ?", (file_id,))
            return manifest(cfg, file_id)
        sizes, plan, source, toc = stored["pages"], stored["plan"], stored["source"], json.loads(row["toc"])
    return {"file_id": file_id, "format": f["format"], "count": len(sizes), "sizes": sizes, "toc": toc,
            "version": int(f["mtime"]) + f["layout_rev"], "plan": [list(p) for p in plan], "source": source}


def file_layout(row) -> dict:
    """The admin's page-layout choices for a file: each True, False or None (automatic)."""
    try:
        stored = json.loads(row["layout"] or "{}")
    except ValueError:
        stored = {}
    return {k: stored.get(k) if isinstance(stored.get(k), bool) else None for k in ("split", "wraparound")}


def set_layout(cfg: Config, file_id: int, split: bool | None, wraparound: bool | None) -> dict:
    f = _file(cfg, file_id)
    if f["format"] not in READABLE:
        raise ValueError("Only PDFs and comics have page layouts")
    with session(cfg.db_path) as con:
        con.execute("UPDATE book_files SET layout = ?, layout_rev = layout_rev + 1 WHERE id = ?",
                    (json.dumps({"split": split, "wraparound": wraparound}), file_id))
        con.execute("DELETE FROM page_info WHERE file_id = ?", (file_id,))
    return manifest(cfg, file_id)


def snap_width(width: int) -> int:
    """The smallest stored width at least as wide as asked (never blurrier than the screen)."""
    return next((w for w in PAGE_WIDTHS if w >= width), PAGE_WIDTHS[-1])


def render_page(cfg: Config, file_id: int, index: int, width: int) -> Path:
    m = manifest(cfg, file_id)
    if not 0 <= index < m["count"]:
        raise IndexError(index)
    w = snap_width(width)
    folder = cfg.page_dir / f"{file_id}-{m['version']}-{m['count']}"  # count changes when pages are split
    target = folder / f"{index}-{w}.jpg"
    if target.is_file():
        return target

    for old in cfg.page_dir.glob(f"{file_id}-*"):
        if old != folder:
            shutil.rmtree(old, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)

    path = Path(_file(cfg, file_id)["path"])
    src, half = m["plan"][index]
    page_w, page_h = m["source"][src]
    full_w = w * 2 if half is not None else w  # a half page is rendered from a source twice as wide
    if m["format"] == "pdf":
        scale = full_w / page_w
        if (page_w * scale) * (page_h * scale) > MAX_PIXELS * (2 if half is not None else 1):
            scale = (MAX_PIXELS * (2 if half is not None else 1) / (page_w * page_h)) ** 0.5
        with open_pdf(path) as doc:
            page = doc[src]
            image = page.render(scale=scale).to_pil()
            page.close()
    else:
        name = comics.page_names(path)[src]
        image = Image.open(io.BytesIO(comics.read_member(path, name)))
        image.load()
    if half is not None:
        mid = image.width // 2
        image = image.crop((0, 0, mid, image.height) if half == 0 else (mid, 0, image.width, image.height))
    if m["format"] != "pdf":
        if image.width > w:
            image = image.resize((w, max(1, round(image.height * w / image.width))), Image.Resampling.LANCZOS)
        if image.width * image.height > MAX_PIXELS:
            f = (MAX_PIXELS / (image.width * image.height)) ** 0.5
            image = image.resize((int(image.width * f), int(image.height * f)), Image.Resampling.LANCZOS)

    # A temp file of its own per render: two requests for the same page never share one.
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            image.convert("RGB").save(f, "JPEG", quality=JPEG_QUALITY)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
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
