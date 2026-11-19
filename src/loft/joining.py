"""Asking to join: someone without an account asks from the sign-in page, and an admin approves
(which makes them a member) or declines. Off until the admin turns it on in Library settings.
A waiting request keeps only a hash of the password chosen, as accounts do."""

from __future__ import annotations

import sqlite3
import time

from . import auth
from .config import Config
from .db import session
from .libsettings import get_library
from .notifications import admins, notify

MAX_WAITING = 20
MAX_NOTE = 500


def ask(cfg: Config, username: str, password: str, note: str = "") -> None:
    if not get_library(cfg)["join_requests"]:
        raise ValueError("This library isn’t taking new people just now")
    username = auth.check_username(username)
    auth.check_password(password)
    note = " ".join((note or "").split())
    if len(note) > MAX_NOTE:
        raise ValueError(f"The note can be at most {MAX_NOTE} characters")
    with session(cfg.db_path) as con:
        if con.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone():
            raise ValueError(f"There’s already an account called {username}")
        if con.execute("SELECT COUNT(*) FROM join_requests").fetchone()[0] >= MAX_WAITING:
            raise ValueError("There are too many people waiting already; try again later")
        try:
            con.execute("INSERT INTO join_requests(username, password_hash, note, created_at) VALUES (?, ?, ?, ?)",
                        (username, auth.hash_password(password), note, time.time()))
        except sqlite3.IntegrityError as e:
            raise ValueError(f"{username} has already asked to join") from e
        notify(con, admins(con), "join", f"{username} asked to join", "#/admin")


def waiting(cfg: Config) -> list[dict]:
    with session(cfg.db_path) as con:
        return [{"id": r["id"], "username": r["username"], "note": r["note"], "at": r["created_at"]}
                for r in con.execute("SELECT id, username, note, created_at FROM join_requests ORDER BY id")]


def approve(cfg: Config, request_id: int) -> auth.User:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM join_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise LookupError(request_id)
        try:
            uid = con.execute("INSERT INTO users(username, password_hash, admin, created_at) VALUES (?, ?, 0, ?)",
                              (row["username"], row["password_hash"], time.time())).lastrowid
        except sqlite3.IntegrityError as e:
            raise ValueError(f"There’s already an account called {row['username']}") from e
        con.execute("DELETE FROM join_requests WHERE id = ?", (request_id,))
    return auth.get_user(cfg, uid)


def decline(cfg: Config, request_id: int) -> None:
    with session(cfg.db_path) as con:
        if not con.execute("DELETE FROM join_requests WHERE id = ?", (request_id,)).rowcount:
            raise LookupError(request_id)
