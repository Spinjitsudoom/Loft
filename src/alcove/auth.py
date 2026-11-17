"""Accounts: people who can sign in, their passwords, and the signed session they get.

Admins run the library (members, scans; later approving books). Members read and take part.

A session is a signed token carrying the user's id and their "session version". Changing a
password or removing an account bumps or drops it, which signs that person out everywhere.
The token travels as a cookie (the web app) or an `Authorization: Bearer` header (the apps).

Adapted from Shelf's auth.py.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, TimestampSigner

from .config import Config
from .db import session

COOKIE = "alcove_session"
MAX_AGE = 60 * 60 * 24 * 365
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")
MIN_PASSWORD = 6
LOCK_AFTER = 8  # wrong passwords from one address...
LOCK_WINDOW = 15 * 60  # ...within this many seconds lock it out for the rest of the window


@dataclass(frozen=True)
class User:
    id: int
    username: str
    admin: bool
    version: int

    def json(self) -> dict:
        return {"id": self.id, "username": self.username, "admin": self.admin}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, salt, digest = stored.split("$")
    except ValueError:
        return False
    if kind != "scrypt":
        return False
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(got.hex(), digest)


_DUMMY = hash_password(secrets.token_hex(8))  # so unknown names take as long as wrong passwords
_failures: dict[str, deque[float]] = defaultdict(deque)


def check_username(name: str) -> str:
    name = re.sub(r"\s+", " ", name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError("Use 1–32 letters, numbers, spaces, dots, dashes or underscores, starting with a letter or number")
    return name


def check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Use at least {MIN_PASSWORD} characters for the password")
    if len(password) > 256:
        raise ValueError("That password is too long")


def _user(row) -> User:
    return User(row["id"], row["username"], bool(row["admin"]), row["version"])


def has_users(cfg: Config) -> bool:
    with session(cfg.db_path) as con:
        return con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def create_user(cfg: Config, username: str, password: str, admin: bool = False) -> User:
    username = check_username(username)
    check_password(password)
    with session(cfg.db_path) as con:
        try:
            uid = con.execute("INSERT INTO users(username, password_hash, admin, created_at) VALUES (?, ?, ?, ?)",
                              (username, hash_password(password), int(admin), time.time())).lastrowid
        except sqlite3.IntegrityError as e:
            raise ValueError(f"There’s already an account called {username}") from e
        return _user(con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())


def get_user(cfg: Config, uid: int) -> User | None:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return _user(row) if row else None


def list_users(cfg: Config) -> list[User]:
    with session(cfg.db_path) as con:
        return [_user(r) for r in con.execute("SELECT * FROM users ORDER BY id")]


LAST_ADMIN = "There has to be at least one admin"


def _other_admins(con, user_id: int) -> int:
    return con.execute("SELECT COUNT(*) FROM users WHERE admin = 1 AND id != ?", (user_id,)).fetchone()[0]


def delete_user(cfg: Config, user_id: int) -> None:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and row["admin"] and not _other_admins(con, user_id):
            raise ValueError(LAST_ADMIN)
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))


def set_admin(cfg: Config, user_id: int, admin: bool) -> User:
    """Make someone an admin or a member. Takes effect on their next request (the flag is read each
    time), so they stay signed in either way."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise LookupError(user_id)
        if row["admin"] and not admin and not _other_admins(con, user_id):
            raise ValueError(LAST_ADMIN)
        con.execute("UPDATE users SET admin = ? WHERE id = ?", (int(admin), user_id))
    return get_user(cfg, user_id)


def set_password(cfg: Config, user_id: int, password: str) -> None:
    """New password; signs the person out on every device."""
    check_password(password)
    with session(cfg.db_path) as con:
        con.execute("UPDATE users SET password_hash = ?, version = version + 1 WHERE id = ?",
                    (hash_password(password), user_id))


def change_password(cfg: Config, user_id: int, current: str, new: str) -> User:
    """Change your own password. Signs you out on every other device; returns you with the new
    session version so this device can be signed back in."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not verify_password(current or "", row["password_hash"]):
        raise ValueError("Your current password isn't right")
    set_password(cfg, user_id, new)
    return get_user(cfg, user_id)


def sign_out_everywhere(cfg: Config, user_id: int) -> User:
    with session(cfg.db_path) as con:
        con.execute("UPDATE users SET version = version + 1 WHERE id = ?", (user_id,))
    return get_user(cfg, user_id)


def _locked_out(ip: str) -> bool:
    window = _failures[ip]
    cutoff = time.time() - LOCK_WINDOW
    while window and window[0] < cutoff:
        window.popleft()
    return len(window) >= LOCK_AFTER


def authenticate(cfg: Config, username: str, password: str, ip: str) -> User | None:
    if _locked_out(ip):
        return None
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", ((username or "").strip(),)).fetchone()
    ok = verify_password(password or "", row["password_hash"] if row else _DUMMY)
    if ok and row:
        _failures.pop(ip, None)
        return _user(row)
    _failures[ip].append(time.time())
    return None


def _signer(cfg: Config) -> TimestampSigner:
    return TimestampSigner(cfg.secret_key, salt="alcove-session")


def make_token(cfg: Config, user: User) -> str:
    return _signer(cfg).sign(f"{user.id}.{user.version}".encode()).decode()


def user_from_token(cfg: Config, token: str | None) -> User | None:
    if not token:
        return None
    try:
        uid, ver = (int(x) for x in _signer(cfg).unsign(token, max_age=MAX_AGE).decode().split("."))
    except (BadSignature, ValueError):
        return None
    user = get_user(cfg, uid)
    return user if user and user.version == ver else None


def token_from(request: Request) -> str | None:
    """The session token from an `Authorization: Bearer` header, else the cookie."""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(COOKIE)


def current_user(request: Request) -> User:
    user = user_from_token(request.app.state.cfg, token_from(request))
    if user is None:
        raise HTTPException(401, "Please sign in")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.admin:
        raise HTTPException(403, "Only an admin can do that")
    return user
