"""Updating Loft: finding a newer release, downloading the standalone server, and swapping it in."""

import hashlib
import io
import json
import os
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loft import auth, libsettings, updates
from loft.app import create_app
from loft.db import session


def server_tar(version: str) -> bytes:
    """A stand-in release archive for Linux: one folder holding the program."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text, mode in [("loft-server", f"#!/bin/sh\necho {version}\n", 0o755), ("README.txt", "hi", 0o644)]:
            data = text.encode()
            info = tarfile.TarInfo(f"loft-server-{version}-linux-x64/{name}")
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def release(monkeypatch, tmp_path):
    """GitHub, faked: a release whose files are served from memory. Returns the files to change."""
    monkeypatch.setattr(updates, "current_version", lambda: "0.1.1")
    monkeypatch.setattr(updates, "system", lambda: ("linux", "x64"))
    monkeypatch.setattr(updates.sys, "platform", "linux")
    home = tmp_path / "opt" / "loft-server"
    home.mkdir(parents=True)
    (home / "loft-server").write_text("old")
    (home / "config.toml").write_text("port = 4545\n")
    monkeypatch.setenv("LOFT_UPDATES_INSTALL", str(home))
    archive = server_tar("0.1.2")
    files = {
        "loft-server-0.1.2-linux-x64.tar.gz": archive,
        "SHA256SUMS.txt": f"{hashlib.sha256(archive).hexdigest()}  loft-server-0.1.2-linux-x64.tar.gz\n".encode(),
    }
    meta = {"tag_name": "v0.1.2", "html_url": "https://github.com/Spinjitsudoom/Loft/releases/tag/v0.1.2",
            "draft": False, "prerelease": False}

    def fake_get(url, limit):
        if url == updates.LATEST:
            assets = [{"name": n, "browser_download_url": f"https://github.com/dl/{n}"} for n in files]
            return json.dumps({**meta, "assets": assets}).encode()
        return files[url.rsplit("/", 1)[1]]

    def fake_download(url, to):
        to.write_bytes(files[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(updates, "_get", fake_get)
    monkeypatch.setattr(updates, "_download", fake_download)
    return {"files": files, "meta": meta, "home": home}


def admin_notes(cfg):
    with session(cfg.db_path) as con:
        return [r["text"] for r in con.execute("SELECT text FROM notifications WHERE kind = 'update' ORDER BY id")]


def test_versions():
    assert updates.parse("v0.1.2") == (0, 1, 2) and updates.parse("0.10.0") == (0, 10, 0)
    assert updates.parse("0.2.0-beta") is None and updates.parse("") is None
    assert updates.newer("0.1.10", "0.1.9") and not updates.newer("0.1.1", "0.1.1")
    assert not updates.newer("nonsense", "0.1.1")


@pytest.mark.parametrize("plat, machine, name", [
    ("linux", "x86_64", "loft-server-0.1.2-linux-x64.tar.gz"),
    ("darwin", "arm64", "loft-server-0.1.2-macos-arm64.zip"),
    ("win32", "AMD64", "loft-server-0.1.2-windows-x64.zip"),
])
def test_asset_names_match_the_build(monkeypatch, plat, machine, name):
    monkeypatch.setattr(updates.sys, "platform", plat)
    monkeypatch.setattr(updates.platform, "machine", lambda: machine)
    assert updates.asset_name("0.1.2") == name


def test_a_newer_release_is_downloaded_and_admins_are_told(cfg, release):
    auth.create_user(cfg, "ann", "correct horse battery", admin=True)
    now = updates.check(cfg)
    assert now["newer"] and now["latest"] == "0.1.2" and now["ready"] and not now["error"]
    stage = updates.staging_dir("0.1.2")
    assert (stage / "loft-server").read_text().strip().endswith("0.1.2")
    assert os.stat(stage / "loft-server").st_mode & stat.S_IXUSR
    assert (release["home"] / "loft-server").read_text() == "old"   # nothing changes until asked
    assert admin_notes(cfg) == ["Loft 0.1.2 is ready to install: restart to update in Library settings"]
    updates.check(cfg)
    assert len(admin_notes(cfg)) == 1   # told once


def test_a_bad_checksum_is_never_installed(cfg, release):
    release["files"]["SHA256SUMS.txt"] = b"0" * 64 + b"  loft-server-0.1.2-linux-x64.tar.gz\n"
    now = updates.check(cfg)
    assert now["newer"] and not now["ready"] and "couldn’t be downloaded" in now["error"]
    assert not updates.staging_dir("0.1.2").exists()


def test_same_version_or_drafts_change_nothing(cfg, release):
    release["meta"]["tag_name"] = "v0.1.1"
    assert not updates.check(cfg)["newer"]
    release["meta"].update(tag_name="v0.9.0", prerelease=True)
    assert not updates.check(cfg)["newer"]
    assert admin_notes(cfg) == []


def test_other_installs_are_only_told(cfg, release, monkeypatch):
    monkeypatch.delenv("LOFT_UPDATES_INSTALL")
    auth.create_user(cfg, "ann", "correct horse battery", admin=True)
    now = updates.check(cfg)
    assert now["newer"] and not now["can_install"] and not now["ready"]
    assert admin_notes(cfg) == ["Loft 0.1.2 is out"]


def test_github_unreachable(cfg, release, monkeypatch):
    def down(url, limit):
        raise OSError("no network")
    monkeypatch.setattr(updates, "_get", down)
    now = updates.check(cfg)
    assert not now["newer"] and "couldn’t reach GitHub" in now["error"]


def test_restarting_swaps_the_folders_and_keeps_config(cfg, release, monkeypatch):
    updates.check(cfg)
    started = []
    monkeypatch.setattr(updates.os, "execve", lambda path, argv, env: started.append((path, env)))
    home = release["home"]
    updates._restart_into("0.1.2")
    assert (home / "loft-server").read_text().strip().endswith("0.1.2")
    assert (home / "config.toml").read_text() == "port = 4545\n"
    assert (home.with_name("loft-server.previous") / "loft-server").read_text() == "old"
    assert not updates.staging_dir("0.1.2").exists()
    assert started[0][0] == str(home / "loft-server")
    assert started[0][1]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


@pytest.fixture
def windows_setup_install(release, monkeypatch):
    """The release above, seen from a copy installed on Windows by the setup."""
    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(updates, "system", lambda: ("windows", "x64"))
    monkeypatch.setattr(updates, "PROGRAM", "loft-server.exe")
    home = release["home"]
    (home / "loft-server.exe").write_text("old")
    (home / "unins000.exe").write_bytes(b"MZ uninstaller")
    setup = b"MZ setup for 0.1.2"
    name = "loft-server-0.1.2-windows-x64-setup.exe"
    release["files"].clear()
    release["files"].update({
        name: setup,
        "loft-server-0.1.2-windows-x64.zip": b"not this one",
        "SHA256SUMS.txt": f"{hashlib.sha256(setup).hexdigest()}  {name}\n".encode(),
    })
    return {**release, "name": name, "setup": setup}


def test_copies_installed_by_the_setup_download_the_next_setup(cfg, windows_setup_install):
    assert updates.asset_name("0.1.2") == windows_setup_install["name"]
    now = updates.check(cfg)
    assert now["ready"] and not now["error"]
    assert (updates.staging_dir("0.1.2") / windows_setup_install["name"]).read_bytes() == windows_setup_install["setup"]


def test_a_setup_with_a_bad_checksum_is_never_run(cfg, windows_setup_install):
    windows_setup_install["files"][windows_setup_install["name"]] = b"MZ something else"
    now = updates.check(cfg)
    assert not now["ready"] and "couldn’t be downloaded" in now["error"]


def restart_script(monkeypatch, version) -> str:
    started = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda args, **kw: started.append(args))
    monkeypatch.setattr(updates.os, "_exit", lambda code: started.append(("exit", code)))
    updates._restart_into(version)
    assert started[-1] == ("exit", updates.UPDATING)
    script = Path(started[0][-1])
    return script.read_text()


def start_setup(monkeypatch, version, refuse_breakaway=False) -> list:
    """Restart into `version` on a setup install; returns each Popen call as (args, kwargs)."""
    calls = []
    def popen(args, **kw):
        calls.append((args, kw))
        if refuse_breakaway and kw.get("creationflags", 0) & updates.BREAKAWAY:
            raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(updates.subprocess, "Popen", popen)
    monkeypatch.setattr(updates.os, "_exit", lambda code: calls.append(("exit", code)))
    updates._restart_into(version)
    return calls


def test_restarting_a_setup_install_starts_the_setup_and_lets_it_do_the_rest(cfg, windows_setup_install, monkeypatch, tmp_path):
    # Like Shelf: the setup itself closes Loft, installs over it and starts it again. No script is
    # left running after Loft, and Loft keeps answering until the setup closes it.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("LOFT_TRAY_PID", "4242")
    updates.check(cfg)
    home, stage = windows_setup_install["home"], updates.staging_dir("0.1.2")
    calls = start_setup(monkeypatch, "0.1.2")
    assert len(calls) == 1                                  # one start, and no exit
    args, kw = calls[0]
    log = tmp_path / "local" / "Loft" / "update-setup.log"
    assert args == [str(stage / windows_setup_install["name"]), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                    "/NORESTART", "/SP-", f"/LOG={log}"]
    assert kw["creationflags"] & updates.BREAKAWAY          # outlives Loft whatever started Loft
    assert kw["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and "LOFT_TRAY_PID" not in kw["env"]
    assert log.parent.is_dir()
    assert not list(home.parent.glob("*.cmd"))
    assert (home / "loft-server.exe").read_text() == "old"  # the setup does the replacing


def test_when_windows_wont_let_the_setup_break_away_it_still_starts(cfg, windows_setup_install, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    updates.check(cfg)
    calls = start_setup(monkeypatch, "0.1.2", refuse_breakaway=True)
    assert [bool(kw["creationflags"] & updates.BREAKAWAY) for _, kw in calls] == [True, False]
    assert ("exit", updates.UPDATING) not in calls


def test_a_setup_that_cant_start_leaves_loft_running(cfg, windows_setup_install, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    updates.check(cfg)
    def popen(args, **kw):
        raise OSError(2, "The system cannot find the file specified")
    monkeypatch.setattr(updates.subprocess, "Popen", popen)
    monkeypatch.setattr(updates.os, "_exit", lambda code: pytest.fail("Loft stopped"))
    updates._restart_into("0.1.2")
    assert "Couldn’t start the setup for Loft 0.1.2" in caplog.text


def test_restarting_an_unpacked_windows_copy_still_swaps_folders(cfg, release, monkeypatch):
    monkeypatch.setattr(updates.sys, "platform", "win32")
    updates.check(cfg)
    script = restart_script(monkeypatch, "0.1.2")
    assert "/VERYSILENT" not in script and f'move "{updates.staging_dir("0.1.2")}"' in script


def test_an_unpacked_copy_run_by_the_tray_comes_back_with_the_tray(cfg, release, monkeypatch):
    monkeypatch.setattr(updates.sys, "platform", "win32")
    (release["home"] / "Loft Server.exe").write_text("tray")
    monkeypatch.setenv("LOFT_TRAY_PID", "4242")
    updates.check(cfg)
    script = restart_script(monkeypatch, "0.1.2")
    assert f'move "{updates.staging_dir("0.1.2")}"' in script
    assert f'"{release["home"] / "Loft Server.exe"}" --background' in script


def test_the_folder_swap_script_waits_without_a_console(cfg, release, monkeypatch):
    # "timeout" quits at once when there's no console (as for a script Loft starts in the
    # background), so waiting for Loft to stop used it to spin; ping waits anywhere.
    monkeypatch.setattr(updates.sys, "platform", "win32")
    updates.check(cfg)
    script = restart_script(monkeypatch, "0.1.2")
    assert "timeout" not in script and "ping -n 2 127.0.0.1 >nul" in script


def test_leftovers_of_an_installed_update_are_cleared(cfg, windows_setup_install):
    home = windows_setup_install["home"]
    done = home.parent / f".{home.name}.update-0.1.1"      # the version running now: installed
    done.mkdir()
    (done / "loft-server-0.1.1-windows-x64-setup.exe").write_bytes(b"MZ")
    waiting = updates.staging_dir("0.1.2")                  # newer: still to be installed
    waiting.mkdir()
    script = home.parent / f".{home.name}.update.cmd"
    script.write_text("@echo off")
    updates.tidy(cfg)
    assert not done.exists() and not script.exists() and waiting.is_dir()


def test_a_download_cut_short_doesnt_say_downloading_forever(cfg, release):
    updates.check(cfg, download=False)
    updates._save(cfg, downloading=True)                    # Loft stopped in the middle of it
    assert updates.status(cfg)["downloading"]
    updates.tidy(cfg)
    assert not updates.status(cfg)["downloading"]


def zip_with(entries) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            z.writestr(info, data)
    return buf


def test_zips_keep_links_and_execute_bits(tmp_path):
    archive = tmp_path / "a.zip"
    archive.write_bytes(zip_with([
        ("s/loft-server", "x", stat.S_IFREG | 0o755),
        ("s/_internal/lib.dylib", "lib", stat.S_IFREG | 0o644),
        ("s/_internal/Python", "lib.dylib", stat.S_IFLNK | 0o777),
    ]).getvalue())
    updates.unpack(archive, tmp_path / "out")
    assert os.stat(tmp_path / "out/s/loft-server").st_mode & stat.S_IXUSR
    assert os.readlink(tmp_path / "out/s/_internal/Python") == "lib.dylib"


@pytest.mark.parametrize("entry", [
    ("../evil", "x", stat.S_IFREG | 0o644),
    ("s/link", "../../etc/passwd", stat.S_IFLNK | 0o777),
    ("s/abs", "/etc/passwd", stat.S_IFLNK | 0o777),
])
def test_zips_cant_write_outside(tmp_path, entry):
    archive = tmp_path / "a.zip"
    archive.write_bytes(zip_with([entry]).getvalue())
    with pytest.raises(ValueError):
        updates.unpack(archive, tmp_path / "out")


def test_routes_are_for_admins(cfg, release):
    app = create_app(cfg, scan_on_start=False)
    client = TestClient(app)
    admin = auth.create_user(cfg, "ann", "correct horse battery", admin=True)
    member = auth.create_user(cfg, "bob", "correct horse battery")
    as_member = {"Authorization": f"Bearer {auth.make_token(cfg, member)}"}
    as_admin = {"Authorization": f"Bearer {auth.make_token(cfg, admin)}"}
    assert client.get("/api/updates").status_code == 401
    for method, path in [("get", "/api/updates"), ("post", "/api/updates/check"), ("post", "/api/updates/install")]:
        assert getattr(client, method)(path, headers=as_member).status_code == 403
    assert client.post("/api/updates/install", headers=as_admin).status_code == 409
    assert client.get("/api/updates", headers=as_admin).json()["current"] == "0.1.1"


def test_the_switch(cfg):
    assert libsettings.get_library(cfg)["check_updates"] is True
    assert libsettings.update_library(cfg, {"check_updates": False})["check_updates"] is False


def test_check_now_without_downloading_waits_to_tell(cfg, release):
    auth.create_user(cfg, "ann", "correct horse battery", admin=True)
    assert updates.check(cfg, download=False)["newer"]
    assert admin_notes(cfg) == []
    updates.check(cfg)
    assert admin_notes(cfg) == ["Loft 0.1.2 is ready to install: restart to update in Library settings"]


def test_every_part_has_the_same_version():
    """The server, desktop app and Android app are released together, so they share one number."""
    import re
    import tomllib
    root = Path(__file__).resolve().parent.parent
    server = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    desktop = json.loads((root / "desktop" / "package.json").read_text())["version"]
    android = re.search(r'VERSION_NAME:-([0-9.]+)\}', (root / "android-lite" / "build.sh").read_text())[1]
    assert server == desktop == android


NOTES = [
    {"version": "0.1.3", "date": "2026-11-21", "new": [{"title": "Later", "text": "Not out yet."}], "fixed": []},
    {"version": "0.1.2", "date": "2026-11-20", "new": [{"title": "Shelves", "text": "Put books on shelves.", "admin": True}],
     "fixed": ["Covers load faster.", {"text": "The Windows server starts in the tray.", "admin": True}]},
    {"version": "0.1.1", "date": "2026-11-19", "new": [], "fixed": ["This version."]},
]


def test_the_next_versions_notes_come_with_the_check(cfg, release):
    release["files"]["whatsnew.json"] = json.dumps(NOTES).encode()
    now = updates.check(cfg, download=False)
    assert now["notes"] == [NOTES[1]]   # newer than this one, up to the release that's out


@pytest.mark.parametrize("body", [b"not json", b'{"version": "0.1.2"}', json.dumps([{"version": "0.1.2", "new": "x"}]).encode(),
                                  json.dumps([{"version": "0.1.2", "fixed": [{"admin": True}]}]).encode()])
def test_notes_that_dont_make_sense_are_left_out(cfg, release, body):
    release["files"]["whatsnew.json"] = body
    now = updates.check(cfg, download=False)
    assert now["newer"] and now["notes"] == []


def test_a_release_without_notes_still_updates(cfg, release):
    now = updates.check(cfg)
    assert now["ready"] and now["notes"] == []
