"""Each person's settings: how they read and how the library looks to them.

Stored on the server so they follow the person to every device. Only known settings with allowed
values are accepted; anything else is refused with a message naming it.
"""

from __future__ import annotations

import copy
import json

from .config import Config
from .db import session

HOME_ROW_KINDS = ("continue", "shelves", "recent", "series", "genres")

DEFAULTS: dict = {
    "reading": {"mode": "pages", "theme": "dark", "turn_speed": "normal", "spread": True, "left_handed": False,
                "epub_font": "literata", "epub_size": 100, "epub_margins": "normal"},
    "look": {"accent": "brass", "cover_size": "medium", "cover_titles": True,
             "home_rows": [{"kind": k, "visible": True} for k in HOME_ROW_KINDS]},
}

CHOICES: dict = {
    "reading": {"mode": {"pages", "scroll"}, "theme": {"dark", "sepia", "white", "black"},
                "turn_speed": {"gentle", "normal", "quick", "off"}, "spread": bool, "left_handed": bool,
                "epub_font": {"literata", "serif", "sans"}, "epub_size": range(80, 161),
                "epub_margins": {"narrow", "normal", "wide"}},
    "look": {"accent": {"brass", "sage", "dusk", "rose", "lilac"}, "cover_size": {"small", "medium", "large"},
             "cover_titles": bool, "home_rows": "home_rows"},
}


def _check(section: str, key: str, value) -> None:
    name = f"{section}.{key}"
    allowed = CHOICES[section].get(key)
    if allowed is None:
        raise ValueError(f"Unknown setting {name}")
    if allowed is bool:
        ok = isinstance(value, bool)
    elif isinstance(allowed, range):
        ok = isinstance(value, int) and not isinstance(value, bool) and value in allowed
    elif allowed == "home_rows":
        ok = (isinstance(value, list) and len(value) == len(HOME_ROW_KINDS)
              and all(isinstance(r, dict) and set(r) == {"kind", "visible"} and isinstance(r["visible"], bool)
                      for r in value)
              and sorted(r["kind"] for r in value) == sorted(HOME_ROW_KINDS))
    else:
        ok = isinstance(value, str) and value in allowed
    if not ok:
        raise ValueError(f"{name} can't be {value!r}")


def _complete_rows(rows):
    """Rows saved before a kind of row existed keep their order; the new kinds go at the end."""
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return rows
    have = {r.get("kind") for r in rows}
    return rows + [{"kind": k, "visible": True} for k in HOME_ROW_KINDS if k not in have]


def _stored(cfg: Config, user_id: int) -> dict:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT data FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    return json.loads(row["data"]) if row else {}


def get_settings(cfg: Config, user_id: int) -> dict:
    result = copy.deepcopy(DEFAULTS)
    for section, values in _stored(cfg, user_id).items():
        if section not in result or not isinstance(values, dict):
            continue
        for key, value in values.items():
            if section == "look" and key == "home_rows":
                value = _complete_rows(value)
            try:
                _check(section, key, value)
            except ValueError:
                continue  # a setting that's no longer valid falls back to its default
            result[section][key] = value
    return result


def update_settings(cfg: Config, user_id: int, patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("Settings must be an object")
    for section, values in patch.items():
        if section not in CHOICES:
            raise ValueError(f"Unknown setting {section}")
        if not isinstance(values, dict):
            raise ValueError(f"{section} must be an object")
        for key, value in values.items():
            _check(section, key, value)
    stored = _stored(cfg, user_id)
    for section, values in patch.items():
        stored.setdefault(section, {}).update(values)
    with session(cfg.db_path) as con:
        con.execute("INSERT INTO user_settings(user_id, data) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data", (user_id, json.dumps(stored)))
    return get_settings(cfg, user_id)
