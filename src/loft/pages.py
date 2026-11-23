"""Pages for the reader: what a book file holds (its manifest) and each page as an image.

PDF pages are rendered with PDFium; comic pages come straight out of the archive. Both are stored
as JPEGs in the data dir, keyed by the file's modified time and the piece of the file they show (a
whole page or one half of a two-page scan), so a replaced file never shows old pages and changing
the layout or the page order never draws a page again. Pruned when the cache grows past page_cache_mb.

The page order is worked out in three steps: the file's own pages; split_plan (two-page scans cut
in two, wraparound covers, manga direction); then arrange (the admin's own order and hidden pages).
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
FIXED_FORMATS = {"epub", "azw3", "azw", "mobi"}  # flowing formats a fixed-layout book (a picture book) can come in
PAGE_WIDTHS = (200, 600, 900, 1200, 1800, 2400)  # 200: thumbnails for arranging pages
MAX_ENTRIES = 20_000

Entry = tuple[int, "int | None"]  # (source page, half: 0 left, 1 right, None whole); a negative page is a blank
MAX_BLANKS = 100
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
               wraparound: bool | None = None, rtl: bool = False) -> list[tuple[int, int | None]]:
    """Which source page (and which half of it) each reader page shows.

    Scanned comics often hold two printed pages per image. When at least half of a book's pages
    are such spreads (and they're scans, not text), each one becomes a left and a right page, so
    the pages turn one at a time like the printed book. Single pages (a cover) stay whole.
    The admin can override this per book: split (always / never) and wraparound (False keeps a
    wide first scan in its scanned order).

    A manga (rtl) is printed the other way round: each scan's right half is the earlier page, and
    its wraparound cover has the front on the left."""
    spreads = [_is_spread(w, h) for w, h in sizes]
    automatic = scanned and sum(spreads) * 2 >= len(sizes)
    if not (automatic if split is None else split):
        return [(i, None) for i in range(len(sizes))]
    plan: list[tuple[int, int | None]] = []
    for i, is_spread in enumerate(spreads):
        halves = [(i, 1), (i, 0)] if rtl else [(i, 0), (i, 1)]
        plan.extend(halves if is_spread else [(i, None)])
    if spreads and spreads[0] and wraparound is not False:
        # A wide first scan is a wraparound cover (the inside of a comic never opens on a spread):
        # like the printed comic, the front comes first and the back last.
        front, back = ((0, 0), (0, 1)) if rtl else ((0, 1), (0, 0))
        plan = [front] + plan[2:] + [back]
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


def fixed_layout_of(cfg: Config, row):
    """A fixed-layout book's pages (FlowBook.fixed: their sizes, spreads, direction), or None for any
    other file. Opens the book (kept open in flowbooks' cache); Unreadable if it can't be opened."""
    if row["format"] not in FIXED_FORMATS:
        return None
    return _fixed_book(cfg, row).fixed


def _fixed_book(cfg: Config, row):
    from . import flowbooks  # here, not at the top: flow imports Unreadable from this module
    return flowbooks.open_flow(cfg, row["id"])[0]


def has_pages(cfg: Config, row) -> bool:
    """Whether a file is read as pages, and so has page settings: a PDF, a comic, or a picture book."""
    if row["format"] in READABLE:
        return True
    try:
        return fixed_layout_of(cfg, row) is not None
    except Unreadable:
        return False


def _measured(cfg: Config, f) -> tuple[list[list[float]], list[dict], bool]:
    """What the file itself says: each page's size, its contents, whether it's a scan. Kept, so a
    layout or order change only reworks the plan: measuring a big comic on a network share takes seconds.
    A picture book's pages are its own (never a scan, so Automatic never splits them); the book is
    already kept open, so nothing is stored."""
    if f["format"] not in READABLE:
        book = _fixed_book(cfg, f)
        toc = [{"title": t.title, "chapter": t.chapter, "anchor": t.anchor, "level": t.level, "page": t.chapter}
               for t in book.toc if 0 <= t.chapter < len(book.fixed.sizes)]
        return [list(s) for s in book.fixed.sizes], toc, False
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM page_info WHERE file_id = ?", (f["id"],)).fetchone()
    known = json.loads(row["sizes"]) if row is not None and row["mtime"] == f["mtime"] else None
    if isinstance(known, dict) and "scanned" in known:
        return known["source"], known["source_toc"], known["scanned"]
    # Never measured, the file changed, or measured before this was kept.
    path = Path(f["path"])
    if f["format"] == "pdf":
        source, source_toc, scanned = _pdf_manifest(path)
    else:
        source, source_toc, scanned = _comic_manifest(path), [], True
    with session(cfg.db_path) as con:
        con.execute("INSERT INTO page_info(file_id, mtime, count, sizes, toc) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(file_id) DO UPDATE SET mtime = excluded.mtime, count = excluded.count, "
                    "sizes = excluded.sizes, toc = excluded.toc",
                    (f["id"], f["mtime"], len(source),
                     json.dumps({"source": source, "source_toc": source_toc, "scanned": scanned}), "[]"))
    return source, source_toc, scanned


def _natural(f, source, scanned, default_rtl: bool = False) -> list[Entry]:
    layout = file_layout(f, default_rtl)
    return split_plan(source, scanned, split=layout["split"], wraparound=layout["wraparound"], rtl=layout["rtl"])


def arrange(natural: list[Entry], order: list[Entry] | None, hidden: list[Entry]) -> tuple[list[Entry], list[Entry], list[Entry]]:
    """The admin's page order and hidden pages, laid over the pages there are now.
    Returns (the pages to show, every page in order, the hidden ones).

    The order was saved against the pages as they were then; if split, wraparound or the file has
    changed since, each page goes where the admin put it as nearly as can be: a half where its whole
    page was (or the other way round), a page the order doesn't know right after the page before it."""
    natural = [tuple(e) for e in natural]
    order = [tuple(e) for e in order or []]
    position = {e: i for i, e in enumerate(order)}
    page_position: dict[int, int] = {}
    for i, (src, _) in enumerate(order):
        page_position.setdefault(src, i)
    keyed, last = [], -1
    for n, e in enumerate(natural):
        if e in position:
            key = (position[e], 0, n)
        elif e[0] in page_position:
            key = (page_position[e[0]], 1, n)
        else:
            key = (last, 2, n)
        last = key[0]
        keyed.append((key, e))
    # Blank pages the admin put in (negative page numbers) stay exactly where they were put.
    keyed += [((position[e], 0, -1), e) for e in order if e[0] < 0]
    every = [e for _, e in sorted(keyed)]

    hide = {tuple(e) for e in hidden or []}

    def is_hidden(e: Entry) -> bool:
        src, half = e
        return e in hide or (src, None) in hide or (half is None and (src, 0) in hide and (src, 1) in hide)

    shown = [e for e in every if not is_hidden(e)]
    if not shown:
        return every, every, []
    return shown, every, [e for e in every if is_hidden(e)]


def _stored_layout(row) -> dict:
    try:
        stored = json.loads(row["layout"] or "{}")
    except ValueError:
        stored = {}
    return stored if isinstance(stored, dict) else {}


def _entries(value, blanks: bool = False) -> list[Entry]:
    """Pages as the app sends them: [source page, half] with half 0, 1 or null. With `blanks`, a
    negative page number is a blank page (always whole)."""
    if not isinstance(value, list) or len(value) > MAX_ENTRIES:
        raise ValueError("The pages must be a list")
    entries = []
    for item in value:
        if (not isinstance(item, (list, tuple)) or len(item) != 2 or not isinstance(item[0], int)
                or isinstance(item[0], bool) or (item[0] < 0 and not (blanks and item[1] is None))
                or item[1] not in (None, 0, 1) or isinstance(item[1], bool)):
            raise ValueError("Each page must be a page number and which half of it")
        entries.append((item[0], item[1]))
    return entries


def _arrangement(row) -> tuple[list[Entry] | None, list[Entry]]:
    stored = _stored_layout(row)
    try:
        order = _entries(stored["order"], blanks=True) if stored.get("order") is not None else None
        hidden = _entries(stored.get("hidden") or [])
    except ValueError:
        return None, []
    return order, hidden


def is_arranged(row) -> bool:
    order, hidden = _arrangement(row)
    return order is not None or bool(hidden)


def manifest(cfg: Config, file_id: int) -> dict:
    f = _file(cfg, file_id)
    fixed = None if f["format"] in READABLE else fixed_layout_of(cfg, f)
    if f["format"] not in READABLE and fixed is None:
        raise Unreadable("format")
    default_rtl = bool(fixed and fixed.rtl)
    source, source_toc, scanned = _measured(cfg, f)
    natural = _natural(f, source, scanned, default_rtl)
    plan, every, hidden = arrange(natural, *_arrangement(f))

    # A chapter starts on its page, or the next one shown if that page is hidden.
    index = {e: i for i, e in enumerate(plan)}
    first: dict[int, int] = {}
    for n, (src, _) in enumerate(natural):
        first.setdefault(src, n)
    toc = []
    for t in source_toc:
        page = next((index[e] for e in natural[first.get(t["page"], len(natural)):] if e in index), None)
        if page is not None:
            toc.append({**t, "page": page})
    sizes = []
    for src, half in plan:
        if src < 0:  # a blank: as big as the page before it (or the first page)
            sizes.append(sizes[-1] if sizes else None)
        else:
            sizes.append([source[src][0] / 2, source[src][1]] if half is not None else source[src])
    first_real = next((x for x in sizes if x), source[0])
    sizes = [[round(w), round(h)] for w, h in (x or first_real for x in sizes)]
    layout = file_layout(f, default_rtl)
    m = {"file_id": file_id, "format": f["format"], "count": len(sizes), "sizes": sizes, "toc": toc,
         "version": int(f["mtime"]) + f["layout_rev"], "rtl": layout["rtl"],
         "plan": [list(p) for p in plan], "source": source,
         "arranged": [list(p) for p in every], "hidden": [list(p) for p in hidden],
         "custom": is_arranged(f), "file_v": int(f["mtime"])}
    if fixed is not None:  # a picture book: its pages are documents (fixed.js), not pictures
        m.update({"fixed": True, "spread": fixed.spread, "layout": layout, "layout_v": f["layout_rev"]})
    return m


def file_layout(row, default_rtl: bool = False) -> dict:
    """The admin's page-layout choices for a file: split and wraparound are True, False or None
    (automatic); rtl (pages read right to left, as in manga) is True or False, and until the admin
    chooses, default_rtl (a picture book's own direction; comics and PDFs read left to right)."""
    stored = _stored_layout(row)
    layout = {k: stored.get(k) if isinstance(stored.get(k), bool) else None for k in ("split", "wraparound")}
    rtl = stored.get("rtl")
    return {**layout, "rtl": rtl if isinstance(rtl, bool) else default_rtl}


def set_layout(cfg: Config, file_id: int, split: bool | None, wraparound: bool | None,
               rtl: bool | None = None) -> dict:
    """Change a file's page layout. rtl None leaves the reading direction as it was.
    Returns the new manifest; for a file that can't be opened (damaged, protected) the change is
    still kept, and the reply has no pages (count None)."""
    f = _file(cfg, file_id)
    if not has_pages(cfg, f):
        raise ValueError("Only books with pages have page layouts")
    if rtl is None:
        fixed = None if f["format"] in READABLE else fixed_layout_of(cfg, f)
        rtl = file_layout(f, bool(fixed and fixed.rtl))["rtl"]
    _store(cfg, f, {"split": split, "wraparound": wraparound, "rtl": rtl})  # the page order stays
    try:
        return manifest(cfg, file_id)
    except Unreadable:
        return {"count": None, "rtl": rtl}


def _store(cfg: Config, f, changes: dict) -> None:
    with session(cfg.db_path) as con:
        con.execute("UPDATE book_files SET layout = ?, layout_rev = layout_rev + 1 WHERE id = ?",
                    (json.dumps({**_stored_layout(f), **changes}), f["id"]))


def set_arrangement(cfg: Config, file_id: int, order, hidden) -> dict:
    """The admin's own page order (every page, hidden ones too, as the app shows them) and the pages
    to hide. order None (with nothing hidden) puts the file's own order back. Returns the manifest."""
    f = _file(cfg, file_id)
    if not has_pages(cfg, f):
        raise ValueError("Only books with pages have pages to arrange")
    order = None if order is None else _entries(order, blanks=True)
    hidden = list(dict.fromkeys(_entries(hidden or [])))  # a blank is taken out, never hidden
    source, _, scanned = _measured(cfg, f)
    fixed = None if f["format"] in READABLE else fixed_layout_of(cfg, f)
    natural = _natural(f, source, scanned, bool(fixed and fixed.rtl))
    known = set(natural)
    changed = "The pages have changed since this was opened; close it and open it again"
    if order is not None:
        real = [e for e in order if e[0] >= 0]
        blanks = [e for e in order if e[0] < 0]
        if len(real) != len(natural) or set(real) != known:
            raise ValueError(changed)
        if len(set(blanks)) != len(blanks):
            raise ValueError("Each blank page must be listed once")
        if len(blanks) > MAX_BLANKS:
            raise ValueError(f"A book can have at most {MAX_BLANKS} blank pages")
        if order == natural:
            order = None
    if any(e not in known for e in hidden):
        raise ValueError(changed)
    if len(hidden) >= len(natural):
        raise ValueError("A book needs at least one page that isn’t hidden")
    _store(cfg, f, {"order": [list(e) for e in order] if order else None, "hidden": [list(e) for e in hidden]})
    return manifest(cfg, file_id)


def snap_width(width: int) -> int:
    """The smallest stored width at least as wide as asked (never blurrier than the screen)."""
    return next((w for w in PAGE_WIDTHS if w >= width), PAGE_WIDTHS[-1])


def render_page(cfg: Config, file_id: int, index: int, width: int) -> Path:
    """Page `index` as the reader shows it."""
    m = manifest(cfg, file_id)
    if m.get("fixed"):
        raise Unreadable("format")  # a picture book's pages are documents, sent by the chapter route
    if not 0 <= index < m["count"]:
        raise IndexError(index)
    src, half = m["plan"][index]
    if src < 0:
        return _blank(cfg, file_id, m["sizes"][index], snap_width(width))
    return _render(cfg, file_id, m, src, half, snap_width(width))


def render_piece(cfg: Config, file_id: int, src: int, half: int | None, width: int) -> Path:
    """One piece of the file (a page, or half of one), hidden or not: for arranging pages."""
    m = manifest(cfg, file_id)
    if m.get("fixed"):
        raise Unreadable("format")
    if [src, half] not in m["arranged"]:
        raise IndexError((src, half))
    if src < 0:
        size = m["sizes"][m["plan"].index([src, half])] if [src, half] in m["plan"] else m["sizes"][0]
        return _blank(cfg, file_id, size, snap_width(width))
    return _render(cfg, file_id, m, src, half, snap_width(width))


def _blank(cfg: Config, file_id: int, size: list[int], w: int) -> Path:
    """A plain white page, the shape of the pages around it."""
    row = _file(cfg, file_id)
    folder = cfg.page_dir / f"{file_id}-{round(row['mtime'] * 1000)}"
    h = max(1, round(w * size[1] / max(1, size[0])))
    target = folder / f"blank-{w}x{h}.jpg"
    if not target.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                Image.new("RGB", (w, h), (255, 255, 255)).save(f, "JPEG", quality=JPEG_QUALITY)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return target


def _render(cfg: Config, file_id: int, m: dict, src: int, half: int | None, w: int) -> Path:
    row = _file(cfg, file_id)
    folder = cfg.page_dir / f"{file_id}-{round(row['mtime'] * 1000)}"
    target = folder / f"{src}-{'p' if half is None else half}-{w}.jpg"
    if target.is_file():
        return target

    for old in cfg.page_dir.glob(f"{file_id}-*"):
        if old != folder:
            shutil.rmtree(old, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)

    path = Path(row["path"])
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
