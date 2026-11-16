"""The web server: the JSON API under /api and the web app for everything else."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, library
from .auth import User, admin_user, current_user
from .config import Config
from .covers import cover_path
from .db import session
from .scanner import Scanner

WEB_DIR = Path(__file__).parent / "web"


class Credentials(BaseModel):
    username: str = ""
    password: str = ""


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

    # ---------- signing in ----------

    @app.get("/api/status")
    def status():
        return {"setup_needed": not auth.has_users(cfg)}

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
        auth.delete_user(cfg, user_id)
        return {"ok": True}

    @app.post("/api/scan", status_code=202)
    def start_scan(_: User = Depends(admin_user)):
        scanner.start()
        scanner.trigger()
        return {"ok": True}

    @app.get("/api/scan")
    def scan_status(_: User = Depends(admin_user)):
        return {"running": scanner.running, "last": scanner.last.json() if scanner.last else None}

    # ---------- the library ----------

    @app.get("/api/home")
    def home(user: User = Depends(current_user)):
        return library.home(cfg, user)

    @app.get("/api/books")
    def books(kind: str | None = None, value: str | None = None, sort: str = "title", offset: int = 0,
              limit: int = 60, _: User = Depends(current_user)):
        try:
            return library.list_books(cfg, kind=kind, value=value, sort=sort, offset=max(0, offset),
                                      limit=min(max(1, limit), 200))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/books/{book_id}")
    def book(book_id: int, _: User = Depends(current_user)):
        b = library.get_book(cfg, book_id)
        if b is None:
            raise HTTPException(404, "No such book")
        return b

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

    # ---------- the web app ----------

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
