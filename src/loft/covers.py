"""Book covers: taken once from the book (or Calibre's cover.jpg) and kept, resized, in the data dir."""

from __future__ import annotations

import colorsys
import io
import logging
import posixpath
import re
import threading
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from . import comics
from .config import Config
from .db import session
from .pdfium import open_pdf

log = logging.getLogger(__name__)

WIDTHS = (240, 480)
PDF_COVER_WIDTH = 600
MAX_LIGHTNESS = 0.29  # a little under the 0.30 limit, so rounding to whole RGB values stays under it
NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
}


def extract_cover(path: Path, fmt: str) -> bytes | None:
    """The book's own cover image, or None. Never raises."""
    try:
        if fmt == "epub":
            return _epub_cover(path)
        if fmt == "pdf":
            return _pdf_cover(path)
        if fmt in ("cbz", "cbr", "cb7"):
            names = comics.page_names(path)
            return comics.read_member(path, names[0]) if names else None
    except Exception as e:
        log.info("No cover from %s: %s", path, e)
    return None


def _epub_cover(path: Path) -> bytes | None:
    with zipfile.ZipFile(path) as z:
        rootfile = ET.fromstring(z.read("META-INF/container.xml")).find(".//c:rootfile", NS)
        opf_path = rootfile.get("full-path")
        opf = ET.fromstring(z.read(opf_path))
        items = opf.findall("opf:manifest/opf:item", NS)
        href = next((i.get("href") for i in items if "cover-image" in (i.get("properties") or "").split()), None)
        if href is None:
            meta = next((m for m in opf.findall("opf:metadata/opf:meta", NS) if m.get("name") == "cover"), None)
            if meta is not None:
                href = next((i.get("href") for i in items if i.get("id") == meta.get("content")), None)
        if href is None:
            href = next((i.get("href") for i in items
                         if (i.get("media-type") or "").startswith("image/") and "cover" in (i.get("id") or "").lower()),
                        None)
        if href is None:
            return None
        return z.read(posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href)))


def _pdf_cover(path: Path) -> bytes | None:
    with open_pdf(path) as doc:
        page = doc[0]
        image = page.render(scale=PDF_COVER_WIDTH / page.get_width()).to_pil().convert("RGB")
        page.close()
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def cover_path(cfg: Config, book_id: int, width: int) -> Path | None:
    w = min(WIDTHS, key=lambda size: abs(size - width))
    p = cfg.cover_dir / f"{book_id}-{w}.jpg"
    return p if p.is_file() else None


def remove_cover(cfg: Config, book_id: int) -> None:
    for w in WIDTHS:
        (cfg.cover_dir / f"{book_id}-{w}.jpg").unlink(missing_ok=True)


def store_cover(cfg: Config, book_id: int, image: bytes) -> str:
    """Save the cover at each size; returns a dark version of its colour for backgrounds."""
    img = Image.open(io.BytesIO(image))
    img.load()
    img = img.convert("RGB")
    cfg.cover_dir.mkdir(parents=True, exist_ok=True)
    for w in WIDTHS:
        h = max(1, round(img.height * w / img.width))
        img.resize((w, h), Image.Resampling.LANCZOS).save(cfg.cover_dir / f"{book_id}-{w}.jpg", "JPEG", quality=85)
    r, g, b = img.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    hue, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    r, g, b = colorsys.hls_to_rgb(hue, min(light, MAX_LIGHTNESS), sat)
    return "#" + "".join(f"{round(c * 255):02x}" for c in (r, g, b))


SPINE_THUMB_WIDTH = 72
SPINE_COLOURS = 8
ACCENT_DISTANCE = 70  # an accent this far from the base (in RGB) reads as a second colour
SHADE = 0.45  # a one-colour cover's label: a deep shade of its spine


def _hexes(*colours: tuple[int, ...]) -> str:
    return " ".join("#" + "".join(f"{c:02x}" for c in colour) for colour in colours)


def spine_palette(img: Image.Image) -> str:
    """The cover's main colour and its next most striking one, as "#base #accent", for a book's spine.
    A colour scores by how much of the cover it covers and how vivid it is."""
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        img = Image.alpha_composite(Image.new("RGBA", rgba.size, (0, 0, 0, 255)), rgba)
    img = img.convert("RGB")
    h = max(1, round(img.height * SPINE_THUMB_WIDTH / img.width))
    small = img.resize((SPINE_THUMB_WIDTH, h), Image.Resampling.BOX)
    quant = small.quantize(SPINE_COLOURS, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    total = small.width * small.height
    scored = []
    for count, index in quant.getcolors(256) or []:
        rgb = tuple(palette[index * 3:index * 3 + 3])
        _, light, sat = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        chroma = sat * (1 - abs(2 * light - 1))
        scored.append((count / total * (0.6 + 2.2 * chroma), rgb))
    scored.sort(key=lambda s: s[0], reverse=True)
    base = scored[0][1] if scored else (0, 0, 0)
    far = [rgb for _, rgb in scored if sum((a - b) ** 2 for a, b in zip(rgb, base)) ** 0.5 > ACCENT_DISTANCE]
    accent = far[0] if far else tuple(round(c * SHADE) for c in base)
    return _hexes(base, accent)


def spine_colours(cfg: Config, book_id: int) -> str | None:
    """The spine palette of Loft's stored copy of the book's cover; None if there isn't a readable one."""
    try:
        with Image.open(cfg.cover_dir / f"{book_id}-480.jpg") as img:
            img.load()
            return spine_palette(img)
    except (OSError, ValueError):
        return None


def fill_spines(cfg: Config, batch: int = 50) -> int:
    """Give every book with a cover but no spine palette yet its palette, from Loft's stored copy of the
    cover (never the book). A book whose copy is missing or unreadable is skipped. Returns how many it filled."""
    with session(cfg.db_path) as con:
        ids = [r[0] for r in con.execute("SELECT id FROM books WHERE has_cover = 1 AND spine_colors IS NULL ORDER BY id")]
    filled = 0
    for start in range(0, len(ids), batch):
        found = [(spine, bid) for bid in ids[start:start + batch] if (spine := spine_colours(cfg, bid))]
        if not found:
            continue
        with session(cfg.db_path) as con:   # one short write per batch; a cover cleared or set meanwhile wins
            for spine, bid in found:
                filled += con.execute("UPDATE books SET spine_colors = ? WHERE id = ? AND has_cover = 1 "
                                      "AND spine_colors IS NULL", (spine, bid)).rowcount
    if filled:
        log.info("Gave %d books their spine colours", filled)
    return filled


class SpineFiller:
    """Once, at start: fills in the spine palettes of books stored before Loft kept them."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="loft-spines", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            fill_spines(self.cfg)
        except Exception:   # the spines keep their plain look until the next start
            log.exception("Filling in the spine colours failed")
