"""Build the standalone Loft server for the system this runs on, into dist/.

    uv run --with pyinstaller python packaging/build_server.py

Makes dist/loft-server-<version>-<system>-<arch>.zip (.tar.gz on Linux): a folder, loft-server, holding
the program, the web app and everything Python needs, so nothing has to be installed first.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
SYSTEM = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
ARCH = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
NAME = f"loft-server-{VERSION}-{SYSTEM}-{ARCH}"


def main() -> None:
    work, dist = ROOT / "build" / "server", ROOT / "dist"
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(dist / "loft-server", ignore_errors=True)
    PyInstaller.__main__.run([
        str(ROOT / "packaging" / "server_entry.py"),
        "--name", "loft-server", "--onedir", "--console", "--noconfirm", "--clean",
        "--distpath", str(dist), "--workpath", str(work), "--specpath", str(work),
        "--collect-data", "loft",            # the web app: HTML, scripts, fonts, icons
        "--collect-submodules", "loft",
        "--collect-submodules", "uvicorn",   # uvicorn picks its loop and protocols by name
        "--collect-all", "pypdfium2", "--collect-all", "pypdfium2_raw",
        "--copy-metadata", "loft",           # /api/ping reports the version from it
        "--icon", str(ROOT / "desktop" / "app" / "icon.png"),
    ])
    folder = dist / "loft-server"
    for doc in ("LICENSE", "config.example.toml"):
        shutil.copy(ROOT / doc, folder / doc)
    shutil.copy(ROOT / "packaging" / "SERVER-README.txt", folder / "README.txt")
    # Inside each download the folder is plain "loft-server": it keeps its name through updates.
    if SYSTEM == "linux":
        out = dist / f"{NAME}.tar.gz"

        def runnable(info: tarfile.TarInfo) -> tarfile.TarInfo:
            # A network share can drop the execute bits: set them for the program and its libraries.
            if info.isdir() or info.name.endswith("/loft-server") or ".so" in info.name.rsplit("/", 1)[-1]:
                info.mode = 0o755
            return info

        with tarfile.open(out, "w:gz") as tar:
            tar.add(folder, arcname="loft-server", filter=runnable)
    elif SYSTEM == "macos":  # ditto keeps the symlinks and signatures macOS needs
        out = dist / f"{NAME}.zip"
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(folder), str(out)], check=True)
    else:
        out = Path(shutil.make_archive(str(dist / NAME), "zip", dist, "loft-server"))
    shutil.rmtree(folder)
    print(f"Built {out}")


if __name__ == "__main__":
    main()
