"""The web server: the JSON API under /api and the web app for everything else."""

from __future__ import annotations

import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from . import auth, editing, flowbooks, libsettings, library, openlibrary, pages, reading, settings, shelves, txt, uploads
from .auth import User, admin_user, current_user
from .config import Config
from .covers import cover_path
from .db import session
from .sanitize import chapter_html
from .scanner import Scanner, last_report

WEB_DIR = Path(__file__).parent / "web"


class WebFiles(StaticFiles):
    """The web app's own files. Browsers may keep them but must check for a newer version each time
    (a quick "not modified" when nothing changed), so an update never leaves anyone on stale code."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


class Credentials(BaseModel):
    username: str = ""
    password: str = ""


class PasswordChange(BaseModel):
    current: str = ""
    new: str = ""


class AdminFlag(BaseModel):
    admin: bool


class NewPassword(BaseModel):
    password: str = ""


class ShelfName(BaseModel):
    name: str = ""


class SaveUpload(BaseModel):
    details: dict = {}
    cover_url: str | None = None


class CoverUrl(BaseModel):
    url: str = ""


class LayoutIn(BaseModel):
    split: bool | None = None
    wraparound: bool | None = None


class ProgressIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    file_id: int
    page: int
    pages: int
    at: float | None = None
    locator: dict | None = None


class BookmarkIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    file_id: int
    page: int
    note: str = ""
    locator: dict | None = None


UNREADABLE = {
    "format": "This kind of book can’t be read here yet; download it instead.",
    "protected": "This book is protected and can’t be opened here.",
    "damaged": "This file is damaged and can’t be opened.",
}


def _signed_in(cfg: Config, response: Response, user: User) -> dict:
    token = auth.make_token(cfg, user)
    response.set_cookie(auth.COOKIE, token, max_age=auth.MAX_AGE, httponly=True, samesite="lax")
    return {**user.json(), "token": token}


def create_app(cfg: Config, scan_on_start: bool = True) -> FastAPI:
    scanner = Scanner(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if scan_on_start:
            scanner.start()
        yield

    app = FastAPI(title="Alcove", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.cfg = cfg
    app.state.scanner = scanner

    @app.exception_handler(RequestValidationError)
    def invalid_request(request: Request, e: RequestValidationError):
        # Name the fields, but never echo the values back (they may not even be valid JSON, like infinity).
        fields = sorted({".".join(str(p) for p in err.get("loc", ())[1:]) or "body" for err in e.errors()})
        return JSONResponse({"detail": f"Some of what was sent isn’t valid: {', '.join(fields)}"}, status_code=422)

    @app.exception_handler(pages.Unreadable)
    def unreadable(request: Request, e: pages.Unreadable):
        return JSONResponse({"detail": UNREADABLE[e.kind], "reason": e.kind}, status_code=415)

    # ---------- signing in ----------

    @app.get("/api/status")
    def status():
        return {"setup_needed": not auth.has_users(cfg), "name": libsettings.get_library(cfg)["name"]}

    @app.post("/api/setup")
    def setup(body: Credentials, response: Response):
        if auth.has_users(cfg):
            raise HTTPException(409, "This library already has an admin")
        try:
            user = auth.create_user(cfg, body.username, body.password, admin=True)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _signed_in(cfg, response, user)

    @app.post("/api/login")
    def login(body: Credentials, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        user = auth.authenticate(cfg, body.username, body.password, ip)
        if user is None:
            raise HTTPException(401, "That name and password don’t match (or there were too many tries; wait 15 minutes)")
        return _signed_in(cfg, response, user)

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(auth.COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return user.json()

    @app.post("/api/me/password")
    def change_password(body: PasswordChange, response: Response, user: User = Depends(current_user)):
        try:
            updated = auth.change_password(cfg, user.id, body.current, body.new)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _signed_in(cfg, response, updated)

    @app.post("/api/me/signout-everywhere")
    def signout_everywhere(response: Response, user: User = Depends(current_user)):
        return _signed_in(cfg, response, auth.sign_out_everywhere(cfg, user.id))

    @app.get("/api/settings")
    def read_settings(user: User = Depends(current_user)):
        return settings.get_settings(cfg, user.id)

    @app.patch("/api/settings")
    def change_settings(patch: dict = Body(...), user: User = Depends(current_user)):
        try:
            return settings.update_settings(cfg, user.id, patch)
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ---------- admin ----------

    @app.get("/api/users")
    def users(_: User = Depends(admin_user)):
        return [u.json() for u in auth.list_users(cfg)]

    @app.post("/api/users")
    def add_user(body: Credentials, _: User = Depends(admin_user)):
        try:
            return auth.create_user(cfg, body.username, body.password).json()
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/users/{user_id}")
    def remove_user(user_id: int, me: User = Depends(admin_user)):
        if user_id == me.id:
            raise HTTPException(400, "You can’t remove your own account")
        try:
            auth.delete_user(cfg, user_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.patch("/api/users/{user_id}")
    def change_user(user_id: int, body: AdminFlag, _: User = Depends(admin_user)):
        try:
            return auth.set_admin(cfg, user_id, body.admin).json()
        except LookupError:
            raise HTTPException(404, "No such person")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/users/{user_id}/password")
    def reset_password(user_id: int, body: NewPassword, _: User = Depends(admin_user)):
        if auth.get_user(cfg, user_id) is None:
            raise HTTPException(404, "No such person")
        try:
            auth.set_password(cfg, user_id, body.password)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/scan", status_code=202)
    def start_scan(_: User = Depends(admin_user)):
        scanner.start()
        scanner.trigger()
        return {"ok": True}

    @app.get("/api/scan")
    def scan_status(_: User = Depends(admin_user)):
        return {"running": scanner.running, "last": scanner.last.json() if scanner.last else None,
                "report": last_report(cfg)}

    @app.get("/api/library")
    def library_settings(_: User = Depends(admin_user)):
        return libsettings.get_library(cfg)

    @app.patch("/api/library")
    def change_library(patch: dict = Body(...), _: User = Depends(admin_user)):
        try:
            return libsettings.update_library(cfg, patch)
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ---------- the library ----------

    @app.get("/api/home")
    def home(user: User = Depends(current_user)):
        return library.home(cfg, user)

    @app.get("/api/books")
    def books(kind: str | None = None, value: str | None = None, sort: str = "title", offset: int = 0,
              limit: int = 60, user: User = Depends(current_user)):
        try:
            return library.list_books(cfg, kind=kind, value=value, sort=sort, offset=max(0, offset),
                                      limit=min(max(1, limit), 200), user=user)
        except LookupError:
            raise HTTPException(404, "No such shelf")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/books/{book_id}")
    def book(book_id: int, user: User = Depends(current_user)):
        b = library.get_book(cfg, book_id, user)
        if b is None:
            raise HTTPException(404, "No such book")
        return b

    def _edited(book_id: int, user: User) -> dict:
        b = library.get_book(cfg, book_id, user)
        if b is None:
            raise HTTPException(404, "No such book")
        return b

    @app.patch("/api/books/{book_id}")
    def edit_book(book_id: int, patch: dict = Body(...), user: User = Depends(admin_user)):
        try:
            editing.edit_book(cfg, book_id, patch)
        except LookupError:
            raise HTTPException(404, "No such book")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _edited(book_id, user)

    async def _body(request: Request, limit: int) -> bytes:
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > limit:
                raise HTTPException(413, "That file is too big")
        return bytes(data)

    @app.put("/api/books/{book_id}/cover")
    async def put_cover(book_id: int, request: Request, user: User = Depends(admin_user)):
        image = await _body(request, editing.MAX_COVER_BYTES)
        try:
            await run_in_threadpool(editing.set_cover, cfg, book_id, image)
        except LookupError:
            raise HTTPException(404, "No such book")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return await run_in_threadpool(_edited, book_id, user)

    @app.delete("/api/books/{book_id}/cover")
    def delete_cover(book_id: int, user: User = Depends(admin_user)):
        try:
            editing.clear_cover(cfg, book_id)
        except LookupError:
            raise HTTPException(404, "No such book")
        return _edited(book_id, user)

    def _lookup(call, *args, **kwargs):
        try:
            return call(cfg, *args, **kwargs)
        except openlibrary.LookupsOff as e:
            raise HTTPException(403, str(e))
        except openlibrary.LookupFailed as e:
            raise HTTPException(502, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/lookup")
    def lookup(title: str = "", author: str = "", isbn: str = "", _: User = Depends(admin_user)):
        return _lookup(openlibrary.search, title=title, author=author, isbn=isbn)

    @app.get("/api/lookup/description")
    def lookup_description(key: str = "", _: User = Depends(admin_user)):
        return {"description": _lookup(openlibrary.description, key)}

    @app.post("/api/books/{book_id}/cover/lookup")
    def cover_from_lookup(book_id: int, body: CoverUrl, user: User = Depends(admin_user)):
        _edited(book_id, user)
        image = _lookup(openlibrary.fetch_cover, body.url)
        try:
            editing.set_cover(cfg, book_id, image)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _edited(book_id, user)

    # ---------- adding books ----------

    @app.put("/api/uploads")
    async def upload(request: Request, name: str = "", _: User = Depends(admin_user)):
        try:
            token, path = await run_in_threadpool(uploads.new_draft, cfg, name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        size = 0
        try:
            with path.open("wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > uploads.MAX_UPLOAD:
                        raise HTTPException(413, "That file is too big (the most is 2 GB)")
                    f.write(chunk)
            if size == 0:
                raise HTTPException(400, "That file is empty")
            return await run_in_threadpool(uploads.read_draft, cfg, token)
        except BaseException:
            await run_in_threadpool(uploads.discard, cfg, token)
            raise

    def _draft_call(call, *args, **kwargs):
        try:
            return call(cfg, *args, **kwargs)
        except LookupError:
            raise HTTPException(404, "That upload has gone; add the file again")

    @app.get("/api/uploads/{token}/cover")
    def upload_cover(token: str, _: User = Depends(admin_user)):
        path = _draft_call(uploads.draft_cover, token)
        if path is None:
            raise HTTPException(404, "No cover")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/uploads/{token}/save")
    def save_upload(token: str, body: SaveUpload, _: User = Depends(admin_user)):
        try:
            return {"book_id": _draft_call(uploads.save, token, body.details, cover_url=body.cover_url or None)}
        except openlibrary.LookupFailed as e:
            raise HTTPException(502, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/uploads/{token}")
    def discard_upload(token: str, _: User = Depends(admin_user)):
        _draft_call(uploads.discard, token)
        return {"ok": True}

    # ---------- shelves ----------

    def _shelf_call(call, *args):
        try:
            return call(cfg, *args)
        except LookupError:
            raise HTTPException(404, "No such shelf")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/shelves")
    def list_shelves(user: User = Depends(current_user)):
        return shelves.list_shelves(cfg, user.id)

    @app.post("/api/shelves")
    def create_shelf(body: ShelfName, user: User = Depends(current_user)):
        return _shelf_call(shelves.create, user.id, body.name)

    @app.patch("/api/shelves/{shelf_id}")
    def rename_shelf(shelf_id: int, body: ShelfName, user: User = Depends(current_user)):
        return _shelf_call(shelves.rename, user.id, shelf_id, body.name)

    @app.delete("/api/shelves/{shelf_id}")
    def delete_shelf(shelf_id: int, user: User = Depends(current_user)):
        _shelf_call(shelves.delete, user.id, shelf_id)
        return {"ok": True}

    @app.put("/api/shelves/{shelf_id}/books/{book_id}")
    def shelve(shelf_id: int, book_id: int, user: User = Depends(current_user)):
        _shelf_call(shelves.add, user.id, shelf_id, book_id)
        return {"ok": True}

    @app.delete("/api/shelves/{shelf_id}/books/{book_id}")
    def unshelve(shelf_id: int, book_id: int, user: User = Depends(current_user)):
        _shelf_call(shelves.remove, user.id, shelf_id, book_id)
        return {"ok": True}

    @app.get("/api/search")
    def search(q: str = "", _: User = Depends(current_user)):
        return library.search(cfg, q)

    @app.get("/api/books/{book_id}/cover")
    def cover(book_id: int, w: int = 480, _: User = Depends(current_user)):
        p = cover_path(cfg, book_id, w)
        if p is None:
            raise HTTPException(404, "No cover")
        return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/files/{file_id}")
    def file(file_id: int, _: User = Depends(current_user)):
        with session(cfg.db_path) as con:
            row = con.execute("SELECT path FROM book_files WHERE id = ?", (file_id,)).fetchone()
        if row is None or not Path(row["path"]).is_file():
            raise HTTPException(404, "No such file")
        path = Path(row["path"])
        fallback = path.name.encode("ascii", "replace").decode().replace('"', "'")
        disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(path.name)}"
        return FileResponse(path, headers={"Content-Disposition": disposition})

    # ---------- reading ----------

    def _book_file(book_id: int, file_id: int) -> None:
        with session(cfg.db_path) as con:
            if not con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
                raise HTTPException(404, "No such book")
            if not con.execute("SELECT 1 FROM book_files WHERE id = ? AND book_id = ?", (file_id, book_id)).fetchone():
                raise HTTPException(400, "That file isn’t part of this book")

    def _manifest(file_id: int) -> dict:
        try:
            return pages.manifest(cfg, file_id)
        except LookupError:
            raise HTTPException(404, "No such file")

    @app.get("/api/files/{file_id}/manifest")
    def file_manifest(file_id: int, _: User = Depends(current_user)):
        return _manifest(file_id)

    @app.patch("/api/files/{file_id}/layout")
    def file_layout(file_id: int, body: LayoutIn, _: User = Depends(admin_user)):
        try:
            return pages.set_layout(cfg, file_id, body.split, body.wraparound)
        except LookupError:
            raise HTTPException(404, "No such file")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/files/{file_id}/pages/{index}")
    def file_page(file_id: int, index: int, w: int = 1200, _: User = Depends(current_user)):
        _manifest(file_id)
        try:
            path = pages.render_page(cfg, file_id, index, min(max(w, 600), 2400))
        except IndexError:
            raise HTTPException(404, "No such page")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=604800"})

    def _flow(file_id: int):
        try:
            return flowbooks.open_flow(cfg, file_id)
        except LookupError:
            raise HTTPException(404, "No such file")

    @app.get("/api/files/{file_id}/flow")
    def flow_outline(file_id: int, _: User = Depends(current_user)):
        book, version = _flow(file_id)
        with session(cfg.db_path) as con:
            fmt = con.execute("SELECT format FROM book_files WHERE id = ?", (file_id,)).fetchone()["format"]
        return {"file_id": file_id, "format": fmt, "version": version,
                "chapters": [{"title": c.title} for c in book.chapters],
                "toc": [{"title": t.title, "chapter": t.chapter, "anchor": t.anchor, "level": t.level} for t in book.toc]}

    @app.get("/api/files/{file_id}/chapters/{n}")
    def flow_chapter(file_id: int, n: int, _: User = Depends(current_user)):
        book, version = _flow(file_id)
        if not 0 <= n < len(book.chapters):
            raise HTTPException(404, "No such chapter")
        chapter = book.chapters[n]
        try:
            raw = book.read(chapter.href)
        except (KeyError, OSError, zipfile.BadZipFile):
            raise pages.Unreadable("damaged")
        body = chapter_html(txt.decode(raw), base=chapter.href, book=book,
                            image_size=lambda p: flowbooks.image_size(file_id, version, book, p),
                            resource_url=lambda p: f"/api/files/{file_id}/res/{quote(p)}")
        return Response(body, media_type="text/html; charset=utf-8", headers={
            "Cache-Control": "private, max-age=604800",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"})

    @app.get("/api/files/{file_id}/res/{path:path}")
    def flow_resource(file_id: int, path: str, _: User = Depends(current_user)):
        book, _version = _flow(file_id)
        resource = book.images().get(path)
        if resource is None:
            raise HTTPException(404, "No such picture")
        headers = {"Cache-Control": "private, max-age=604800", "X-Content-Type-Options": "nosniff"}
        if resource.media_type == "image/svg+xml":
            headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        try:
            data = book.read(path)
        except (KeyError, OSError, zipfile.BadZipFile):
            raise pages.Unreadable("damaged")
        return Response(data, media_type=resource.media_type, headers=headers)

    @app.put("/api/books/{book_id}/progress")
    def put_progress(book_id: int, body: ProgressIn, user: User = Depends(current_user)):
        _book_file(book_id, body.file_id)
        try:
            return reading.save_progress(cfg, user.id, book_id, file_id=body.file_id, page=body.page,
                                         pages=body.pages, at=body.at, locator=body.locator)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/books/{book_id}/bookmarks")
    def get_bookmarks(book_id: int, user: User = Depends(current_user)):
        return reading.list_bookmarks(cfg, user.id, book_id)

    @app.post("/api/books/{book_id}/bookmarks")
    def post_bookmark(book_id: int, body: BookmarkIn, user: User = Depends(current_user)):
        _book_file(book_id, body.file_id)
        try:
            return reading.add_bookmark(cfg, user.id, book_id, file_id=body.file_id, page=body.page, note=body.note,
                                        locator=body.locator)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/bookmarks/{bookmark_id}")
    def remove_bookmark(bookmark_id: int, user: User = Depends(current_user)):
        if not reading.delete_bookmark(cfg, user.id, bookmark_id):
            raise HTTPException(404, "No such bookmark")
        return {"ok": True}

    # ---------- the web app ----------

    app.mount("/", WebFiles(directory=WEB_DIR, html=True), name="web")
    return app
