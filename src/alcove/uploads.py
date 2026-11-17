"""Adding books: a file is uploaded into a draft, its details are read for the admin to review,
then it's saved into a books folder as Author/Title/file and is in the library at once.

Drafts live in the data dir (never in a books folder) until they're saved or discarded; ones left
for two days are cleared away, except members' submissions waiting for an admin. Saving never
overwrites a file: a name that's taken gets " (2)".

Each draft belongs to whoever uploaded it. Only they can see or change it; an admin also can once a
member has sent it for approval (submissions.py).
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from collections.abc import Iterable
from pathlib import Path

from .config import Config
from .covers import extract_cover
from .db import session
from .editing import FIELDS, clean_details
from .filemeta import read_file_meta, title_from_filename
from .formats import format_of
from .libsettings import allow_txt, get_library
from . import pages

MAX_UPLOAD = 2 * 1024**3
DRAFT_DAYS = 2
TOKEN = re.compile(r"^[A-Za-z0-9_-]{22}$")
MAX_NAME = 80
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)
UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')


def _folder(cfg: Config) -> Path:
    return cfg.data_dir / "uploads"


def _draft(cfg: Config, token: str, user=None) -> Path:
    """The draft's folder. With `user`, only if they may see it (LookupError otherwise, as if it
    weren't there: a member never learns another's draft exists)."""
    if not isinstance(token, str) or not TOKEN.match(token):
        raise LookupError(token)
    folder = _folder(cfg) / token
    if not (folder / "draft.json").is_file():
        raise LookupError(token)
    if user is not None:
        info = json.loads((folder / "draft.json").read_text())
        owner = info.get("owner")
        if not (owner == user.id or (user.admin and (owner is None or info.get("submitted")))):
            raise LookupError(token)
    return folder


def mark_submitted(cfg: Config, token: str) -> None:
    folder = _draft(cfg, token)
    info = json.loads((folder / "draft.json").read_text())
    (folder / "draft.json").write_text(json.dumps({**info, "submitted": True}))


def draft_info(cfg: Config, token: str) -> dict:
    return json.loads((_draft(cfg, token) / "draft.json").read_text())


def safe_name(text: str, fallback: str) -> str:
    """A file or folder name that works on Windows, macOS and Linux and can't climb out of its folder."""
    name = " ".join(UNSAFE.sub(lambda m: " " if m.group() in "\t\n\r" else "", text or "").split())
    name = name.strip(". ")[:MAX_NAME].strip(". ")
    if not name:
        return fallback
    match = RESERVED.match(name)
    if match:
        name = match.group(1) + "_" + (match.group(2) or "")
    return name


def check_name(cfg: Config, filename: str) -> str:
    """The format of an upload, or ValueError if Alcove can't read that kind of file."""
    name = Path((filename or "").replace("\\", "/")).name
    fmt = format_of(Path(name), allow_txt=allow_txt(cfg))
    if not fmt:
        suffix = Path(name).suffix.lower() or "these"
        raise ValueError(f"Alcove can’t read {suffix} files" if suffix != "these" else "Alcove can’t tell what kind of book that is")
    return fmt


def new_draft(cfg: Config, filename: str, owner: int | None = None) -> tuple[str, Path]:
    """A fresh draft folder for an upload; returns its token and where to write the file."""
    fmt = check_name(cfg, filename)
    token = secrets.token_urlsafe(16)
    folder = _folder(cfg) / token
    folder.mkdir(parents=True)
    original = Path((filename or "").replace("\\", "/")).name
    (folder / "draft.json").write_text(json.dumps({"filename": original, "format": fmt, "created": time.time(),
                                                   "owner": owner}))
    return token, folder / f"book.{fmt}"


def discard(cfg: Config, token: str, user=None) -> None:
    folder = _draft(cfg, token, user)
    if user is not None and not user.admin and json.loads((folder / "draft.json").read_text()).get("submitted"):
        raise ValueError("That’s been sent for approval; take the submission back instead")
    shutil.rmtree(folder, ignore_errors=True)


def _same_as(cfg: Config, title: str, authors: list[str]) -> list[dict]:
    from .library import book_card
    if not title:
        return []
    with session(cfg.db_path) as con:
        rows = con.execute("SELECT * FROM books WHERE title = ? COLLATE NOCASE", (title,)).fetchall()
    first = (authors[0] if authors else "").casefold()
    return [book_card(r) for r in rows if (json.loads(r["authors"] or "[]") or [""])[0].casefold() == first]


def read_draft(cfg: Config, token: str, user=None) -> dict:
    """Read an uploaded file's details and cover, for whoever uploaded it to review."""
    folder = _draft(cfg, token, user)
    info = json.loads((folder / "draft.json").read_text())
    path = folder / f"book.{info['format']}"
    meta = read_file_meta(path, info["format"])
    if not (folder / "cover.jpg").exists():
        image = extract_cover(path, info["format"])
        if image:
            (folder / "cover.jpg").write_bytes(image)
    title = title_from_filename(Path(info["filename"])) if meta.title_from_name else meta.title
    details = {"title": title, "authors": meta.authors, "series": meta.series, "series_index": meta.series_index,
               "description": meta.description, "publisher": meta.publisher, "published": meta.published,
               "language": meta.language, "tags": []}
    return {"token": token, "filename": info["filename"], "format": info["format"], "size": path.stat().st_size,
            "details": details, "isbn": meta.isbn, "has_cover": (folder / "cover.jpg").is_file(),
            "has_pages": info["format"] in pages.READABLE,  # shown page by page, so it can read right to left
            "same_as": _same_as(cfg, meta.title, meta.authors)}


def start(cfg: Config, filename: str, chunks: Iterable[bytes], owner: int | None = None) -> dict:
    token, path = new_draft(cfg, filename, owner)
    try:
        size = 0
        with path.open("wb") as f:
            for chunk in chunks:
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise ValueError("That file is too big (the most is 2 GB)")
                f.write(chunk)
        if size == 0:
            raise ValueError("That file is empty")
        return read_draft(cfg, token)
    except BaseException:
        shutil.rmtree(path.parent, ignore_errors=True)
        raise


def draft_cover(cfg: Config, token: str, user=None) -> Path | None:
    cover = _draft(cfg, token, user) / "cover.jpg"
    return cover if cover.is_file() else None


def prune_drafts(cfg: Config, max_age: float = DRAFT_DAYS * 86400) -> None:
    folder = _folder(cfg)
    if not folder.is_dir():
        return
    cutoff = time.time() - max_age
    for draft in folder.iterdir():
        try:
            if draft.is_dir() and draft.stat().st_mtime < cutoff:
                info = json.loads((draft / "draft.json").read_text()) if (draft / "draft.json").is_file() else {}
                if not info.get("submitted"):  # a member's book waiting for an admin stays
                    shutil.rmtree(draft, ignore_errors=True)
        except (OSError, ValueError):
            pass


def _destination(upload_dir: Path, details: dict, original: str, fmt: str) -> Path:
    stem = safe_name(Path(original).stem, "book")
    folder = upload_dir / safe_name(details["authors"][0], "Unknown author") / safe_name(details["title"], "Untitled")
    if not folder.resolve().is_relative_to(upload_dir.resolve()):
        raise ValueError("That title or author can’t be used as a folder name")
    return folder / f"{stem}.{fmt}"


def _copy_new(source: Path, target: Path) -> Path:
    """Copy to target, or to "target (2)" and so on if it's taken; never overwrites."""
    n = 1
    while True:
        candidate = target if n == 1 else target.with_name(f"{target.stem} ({n}){target.suffix}")
        try:
            with source.open("rb") as src, candidate.open("xb") as dst:
                try:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                except BaseException:
                    dst.close()
                    candidate.unlink(missing_ok=True)
                    raise
            return candidate
        except FileExistsError:
            n += 1


def save(cfg: Config, token: str, details: dict, *, cover_url: str | None = None,
         right_to_left: bool = False, approving: bool = False) -> int:
    """Save a reviewed upload into the books folder and the library. Returns the new book's id.
    right_to_left marks a manga, whose pages turn the other way."""
    from .openlibrary import LookupFailed, fetch_cover
    from .scanner import _Found, _scan_lock, _set_cover, _upsert_file, _write_book

    folder = _draft(cfg, token)
    if not approving and json.loads((folder / "draft.json").read_text()).get("submitted"):
        raise ValueError("That was sent for approval; approve or decline it in Approvals")
    clean = clean_details({k: details.get(k) for k in FIELDS if k in details}, require=True)
    full = {"title": "", "authors": [], "series": "", "series_index": None, "description": "", "publisher": "",
            "published": "", "language": "", "tags": [], **clean}
    if not full["series"]:
        full["series_index"] = None
    info = json.loads((folder / "draft.json").read_text())
    source = folder / f"book.{info['format']}"
    image = None
    if cover_url:
        try:
            image = fetch_cover(cfg, cover_url)
        except LookupFailed:
            image = None  # Open Library didn't send it: the file's own cover will do
    if image is None and (folder / "cover.jpg").is_file():
        image = (folder / "cover.jpg").read_bytes()

    upload_dir = Path(get_library(cfg)["upload_dir"] or "")
    if not str(upload_dir) or not upload_dir.is_dir():
        raise ValueError(f"Alcove can’t find the folder uploads go into ({upload_dir}). Check Library settings.")
    # While a scan runs it mustn't meet this file half-copied, or before the book that owns it exists.
    with _scan_lock:
        target = _destination(upload_dir, full, info["filename"], info["format"])
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            saved = _copy_new(source, target)
        except OSError as e:
            raise ValueError(f"Alcove can’t save into {upload_dir}: {e.strerror or e}. "
                             "Check that the folder can be written to.") from e

        st = saved.stat()
        try:
            with session(cfg.db_path) as con:
                book_id = _write_book(con, None, title=full["title"], authors=full["authors"], author_sort="",
                                      series=full["series"], series_index=full["series_index"],
                                      description=full["description"], publisher=full["publisher"],
                                      published=full["published"], language=full["language"], tags=full["tags"],
                                      calibre_id=None, added_at=time.time(), locked=list(FIELDS))
                _set_cover(cfg, con, book_id, image)
                _upsert_file(con, book_id, saved, _Found(info["format"], st.st_size, st.st_mtime), upload_dir)
                if right_to_left and info["format"] in pages.READABLE:
                    con.execute("UPDATE book_files SET layout = ? WHERE path = ?",
                                (json.dumps({"split": None, "wraparound": None, "rtl": True}), str(saved)))
        except BaseException:
            saved.unlink(missing_ok=True)
            raise
    shutil.rmtree(folder, ignore_errors=True)
    return book_id
