"""Backups of the library (src/loft/backups.py): making, keeping, restoring."""

import json
import shutil
import sqlite3
import time
import zipfile
from datetime import date
from pathlib import Path

import pytest

from loft import auth, backups
from loft.backups import DAY, BackupError, due, list_backups, make, path_of, prune, to_keep
from loft.db import session


def set_library(cfg, **values):
    """Library settings straight into the database, as the app saves them."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT value FROM meta WHERE key = 'library'").fetchone()
        stored = {**(json.loads(row["value"]) if row else {}), **values}
        con.execute("INSERT INTO meta(key, value) VALUES ('library', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(stored),))


def users_in(db: Path) -> list[str]:
    con = sqlite3.connect(db)
    try:
        return [r[0] for r in con.execute("SELECT username FROM users ORDER BY id")]
    finally:
        con.close()


def db_inside(zip_path: Path, tmp_path: Path) -> Path:
    out = tmp_path / f"inside-{zip_path.stem}"
    with zipfile.ZipFile(zip_path) as z:
        z.extract("loft.db", out)
    return out / "loft.db"


@pytest.fixture
def library(cfg):
    """A library with someone in it, a cover, an upload waiting, and caches that aren't backed up."""
    auth.create_user(cfg, "ann", "correct horse battery", admin=True)
    cfg.cover_dir.mkdir(parents=True, exist_ok=True)
    (cfg.cover_dir / "1-240.jpg").write_bytes(b"cover")
    (cfg.data_dir / "uploads" / "x").mkdir(parents=True)
    (cfg.data_dir / "uploads" / "x" / "book.epub").write_bytes(b"epub")
    (cfg.page_dir / "1").mkdir(parents=True)
    (cfg.page_dir / "1" / "p.webp").write_bytes(b"page")
    cfg.flow_dir.mkdir(parents=True)
    (cfg.flow_dir / "f").write_bytes(b"flow")
    (cfg.data_dir / "secret_key").write_text("s" * 32)
    return cfg


def last_seven_days(now: float) -> set:
    today = date.fromtimestamp(now).toordinal()
    return {date.fromordinal(today - i) for i in range(7)}


def test_due_by_schedule():
    now = 10 * DAY
    assert due([], now, "day") and due([], now, "week") and not due([], now, "off")
    assert not due([now - DAY + 3601], now, "day") and due([now - DAY + 3600], now, "day")
    assert not due([now - 6 * DAY], now, "week") and due([now - 7 * DAY + 3600], now, "week")
    assert not due([now - 30 * DAY], now, "off")


def test_keeping_shelfs_way_and_by_count():
    now = 100 * DAY
    times = [now - h * 3600 for h in range(0, 24 * 80, 12)]   # two a day for 80 days
    kept = to_keep(times, now, 0)
    assert max(times) in kept and len(kept) == 7 + 8           # a week of days, then 8 weeks
    assert to_keep(times, now, 5) == set(sorted(times)[-5:])
    assert to_keep([], now, 0) == set()


def test_daily_backups_a_little_under_a_day_apart_keep_a_whole_week():
    """Backups are due after 23 hours and looked for hourly, so they land 23 to 24 hours apart."""
    now = 100 * DAY
    for gap in (23 * 3600, 23.5 * 3600, 24 * 3600 - 60):
        times = [now - i * gap for i in range(30)]
        kept = to_keep(times, now, 0)
        assert last_seven_days(now) <= {date.fromtimestamp(t) for t in kept}, gap   # one for each


def test_a_backup_holds_the_database_covers_and_uploads(library, tmp_path):
    made = make(library)
    assert made.parent == library.data_dir / "backups" and backups.NAME.match(made.name)
    with zipfile.ZipFile(made) as z:
        names = set(z.namelist())
    assert {"loft.db", "covers/1-240.jpg", "uploads/x/book.epub"} <= names
    assert not any(n.startswith(("pages/", "flow/")) or n == "secret_key" for n in names)
    assert users_in(db_inside(made, tmp_path)) == ["ann"]
    assert [b["name"] for b in list_backups(library)] == [made.name]


def test_the_backup_holds_what_was_just_written(library, tmp_path):
    con = sqlite3.connect(library.db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("INSERT INTO meta(key, value) VALUES ('just', 'written')")
    con.commit()   # in the WAL, not yet checkpointed into loft.db; the connection stays open
    try:
        made = make(library)
    finally:
        con.close()
    inside = sqlite3.connect(db_inside(made, tmp_path))
    assert inside.execute("SELECT value FROM meta WHERE key = 'just'").fetchone() == ("written",)
    inside.close()


def test_a_failed_backup_leaves_nothing_behind(library, monkeypatch):
    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(zipfile.ZipFile, "write", full)
    with pytest.raises(OSError):
        make(library)
    folder = library.data_dir / "backups"
    assert not list(folder.glob("*.zip")) and not list(folder.glob("*.part"))


def test_only_lofts_backups_are_touched(library):
    folder = library.data_dir / "backups"
    folder.mkdir()
    for other in ("holiday.zip", "loft-notes.zip", "loft-2026-11-21-120000.zip.old"):
        (folder / other).write_bytes(b"mine")
    now = 200 * DAY
    for i in range(12):
        make(library, now=now - (12 - i) * DAY)
    set_library(library, backup_keep=5)
    prune(library, now=now)
    for other in ("holiday.zip", "loft-notes.zip", "loft-2026-11-21-120000.zip.old"):
        assert (folder / other).read_bytes() == b"mine"
    assert all(backups.NAME.match(b["name"]) for b in list_backups(library))


def test_pruning_keeps_the_newest_and_before_restore_copies_a_month(library):
    set_library(library, backup_keep=5)
    now = 300 * DAY
    old_safety = make(library, now=now - 31 * DAY, suffix=backups.RESTORE_SUFFIX)
    new_safety = make(library, now=now - 29 * DAY, suffix=backups.RESTORE_SUFFIX)
    made = [make(library, now=now - (8 - i) * DAY) for i in range(8)]
    prune(library, now=now)
    left = {b["name"] for b in list_backups(library)}
    assert {p.name for p in made[-5:]} | {new_safety.name} == left
    assert old_safety.name not in left
    assert [b["before_restore"] for b in list_backups(library) if b["name"] == new_safety.name] == [True]


def test_path_of_refuses_other_names(library):
    make(library)
    for bad in ["../loft.db", "holiday.zip", "loft-2026-11-21-120000.zip/../x", "loft-2026-11-21-120000.zip"]:
        with pytest.raises(BackupError):
            path_of(library, bad)
    good = list_backups(library)[0]["name"]
    assert path_of(library, good).is_file()


# ---------- restoring ----------

def test_restoring_puts_everything_back_and_keeps_what_was_there(library):
    made = make(library)
    auth.create_user(library, "ben", "another long password")
    (library.cover_dir / "1-240.jpg").write_bytes(b"a new cover")
    shutil.rmtree(library.data_dir / "uploads")
    safety = backups.restore(library, made.name)
    assert users_in(library.db_path) == ["ann"]
    assert (library.cover_dir / "1-240.jpg").read_bytes() == b"cover"
    assert (library.data_dir / "uploads" / "x" / "book.epub").read_bytes() == b"epub"
    assert not any(p.is_file() for p in library.page_dir.rglob("*"))   # remade from the books when needed
    assert not any(p.is_file() for p in library.flow_dir.rglob("*"))
    assert (library.data_dir / "secret_key").read_text() == "s" * 32    # sign-ins aren't part of a backup
    listed = {b["name"]: b for b in list_backups(library)}
    assert listed[safety.name]["before_restore"] and made.name in listed
    backups.restore(library, safety.name)                                 # a wrong restore can be undone
    assert users_in(library.db_path) == ["ann", "ben"]
    assert (library.cover_dir / "1-240.jpg").read_bytes() == b"a new cover"


def test_a_restore_keeps_the_backup_settings_as_they_are_now(library, tmp_path):
    """They say where the backups are: restoring an older library mustn't send Loft to another folder,
    where the backup made just before the restore couldn't be seen."""
    from loft import libsettings
    old = make(library)                                    # made with the settings from back then
    usb = tmp_path / "usb"
    usb.mkdir()
    shutil.copy2(old, usb / old.name)                      # the admin moved their backups to another drive
    libsettings.update_library(library, {"backup_dir": str(usb), "backup_every": "week", "backup_keep": 10})
    safety = backups.restore(library, old.name)
    lib = libsettings.get_library(library)
    assert (lib["backup_dir"], lib["backup_every"], lib["backup_keep"]) == (str(usb), "week", 10)
    assert safety.parent == usb and safety.name in [b["name"] for b in list_backups(library)]


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def test_bad_backups_are_refused_before_anything_changes(library, tmp_path):
    good = make(library)
    folder = good.parent
    sid = backups.server_id(library)
    db = good.parent / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE things(x)")
    con.commit()
    con.close()
    good_db = db_inside(good, tmp_path).read_bytes()
    bad = {
        f"loft-2020-01-01-000001-{sid}.zip": good.read_bytes()[:len(good.read_bytes()) // 2],   # cut short
        f"loft-2020-01-01-000002-{sid}.zip": {"covers/1-240.jpg": b"c"},                        # no database
        f"loft-2020-01-01-000003-{sid}.zip": {"loft.db": b"not a database at all"},
        f"loft-2020-01-01-000004-{sid}.zip": {"loft.db": good_db, "../evil": b"x"},
        f"loft-2020-01-01-000005-{sid}.zip": {"loft.db": good_db, "/abs/evil": b"x"},
        f"loft-2020-01-01-000006-{sid}.zip": {"loft.db": db.read_bytes()},                      # not Loft's
        f"loft-2020-01-01-000007-{sid}.zip": {"loft.db": good_db, "pages/1/p.webp": b"x"},      # not what a backup holds
    }
    db.unlink()
    for name, content in bad.items():
        if isinstance(content, bytes):
            (folder / name).write_bytes(content)
        else:
            _zip(folder / name, content)
    auth.create_user(library, "ben", "another long password")
    before = {b["name"] for b in list_backups(library)}
    for name in bad:
        with pytest.raises(BackupError):
            backups.restore(library, name)
        assert users_in(library.db_path) == ["ann", "ben"]
        assert (library.cover_dir / "1-240.jpg").read_bytes() == b"cover"
        assert {b["name"] for b in list_backups(library)} == before   # no backup made before refusing
    assert not (tmp_path.parent / "evil").exists() and not Path("/abs/evil").exists()


def test_an_older_backup_gets_the_newer_columns(library, tmp_path):
    made = make(library)
    old_db = db_inside(made, tmp_path)
    con = sqlite3.connect(old_db)
    con.execute("ALTER TABLE progress DROP COLUMN locator")   # as a database from before it was added
    con.commit()
    con.close()
    with zipfile.ZipFile(made) as z:
        others = {n: z.read(n) for n in z.namelist() if n != "loft.db"}
    _zip(made, {"loft.db": old_db.read_bytes(), **others})
    backups.restore(library, made.name)
    con = sqlite3.connect(library.db_path)
    assert "locator" in [r[1] for r in con.execute("PRAGMA table_info(progress)")]
    con.close()


# ---------- by itself ----------

def backup_notes(cfg) -> list[tuple[str, str]]:
    with session(cfg.db_path) as con:
        return [(r["text"], r["link"]) for r in con.execute("SELECT text, link FROM notifications WHERE kind = 'backup'")]


def test_step_follows_the_schedule(library):
    t = 50 * DAY
    assert backups.step(library, now=t) is not None
    assert backups.step(library, now=t + 3600) is None
    assert backups.step(library, now=t + 23 * 3600) is not None
    assert backups.status(library)["last_at"] == t + 23 * 3600
    set_library(library, backup_every="off")
    assert backups.step(library, now=t + 30 * DAY) is None
    assert prune(library, now=t + 300 * DAY) == 0 and len(list_backups(library)) == 2


def test_a_folder_that_is_gone_fails_loudly_once(library, tmp_path):
    from loft import libsettings
    usb = tmp_path / "usb" / "backups"
    usb.mkdir(parents=True)
    libsettings.update_library(library, {"backup_dir": str(usb)})
    away = usb.with_name("away")
    usb.rename(away)                                          # the drive was unplugged
    t = 60 * DAY
    assert backups.step(library, now=t) is None
    assert not usb.exists()                                   # never made on whatever disk is there instead
    error = backups.status(library)["error"]
    assert str(usb) in error and error.startswith("Loft couldn’t back up the library")
    assert backup_notes(library) == [(error, "#/admin")]
    assert backups.step(library, now=t + 3600) is None
    assert len(backup_notes(library)) == 1                    # told once, not every hour
    away.rename(usb)                                          # and plugged in again
    assert backups.step(library, now=t + 7200) is not None
    assert backups.status(library)["error"] == ""
    shutil.rmtree(usb)
    backups.step(library, now=t + 2 * DAY)
    assert len(backup_notes(library)) == 2                    # a new failure is told again


def test_status_says_where_and_what(library, tmp_path):
    s = backups.status(library)
    assert (s["every"], s["keep"], s["folder"], s["folder_is_default"]) == ("day", 0, str(library.data_dir / "backups"), True)
    assert s["backups"] == [] and s["last_at"] is None and s["error"] == ""
    made = backups.make_now(library)
    assert backups.status(library)["backups"][0]["name"] == made.name


# ---------- routes ----------

def test_backup_routes(client):
    r = client.post("/api/backups")
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    assert [b["name"] for b in r.json()["backups"]] == [name] and r.json()["error"] == ""
    assert client.get("/api/backups").json()["backups"][0]["name"] == name
    got = client.get(f"/api/backups/{name}")
    assert got.status_code == 200 and got.headers["content-type"] == "application/zip"
    assert name in got.headers["content-disposition"]
    import io
    assert "loft.db" in zipfile.ZipFile(io.BytesIO(got.content)).namelist()
    r = client.post(f"/api/backups/{name}/restore")
    assert r.status_code == 200, r.text
    assert r.json()["before"] in [b["name"] for b in r.json()["backups"]]
    assert client.get("/api/backups").status_code == 401          # a restore signs everyone out
    assert client.post("/api/login", json={"username": "admin", "password": "longpassword"}).status_code == 200
    assert client.get("/api/backups/..%2Fsecret_key").status_code == 404
    assert client.get("/api/backups/loft-2020-01-01-000000.zip").status_code == 404
    assert client.post("/api/backups/holiday.zip/restore").status_code == 400


def test_back_up_now_says_why_it_cant(client, cfg, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    assert client.patch("/api/library", json={"backup_dir": str(usb)}).status_code == 200
    shutil.rmtree(usb)
    r = client.post("/api/backups")
    assert r.status_code == 500 and str(usb) in r.json()["detail"]


def test_backup_routes_are_for_admins(app_lib):
    calls = [("get", "/api/backups"), ("post", "/api/backups"),
             ("get", "/api/backups/loft-2020-01-01-000000.zip"), ("post", "/api/backups/loft-2020-01-01-000000.zip/restore")]
    for method, path in calls:
        assert getattr(app_lib, method)(path).status_code == 401, path
    assert app_lib.post("/api/setup", json={"username": "admin", "password": "longpassword"}).status_code == 200
    assert app_lib.post("/api/users", json={"username": "ben", "password": "another long password"}).status_code == 200
    app_lib.post("/api/logout")
    assert app_lib.post("/api/login", json={"username": "ben", "password": "another long password"}).status_code == 200
    for method, path in calls:
        assert getattr(app_lib, method)(path).status_code == 403, path


# ---------- found in review ----------

def test_months_of_daily_backups_keep_a_week_then_eight_weeks():
    """As it really runs: looked for every hour, a backup when due, pruned after each."""
    start = 1_700_000_000.0
    times: list[float] = []
    for hour in range(150 * 24):
        now = start + hour * 3600 + 7
        if due(times, now, "day"):
            times = sorted(to_keep(times + [now], now, 0))
    now = times[-1]
    assert last_seven_days(now) <= {date.fromtimestamp(t) for t in times}
    assert (now - min(times)) / DAY >= 49                      # the weekly ones reach back about two months
    assert 14 <= len(times) <= 16


def test_a_restore_signs_everyone_out(client):
    """Sign-ins are by account number, and a removed account's number is given to the next person:
    after a restore, nobody's sign-in may become someone else's."""
    from fastapi.testclient import TestClient
    bob = client.post("/api/users", json={"username": "bob", "password": "bobs long password"}).json()
    name = client.post("/api/backups").json()["name"]
    assert client.delete(f"/api/users/{bob['id']}").status_code in (200, 204)
    carol = client.post("/api/users", json={"username": "carol", "password": "carols long password"}).json()
    assert carol["id"] == bob["id"]                            # the same number, as SQLite reuses it
    other = TestClient(client.app)
    assert other.post("/api/login", json={"username": "carol", "password": "carols long password"}).status_code == 200
    assert client.post(f"/api/backups/{name}/restore").status_code == 200
    assert other.get("/api/me").status_code == 401             # not signed in as bob
    assert client.get("/api/me").status_code == 401            # everyone signs in again


def test_a_drive_that_isnt_there_leaves_an_empty_mount_point_alone(library, tmp_path):
    from loft import libsettings
    mount = tmp_path / "mnt" / "usb"
    mount.mkdir(parents=True)
    libsettings.update_library(library, {"backup_dir": str(mount)})
    assert backups.step(library, now=70 * DAY) is not None
    shutil.rmtree(mount)
    mount.mkdir()                                              # unplugged: an empty folder on the system disk
    assert backups.step(library, now=71 * DAY) is None
    assert list(mount.iterdir()) == []
    assert "drive" in backups.status(library)["error"] and len(backup_notes(library)) == 1


def test_backups_copied_to_another_drive_keep_their_dates(library, tmp_path):
    from loft import libsettings
    now = 400 * DAY
    made = [make(library, now=now - (5 - i) * DAY) for i in range(5)]
    usb = tmp_path / "usb"
    usb.mkdir()
    libsettings.update_library(library, {"backup_dir": str(usb)})
    for p in made:
        shutil.copy(p, usb / p.name)                           # copying gives them today's file dates
    make(library, now=now)
    names = {b["name"] for b in list_backups(library)}
    assert {p.name for p in made} <= names
    assert sorted(b["at"] for b in list_backups(library))[:5] == [now - (5 - i) * DAY for i in range(5)]


def test_a_folder_loft_cant_read_is_refused_and_reported(library, tmp_path):
    from loft import libsettings
    write_only = tmp_path / "write-only"
    write_only.mkdir()
    later = tmp_path / "later"
    later.mkdir()
    try:
        write_only.chmod(0o300)
        with pytest.raises(ValueError, match="read"):
            libsettings.update_library(library, {"backup_dir": str(write_only)})
        libsettings.update_library(library, {"backup_dir": str(later)})
        later.chmod(0o300)                                     # became unreadable after it was chosen
        assert backups.step(library, now=80 * DAY) is None
        s = backups.status(library)                            # Library settings still opens
        assert s["error"] and s["backups"] == []
        assert len(backup_notes(library)) == 1
    finally:
        write_only.chmod(0o700)
        later.chmod(0o700)


def test_a_restore_that_fails_partway_changes_nothing(library, monkeypatch):
    made = make(library)
    auth.create_user(library, "ben", "another long password")
    (library.cover_dir / "1-240.jpg").write_bytes(b"a new cover")
    real = Path.rename

    def in_use(self, target):
        if self.name == "uploads" and self.parent.name.startswith(".restore-"):
            raise PermissionError(13, "The file is in use by another process", str(self))
        return real(self, target)
    monkeypatch.setattr(Path, "rename", in_use)
    with pytest.raises(BackupError, match="nothing was changed"):
        backups.restore(library, made.name)
    assert users_in(library.db_path) == ["ann", "ben"]
    assert (library.cover_dir / "1-240.jpg").read_bytes() == b"a new cover"
    assert (library.data_dir / "uploads" / "x" / "book.epub").read_bytes() == b"epub"


def test_two_lofts_sharing_a_folder_leave_each_others_backups_alone(library, tmp_path):
    from loft import libsettings
    nas = tmp_path / "nas"
    nas.mkdir()
    libsettings.update_library(library, {"backup_dir": str(nas), "backup_keep": 5})
    mine = backups.server_id(library)
    theirs = "abcdef" if mine != "abcdef" else "fedcba"
    first = make(library, now=500 * DAY)
    others = [nas / first.name.replace(mine, theirs).replace("500", "5")] + [
        nas / f"loft-2020-01-0{i}-120000-{theirs}.zip" for i in range(1, 8)]
    for o in others:
        shutil.copy(first, o)
    for i in range(1, 10):
        make(library, now=500 * DAY + i * DAY)
    assert all(o.exists() for o in others)                     # never pruned by this Loft
    listed = list_backups(library)
    assert sum(b["mine"] for b in listed) == 5 and sum(not b["mine"] for b in listed) == len(others)
    backups.restore(library, others[-1].name)                  # a backup from another Loft can still be restored


def test_backups_stay_out_of_lofts_own_folders(cfg):
    from loft import libsettings
    own = [cfg.data_dir, cfg.page_dir, cfg.cover_dir, cfg.data_dir / "uploads", cfg.flow_dir]
    for place in own + [cfg.data_dir / "backups"]:
        place.mkdir(parents=True, exist_ok=True)
    for place in own:
        with pytest.raises(ValueError, match="Loft’s own"):
            libsettings.update_library(cfg, {"backup_dir": str(place)})
    assert libsettings.update_library(cfg, {"backup_dir": str(cfg.data_dir / "backups")})["backup_dir"]
