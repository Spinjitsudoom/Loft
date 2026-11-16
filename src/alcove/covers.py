"""Book covers: taken once from the book (or Calibre's cover.jpg) and kept, resized, in the data dir."""

from __future__ import annotations

import colorsys
import io
import logging
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from .config import Config

log = logging.getLogger(__name__)

WIDTHS = (240, 480)
PDF_COVER_WIDTH = 600
MAX_LIGHTNESS = 0.29  # a little under the 0.30 limit, so rounding to whole RGB values stays under it
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
}


def natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def extract_cover(path: Path, fmt: str) -> bytes | None:
    """The book's own cover image, or None. Never raises."""
    try:
        if fmt == "epub":
            return _epub_cover(path)
        if fmt == "pdf":
            return _pdf_cover(path)
        if fmt == "cbz":
            return _cbz_cover(path)
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
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        page = doc[0]
        width = page.get_width()
        image = page.render(scale=PDF_COVER_WIDTH / width).to_pil().convert("RGB")
        page.close()
    finally:
        doc.close()
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _cbz_cover(path: Path) -> bytes | None:
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist()
                        if n.lower().endswith(IMAGE_EXTS) and not posixpath.basename(n).startswith(".")
                        and "__macosx" not in n.lower()), key=natural_key)
        return z.read(names[0]) if names else None


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
