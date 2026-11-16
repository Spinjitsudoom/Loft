"""Comic archives (CBZ, CBR, CB7): a folder of page images in a zip, rar or 7z file.

The archive type is read from the file's first bytes, not its extension: CBZ files that are really
RAR (and the other way round) are common. RAR needs a tool on the server (unrar, unar, 7z or bsdtar).
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
MAX_PAGE_BYTES = 200 * 1024 * 1024  # one page image; anything bigger isn't a comic page
SIGNATURES = {b"PK\x03\x04": "zip", b"Rar!\x1a\x07": "rar", b"7z\xbc\xaf\x27\x1c": "7z"}


class ComicError(Exception):
    pass


def natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def archive_kind(path: Path) -> str | None:
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    return next((kind for sig, kind in SIGNATURES.items() if head.startswith(sig)), None)


def _is_page(name: str) -> bool:
    base = posixpath.basename(name)
    return (name.lower().endswith(IMAGE_EXTS) and not base.startswith(".")
            and "__macosx/" not in name.lower())


def _names(path: Path, kind: str | None) -> list[str]:
    if kind == "zip":
        with zipfile.ZipFile(path) as z:
            return [i.filename for i in z.infolist() if not i.is_dir()]
    if kind == "7z":
        import py7zr
        with py7zr.SevenZipFile(path) as z:
            return [i.filename for i in z.list() if not i.is_directory]
    if kind == "rar":
        import rarfile
        with rarfile.RarFile(path) as z:
            return [i.filename for i in z.infolist() if not i.is_dir()]
    raise ComicError(f"{path.name} isn't a comic archive")


def page_names(path: Path) -> list[str]:
    """The page images, in reading order."""
    try:
        names = _names(path, archive_kind(path))
    except ComicError:
        raise
    except Exception as e:  # zipfile, py7zr and rarfile raise their own kinds
        raise ComicError(f"Couldn't read {path.name}: {e}") from e
    return sorted((n for n in names if _is_page(n)), key=natural_key)


def read_member(path: Path, name: str) -> bytes:
    kind = archive_kind(path)
    try:
        if kind == "zip":
            with zipfile.ZipFile(path) as z:
                return z.read(name)
        if kind == "7z":
            import py7zr
            from py7zr.io import BytesIOFactory
            factory = BytesIOFactory(MAX_PAGE_BYTES)
            with py7zr.SevenZipFile(path) as z:
                z.extract(targets=[name], factory=factory)
            product = factory.products[name]
            product.seek(0)
            return product.read()
        if kind == "rar":
            import rarfile
            with rarfile.RarFile(path) as z:
                return z.read(name)
    except Exception as e:
        raise ComicError(f"Couldn't read page {name} of {path.name}: {e}") from e
    raise ComicError(f"{path.name} isn't a comic archive")
