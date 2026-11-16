"""Details read from a book file itself: for books Calibre doesn't know about.

Never raises: a damaged or unreadable file still gets a title from its filename, so it shows up.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

CALIBRE_BOOK_DIR = re.compile(r" \(\d+\)$")
JUNK_EXTENSIONS = (".doc", ".docx", ".pdf", ".indd", ".qxd", ".rtf", ".txt", ".tex", ".dvi")
AUTHOR_SPLIT = re.compile(r"\s*(?:;|&|\band\b)\s*")

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass
class FileMeta:
    title: str
    authors: list[str] = field(default_factory=list)
    description: str = ""
    language: str = ""
    published: str = ""
    publisher: str = ""
    series: str = ""
    series_index: float | None = None
    encrypted: bool = False


def title_from_filename(path: Path) -> str:
    stem = path.stem
    # Calibre names files "Title - Author" inside a "Title (id)" folder; elsewhere a dash is part of the title.
    if CALIBRE_BOOK_DIR.search(path.parent.name) and " - " in stem:
        stem = stem.rsplit(" - ", 1)[0]
    stem = re.sub(r"_ ", ": ", stem)  # Calibre writes ":" as "_"
    stem = stem.replace("_", " ")
    return re.sub(r"\s+", " ", stem).strip() or path.name


SITE_SUFFIX = re.compile(r"\s*[-|–]\s*(?:www\.)?[\w-]+\.(?:com|net|org|ru|info|to)\s*$", re.I)
SITE = re.compile(r"^(?:www\.)?[\w-]+\.(?:com|net|org|ru|info|to)$", re.I)


def clean_title(title: str) -> str:
    """Tidy an embedded title: control characters, escaped quotes, download-site suffixes."""
    t = "".join(ch for ch in (title or "") if ch.isprintable() or ch == " ")
    t = t.replace("\\'", "'").replace('\\"', '"')
    t = SITE_SUFFIX.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def is_junk_title(title: str, path: Path) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    low = t.lower()
    return (low.startswith("microsoft word - ")
            or re.fullmatch(r"untitled\d*", low) is not None
            or re.fullmatch(r"[\d\W_]+", t) is not None
            or SITE.fullmatch(t) is not None
            or t == path.stem
            or low.endswith(JUNK_EXTENSIONS))


PLACEHOLDER_AUTHORS = {"unknown", "unknown author", "unknown authors"}


def real_authors(names: list[str]) -> list[str]:
    """Drop "Unknown" and its kin: they're what Calibre and PDF tools write when there's no author."""
    return [n for n in names if n.strip().lower() not in PLACEHOLDER_AUTHORS]


def split_authors(value: str) -> list[str]:
    return real_authors([a.strip() for a in AUTHOR_SPLIT.split(value or "") if a.strip()])


def _text(html: str) -> str:
    from .calibre import html_to_text
    return html_to_text(html)


def read_file_meta(path: Path, fmt: str) -> FileMeta:
    fallback = FileMeta(title=title_from_filename(path))
    try:
        if fmt == "pdf":
            meta = _pdf(path)
        elif fmt == "epub":
            meta = _epub(path)
        else:
            return fallback
    except Exception as e:  # damaged files must never stop a scan
        log.info("Couldn't read details from %s: %s", path, e)
        return fallback
    meta.title = clean_title(meta.title)
    if is_junk_title(meta.title, path):
        meta.title = fallback.title
    return meta


def _pdf(path: Path) -> FileMeta:
    import pypdfium2 as pdfium

    from .pdfium import open_pdf

    try:
        with open_pdf(path) as doc:
            info = doc.get_metadata_dict(skip_empty=True)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            return FileMeta(title=title_from_filename(path), encrypted=True)
        raise
    return FileMeta(title=info.get("Title", "").strip(), authors=split_authors(info.get("Author", "")))


def _epub(path: Path) -> FileMeta:
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", NS)
        opf_path = rootfile.get("full-path") if rootfile is not None else None
        if not opf_path:
            raise ValueError("no OPF in container.xml")
        opf = ET.fromstring(z.read(opf_path))
    md = opf.find("opf:metadata", NS)
    if md is None:
        raise ValueError("OPF has no metadata")

    def first(tag: str) -> str:
        el = md.find(f"dc:{tag}", NS)
        return "".join(el.itertext()).strip() if el is not None else ""

    meta = FileMeta(
        title=first("title"),
        authors=real_authors([(el.text or "").strip() for el in md.findall("dc:creator", NS) if (el.text or "").strip()]),
        description=_text(first("description")),
        language=first("language"),
        published=first("date")[:10],
        publisher=first("publisher"),
    )
    metas = {el.get("name"): el.get("content", "") for el in md.findall("opf:meta", NS) if el.get("name")}
    if metas.get("calibre:series"):
        meta.series = metas["calibre:series"].strip()
        meta.series_index = _float(metas.get("calibre:series_index"))
    else:  # EPUB 3 collections
        refines = {el.get("refines", "").lstrip("#"): el for el in md.findall("opf:meta", NS)
                   if el.get("property") == "group-position"}
        for el in md.findall("opf:meta", NS):
            if el.get("property") == "belongs-to-collection" and (el.text or "").strip():
                meta.series = el.text.strip()
                pos = refines.get(el.get("id", ""))
                meta.series_index = _float(pos.text if pos is not None else None)
                break
    return meta


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
