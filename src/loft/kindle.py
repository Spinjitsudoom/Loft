"""Kindle books (MOBI, AZW, AZW3): unpacked once into the data dir, then read as EPUB.

Newer Kindle files (KF8/AZW3) unpack to a real EPUB. Old MOBI files unpack to one HTML file, which
is split into chapters at its page breaks. Books with DRM are recognised from the file's header and
reported as protected (Loft never tries to remove DRM).
"""

from __future__ import annotations

import logging
import re
import shutil
import struct
from pathlib import Path

from .config import Config
from .epub import open_epub
from .flow import Chapter, FlowBook, Resource, TocEntry, Unreadable

log = logging.getLogger(__name__)
PAGEBREAK = re.compile(r"<mbp:pagebreak\s*/?>", re.I)
ANCHOR = re.compile(r"""\bid=["']([^"']+)["']""", re.I)
LOCAL_LINK = re.compile(r"""href=["']#([^"']+)["']""", re.I)
TITLE = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.I | re.S)
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}


def encryption_type(path: Path) -> int:
    """The PalmDOC header's encryption field (0 = none, 1 = old Mobipocket, 2 = Kindle DRM)."""
    with open(path, "rb") as f:
        head = f.read(86)
        if len(head) < 86 or head[60:68] not in (b"BOOKMOBI", b"TEXtREAd"):
            raise Unreadable("damaged")
        (record0,) = struct.unpack_from(">I", head, 78)
        f.seek(record0)
        palmdoc = f.read(16)
    if len(palmdoc) < 14:
        raise Unreadable("damaged")
    return struct.unpack_from(">H", palmdoc, 12)[0]


def _unpack(path: Path, target: Path) -> None:
    import mobi

    tempdir, out = mobi.extract(str(path))
    try:
        out = Path(out)
        target.mkdir(parents=True, exist_ok=True)
        if out.suffix == ".epub":
            shutil.copy(out, target / "book.epub")
        elif out.suffix in (".html", ".htm"):
            shutil.copytree(out.parent, target / "html", dirs_exist_ok=True)
        else:
            raise Unreadable("damaged")
        (target / "done").write_text("ok")
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def _html_book(folder: Path) -> FlowBook:
    raw = (folder / "book.html").read_text(encoding="utf-8", errors="replace")
    body = re.split(r"<body[^>]*>", raw, maxsplit=1, flags=re.I)[-1]
    body = re.split(r"</body>", body, maxsplit=1, flags=re.I)[0]
    pieces = [p for p in PAGEBREAK.split(body) if re.sub(r"<[^>]+>|\s", "", p) or ANCHOR.search(p)]
    # The unpacker writes links as href="#fileposN" to <a id="fileposN"/>; once the book is split into
    # chapters, each link has to name the chapter its target landed in.
    where = {m.group(1): n for n, p in enumerate(pieces) for m in ANCHOR.finditer(p)}

    def relink(m):
        target = m.group(1)
        return f'href="chapter-{where[target]}.xhtml#{target}"' if target in where else m.group(0)

    pieces = [LOCAL_LINK.sub(relink, p) for p in pieces]
    files = {f"chapter-{n}.xhtml": f"<html><body>{p}</body></html>".encode() for n, p in enumerate(pieces)}
    resources = {}
    for img in folder.rglob("*"):
        if img.suffix.lower() in IMAGE_TYPES:
            rel = img.relative_to(folder).as_posix()
            resources[rel] = Resource(rel, IMAGE_TYPES[img.suffix.lower()])
    chapters, toc = [], []
    for n, p in enumerate(pieces):
        m = TITLE.search(p)
        title = " ".join(re.sub(r"<[^>]+>", "", m.group(1)).split()) if m else ""
        chapters.append(Chapter(f"chapter-{n}.xhtml", title))
        if title:
            toc.append(TocEntry(title, n, "", 0))

    def read(member: str) -> bytes:
        if member in files:
            return files[member]
        p = (folder / member).resolve()
        if folder.resolve() not in p.parents:
            raise KeyError(member)
        return p.read_bytes()

    return FlowBook(chapters=chapters, toc=toc, resources=resources, read=read)


def open_kindle(cfg: Config, file_id: int, version: int, path: Path) -> FlowBook:
    if encryption_type(path) != 0:
        raise Unreadable("protected")
    target = cfg.flow_dir / f"{file_id}-{version}"
    if not (target / "done").is_file():
        for old in cfg.flow_dir.glob(f"{file_id}-*"):
            shutil.rmtree(old, ignore_errors=True)
        try:
            _unpack(path, target)
        except Unreadable:
            raise
        except Exception as e:  # the unpacker raises many kinds of errors on odd files
            log.info("Couldn't unpack %s: %s", path, e)
            shutil.rmtree(target, ignore_errors=True)
            raise Unreadable("damaged") from e
    if (target / "book.epub").is_file():
        return open_epub(target / "book.epub")
    return _html_book(target / "html")
