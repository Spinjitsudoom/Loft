"""Settings, read from config.toml with environment variables taking precedence."""

from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Windows keeps app data under %LOCALAPPDATA%; Linux and macOS under ~/.local/share.
DEFAULT_DATA_DIR = (Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Alcove"
                    if os.name == "nt" else Path.home() / ".local" / "share" / "alcove")


@dataclass
class Config:
    # Folders holding your books. Subfolders are scanned. Alcove never changes what's in them.
    books_dirs: list[Path] = field(default_factory=list)
    # Database and covers live here. Keep it on a local disk: SQLite is unreliable on network shares.
    data_dir: Path = DEFAULT_DATA_DIR
    host: str = "0.0.0.0"
    port: int = 4545
    scan_interval_minutes: int = 10
    # How much disk the reader's page images may take up.
    page_cache_mb: int = 2048
    secret_key: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "alcove.db"

    @property
    def cover_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def page_dir(self) -> Path:
        return self.data_dir / "pages"

    @property
    def flow_dir(self) -> Path:
        """Kindle books unpacked for reading."""
        return self.data_dir / "flow"


def _path(value: str) -> Path:
    return Path(value).expanduser()


def load_config(path: Path | None = None) -> Config:
    """Settings from `path`, else the file ALCOVE_CONFIG names, else config.toml here."""
    path = Path(path) if path else Path(os.environ.get("ALCOVE_CONFIG") or "config.toml").expanduser()
    raw: dict = {}
    if path.is_file():
        with path.open("rb") as f:
            raw = tomllib.load(f)

    cfg = Config()
    if "books_dirs" in raw:
        cfg.books_dirs = [_path(p) for p in raw["books_dirs"]]
    if "data_dir" in raw:
        cfg.data_dir = _path(raw["data_dir"])
    for key in ("host", "secret_key"):
        if key in raw:
            setattr(cfg, key, str(raw[key]))
    for key in ("port", "scan_interval_minutes", "page_cache_mb"):
        if key in raw:
            setattr(cfg, key, int(raw[key]))

    env = os.environ
    if env.get("ALCOVE_BOOKS_DIRS"):
        cfg.books_dirs = [_path(p) for p in env["ALCOVE_BOOKS_DIRS"].split(os.pathsep) if p]
    if env.get("ALCOVE_DATA_DIR"):
        cfg.data_dir = _path(env["ALCOVE_DATA_DIR"])
    if env.get("ALCOVE_PORT"):
        cfg.port = int(env["ALCOVE_PORT"])
    if env.get("ALCOVE_HOST"):
        cfg.host = env["ALCOVE_HOST"]

    if not cfg.secret_key:
        cfg.secret_key = _stored_secret(cfg.data_dir)
    return cfg


def _stored_secret(data_dir: Path) -> str:
    """The key that signs sessions: made once, then kept in the data dir so sign-ins survive restarts."""
    f = data_dir / "secret_key"
    if f.is_file() and f.read_text().strip():
        return f.read_text().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    f.write_text(key)
    try:
        f.chmod(0o600)
    except OSError:
        pass
    return key
