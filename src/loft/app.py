"""The web server: the JSON API under /api and the web app for everything else."""

from __future__ import annotations

import sqlite3
import threading
import time
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

from . import auth, browse, check, discussion, editing, flowbooks, joining, libsettings, library, lookups, notifications, openlibrary, book_requests, submissions, pages, reading, settings, shelves, txt, uploads
from .auth import User, admin_user, current_user
from .config import Config
from .covers import cover_path
from .db import session
from .sanitize import chapter_html
from . import autofill, backups, updates
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


class CheckItem(BaseModel):
    kind: str = ""
    key: str = ""


class MergeIn(BaseModel):
    other: int


class ShelfName(BaseModel):
    name: str = ""


class SaveUpload(BaseModel):
    details: dict = {}
    cover_url: str | None = None
    right_to_left: bool = False


class CoverUrl(BaseModel):
    url: str = ""


class MessageIn(BaseModel):
    body: str = ""
    parent_id: int | None = None


class RequestIn(BaseModel):
    title: str = ""
    author: str = ""
    note: str = ""


class VoteIn(BaseModel):
    on: bool = True


class FulfilIn(BaseModel):
    book_id: int


class ReasonIn(BaseModel):
    reason: str = ""


class JoinIn(BaseModel):
    username: str
    password: str
    note: str = ""


class LayoutIn(BaseModel):
    split: bool | None = None
    wraparound: bool | None = None
    rtl: bool | None = None  # None leaves it as it was


class ArrangementIn(BaseModel):
    order: list[list] | None = None  # every page as [source page, half]; None puts the file's order back
    hidden: list[list] = []


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


def _signed_in(cfg: Config, request: Request, response: Response, user: User) -> dict:
    token = auth.make_token(cfg, user)
    # Over https (tailscale serve, a proxy) the cookie is marked so it's never sent over plain http.
    response.set_cookie(auth.COOKIE, token, max_age=auth.MAX_AGE, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return {**user.json(), "token": token}


def create_app(cfg: Config, scan_on_start: bool = True) -> FastAPI:
    scanner = Scanner(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if scan_on_start:
            scanner.start()
            updater.start()
            backups.BackupKeeper(cfg).start()
        yield

    updater = updates.UpdateChecker(cfg)
    app = FastAPI(title="Loft", lifespan=lifespan, docs_url=None, redoc_url=None)
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

    @app.get("/api/ping")
    def ping(response: Response):
        """Says this is a Loft server: the Android app asks before saving an address. Anyone may ask
        (from the app's own start page, a different origin), and it says nothing about the library."""
        from importlib.metadata import PackageNotFoundError, version
        try:
            v = version("loft")
        except PackageNotFoundError:
            v = "dev"
        response.headers["Access-Control-Allow-Origin"] = "*"
        return {"app": "loft", "version": v}

    @app.get("/api/status")
    def status():
        lib = libsettings.get_library(cfg)
        return {"setup_needed": not auth.has_users(cfg), "name": lib["name"], "join_requests": lib["join_requests"],
                "version": updates.current_version()}

    @app.post("/api/setup")
    def setup(body: Credentials, request: Request, response: Response):
        if auth.has_users(cfg):
            raise HTTPException(409, "This library already has an admin")
        try:
            user = auth.create_user(cfg, body.username, body.password, admin=True)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _signed_in(cfg, request, response, user)

    @app.post("/api/login")
    def login(body: Credentials, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        user = auth.authenticate(cfg, body.username, body.password, ip)
        if user is None:
            raise HTTPException(401, "That name and password don’t match (or there were too many tries; wait 15 minutes)")
        return _signed_in(cfg, request, response, user)

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(auth.COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return user.json()

    @app.post("/api/me/password")
    def change_password(body: PasswordChange, request: Request, response: Response, user: User = Depends(current_user)):
        try:
            updated = auth.change_password(cfg, user.id, body.current, body.new)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _signed_in(cfg, request, response, updated)

    @app.post("/api/me/signout-everywhere")
    def signout_everywhere(request: Request, response: Response, user: User = Depends(current_user)):
        return _signed_in(cfg, request, response, auth.sign_out_everywhere(cfg, user.id))

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

    # ---------- asking to join, and notifications ----------

    asked: dict[str, list[float]] = {}

    @app.post("/api/join")
    def join(body: JoinIn, request: Request):
        ip = request.client.host if request.client else ""
        recent = [t for t in asked.get(ip, []) if t > time.time() - 3600]
        if len(recent) >= 5:
            raise HTTPException(429, "Too many requests from here; try again in an hour")
        asked[ip] = recent + [time.time()]
        try:
            joining.ask(cfg, body.username, body.password, body.note)
        except ValueError as e:
            raise HTTPException(403 if "isn’t taking" in str(e) else 400, str(e))
        return {"ok": True}

    @app.get("/api/join-requests")
    def join_requests(_: User = Depends(admin_user)):
        return joining.waiting(cfg)

    @app.post("/api/join-requests/{request_id}/approve")
    def approve_join(request_id: int, _: User = Depends(admin_user)):
        try:
            return joining.approve(cfg, request_id).json()
        except LookupError:
            raise HTTPException(404, "No such request")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/join-requests/{request_id}")
    def decline_join(request_id: int, _: User = Depends(admin_user)):
        try:
            joining.decline(cfg, request_id)
        except LookupError:
            raise HTTPException(404, "No such request")
        return {"ok": True}

    @app.get("/api/notifications")
    def my_notifications(user: User = Depends(current_user)):
        return notifications.list_for(cfg, user.id)

    @app.post("/api/notifications/read")
    def read_notifications(user: User = Depends(current_user)):
        notifications.mark_read(cfg, user.id)
        return {"ok": True}

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

    # ---------- updates ----------

    @app.get("/api/updates")
    def update_status(_: User = Depends(admin_user)):
        return updates.status(cfg)

    @app.post("/api/updates/check")
    def check_updates(_: User = Depends(admin_user)):
        """Ask now. Downloading (when there's something to download) carries on in the background."""
        found = updates.check(cfg, download=False)
        if found["newer"] and found["can_install"] and not found["ready"]:
            threading.Thread(target=updates.check, args=(cfg,), name="loft-update-download", daemon=True).start()
            found = {**found, "downloading": True}
        return found

    # ---------- backups ----------

    @app.get("/api/backups")
    def backup_status(_: User = Depends(admin_user)):
        return backups.status(cfg)

    @app.post("/api/backups")
    def back_up_now(_: User = Depends(admin_user)):
        try:
            made = backups.make_now(cfg)
        except (OSError, sqlite3.Error):
            raise HTTPException(500, backups.status(cfg)["error"] or "Loft couldn’t back up the library")
        return {"name": made.name, **backups.status(cfg)}

    @app.get("/api/backups/{name}")
    def download_backup(name: str, _: User = Depends(admin_user)):
        try:
            p = backups.path_of(cfg, name)
        except backups.BackupError:
            raise HTTPException(404, "No such backup")
        return FileResponse(p, media_type="application/zip", filename=name)

    @app.post("/api/backups/{name}/restore")
    def restore_backup(name: str, _: User = Depends(admin_user)):
        """Put the library back as it was. What's there now is backed up first, so this can be undone."""
        try:
            safety = backups.restore(cfg, name)
        except backups.BackupError as e:
            raise HTTPException(400, str(e))
        scanner.trigger()   # the books may have changed since the backup
        return {"before": safety.name, **backups.status(cfg)}

    @app.post("/api/updates/install", status_code=202)
    def install_update(_: User = Depends(admin_user)):
        try:
            return {"version": updates.install(cfg)}
        except LookupError as e:
            raise HTTPException(409, str(e))

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
    def lookup(title: str = "", author: str = "", isbn: str = "", comic: bool = False, lang: str = "",
               _: User = Depends(current_user)):
        return _lookup(lookups.search, title=title, author=author, isbn=isbn, comic=comic, lang=lang[:20])

    @app.get("/api/lookup/description")
    def lookup_description(key: str = "", _: User = Depends(current_user)):
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
    async def upload(request: Request, name: str = "", user: User = Depends(current_user)):
        """Admins add books; members send them for approval (submissions). Either way a draft first."""
        try:
            token, path = await run_in_threadpool(uploads.new_draft, cfg, name, user.id, not user.admin)
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
    def upload_cover(token: str, user: User = Depends(current_user)):
        path = _draft_call(uploads.draft_cover, token, user=user)
        if path is None:
            raise HTTPException(404, "No cover")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/uploads/{token}/save")
    def save_upload(token: str, body: SaveUpload, user: User = Depends(admin_user)):
        _draft_call(uploads.draft_cover, token, user=user)  # theirs to save
        try:
            return {"book_id": _draft_call(uploads.save, token, body.details, cover_url=body.cover_url or None,
                                             right_to_left=body.right_to_left)}
        except openlibrary.LookupFailed as e:
            raise HTTPException(502, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/uploads/{token}/submit")
    def submit_upload(token: str, body: SaveUpload, user: User = Depends(current_user)):
        try:
            return {"id": _draft_call(submissions.submit, user, token, body.details,
                                      cover_url=body.cover_url or None, right_to_left=body.right_to_left)}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/uploads/{token}")
    def discard_upload(token: str, user: User = Depends(current_user)):
        try:
            _draft_call(uploads.discard, token, user=user)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    # ---------- submissions: members' books waiting for an admin ----------

    def _submission_call(call, *args, **kwargs):
        try:
            return call(cfg, *args, **kwargs)
        except LookupError:
            raise HTTPException(404, "No such submission")
        except openlibrary.LookupFailed as e:
            raise HTTPException(502, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/submissions/mine")
    def my_submissions(user: User = Depends(current_user)):
        return submissions.mine(cfg, user.id)

    @app.get("/api/submissions")
    def waiting_submissions(_: User = Depends(admin_user)):
        return submissions.waiting(cfg)

    @app.post("/api/submissions/{sub_id}/approve")
    def approve_submission(sub_id: int, body: SaveUpload, _: User = Depends(admin_user)):
        return {"book_id": _submission_call(submissions.approve, sub_id, body.details or None,
                                            cover_url=body.cover_url, right_to_left=body.right_to_left)}

    @app.post("/api/submissions/{sub_id}/decline")
    def decline_submission(sub_id: int, body: ReasonIn, _: User = Depends(admin_user)):
        _submission_call(submissions.decline, sub_id, body.reason)
        return {"ok": True}

    @app.delete("/api/submissions/{sub_id}")
    def withdraw_submission(sub_id: int, user: User = Depends(current_user)):
        _submission_call(submissions.withdraw, user, sub_id)
        return {"ok": True}

    # ---------- requests: books people would like ----------

    def _request_call(call, *args, **kwargs):
        try:
            return call(cfg, *args, **kwargs)
        except LookupError:
            raise HTTPException(404, "No such request")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/requests")
    def list_requests(closed: bool = False, user: User = Depends(current_user)):
        return book_requests.listing(cfg, user.id, closed)

    @app.post("/api/requests")
    def ask_for_book(body: RequestIn, user: User = Depends(current_user)):
        return {"id": _request_call(book_requests.ask, user, body.title, body.author, body.note)}

    @app.post("/api/requests/{rid}/vote")
    def vote_request(rid: int, body: VoteIn, user: User = Depends(current_user)):
        _request_call(book_requests.vote, user.id, rid, body.on)
        return {"ok": True}

    @app.delete("/api/requests/{rid}")
    def remove_request(rid: int, user: User = Depends(current_user)):
        _request_call(book_requests.remove, user, rid)
        return {"ok": True}

    @app.post("/api/requests/{rid}/fulfil")
    def fulfil_request(rid: int, body: FulfilIn, _: User = Depends(admin_user)):
        _request_call(book_requests.fulfil, rid, body.book_id)
        return {"ok": True}

    @app.post("/api/requests/{rid}/decline")
    def decline_request(rid: int, body: ReasonIn, _: User = Depends(admin_user)):
        _request_call(book_requests.decline, rid, body.reason)
        return {"ok": True}

    # ---------- the stacks ----------

    @app.get("/api/stacks")
    def the_stacks(by: str = "series", status: str = "", section: str = "", author: str = "", format: str = "",
                   user: User = Depends(current_user)):
        try:
            return browse.stacks(cfg, user, by, status or None, section or None, author or None, format or None)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/sections")
    def library_sections(_: User = Depends(admin_user)):
        return browse.sections_report(cfg)

    # ---------- discussion about each book ----------

    def _talk_call(call, *args, **kwargs):
        try:
            return call(cfg, *args, **kwargs)
        except LookupError:
            raise HTTPException(404, "No such message or book")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/books/{book_id}/discussion")
    def book_discussion(book_id: int, after: int = 0, user: User = Depends(current_user)):
        return _talk_call(discussion.thread, user, book_id, after)

    @app.post("/api/books/{book_id}/discussion")
    def post_message(book_id: int, body: MessageIn, user: User = Depends(current_user)):
        return _talk_call(discussion.post, user, book_id, body.body, body.parent_id)

    @app.patch("/api/messages/{mid}")
    def edit_message(mid: int, body: MessageIn, user: User = Depends(current_user)):
        return _talk_call(discussion.edit, user, mid, body.body)

    @app.delete("/api/messages/{mid}")
    def remove_message(mid: int, user: User = Depends(current_user)):
        _talk_call(discussion.remove, user, mid)
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

    # ---------- new books filled in by themselves ----------

    @app.get("/api/autofill")
    def autofilled(_: User = Depends(admin_user)):
        return {**autofill.overview(cfg), "running": scanner.filler.running}

    @app.post("/api/autofill/{book_id}/undo")
    def undo_autofill(book_id: int, _: User = Depends(admin_user)):
        try:
            autofill.undo(cfg, book_id)
        except LookupError:
            raise HTTPException(404, "Nothing to undo for that book")
        return {"ok": True}

    @app.post("/api/autofill/rest", status_code=202)
    def autofill_the_rest(_: User = Depends(admin_user)):
        queued = autofill.look_up_the_rest(cfg)
        if queued and scan_on_start:
            scanner.filler.trigger()
        return {"queued": queued}

    # ---------- the library check ----------

    @app.get("/api/check")
    def library_check(_: User = Depends(admin_user)):
        return check.problems(cfg)

    @app.get("/api/check/ignored")
    def ignored(_: User = Depends(admin_user)):
        return check.list_ignored(cfg)

    @app.post("/api/check/ignored")
    def ignore(body: CheckItem, _: User = Depends(admin_user)):
        try:
            check.ignore(cfg, body.kind, body.key)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.delete("/api/check/ignored")
    def unignore(body: CheckItem, _: User = Depends(admin_user)):
        try:
            check.unignore(cfg, body.kind, body.key)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/books/{book_id}/merge")
    def merge(book_id: int, body: MergeIn, user: User = Depends(admin_user)):
        try:
            library.merge_books(cfg, book_id, body.other)
        except LookupError:
            raise HTTPException(404, "No such book")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _edited(book_id, user)

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
            return pages.set_layout(cfg, file_id, body.split, body.wraparound, body.rtl)
        except LookupError:
            raise HTTPException(404, "No such file")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.patch("/api/files/{file_id}/arrangement")
    def file_arrangement(file_id: int, body: ArrangementIn, _: User = Depends(admin_user)):
        try:
            return pages.set_arrangement(cfg, file_id, body.order, body.hidden)
        except LookupError:
            raise HTTPException(404, "No such file")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/files/{file_id}/piece")
    def file_piece(file_id: int, src: int, half: int | None = None, w: int = 200, _: User = Depends(admin_user)):
        """A page (or half of one) of the file, hidden or not, by where it is in the file: for arranging."""
        _manifest(file_id)
        try:
            path = pages.render_piece(cfg, file_id, src, half, min(max(w, 200), 2400))
        except IndexError:
            raise HTTPException(404, "No such page")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=604800"})

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
