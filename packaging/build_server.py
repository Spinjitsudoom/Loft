"""Build the standalone Loft server for the system this runs on, into dist/.

    uv run --with pyinstaller python packaging/build_server.py

Makes dist/loft-server-<version>-<system>-<arch>.zip (.tar.gz on Linux): a folder, loft-server, holding
the program, the web app and everything Python needs, so nothing has to be installed first. On
Windows it also makes dist/loft-server-<version>-windows-<arch>-setup.exe from the same folder, with
Inno Setup 6 (packaging/windows/loft-server.iss); set ISCC to its ISCC.exe if it isn't found.
"""
from __future__ import annotations

import os
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
        windows_setup(folder, dist, work)
    shutil.rmtree(folder)
    print(f"Built {out}")


def find_iscc() -> str | None:
    candidates = [os.environ.get("ISCC"), shutil.which("iscc")]
    for base in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        if os.environ.get(base):
            candidates += [str(Path(os.environ[base]) / sub / "Inno Setup 6" / "ISCC.exe") for sub in ("", "Programs")]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def windows_setup(folder: Path, dist: Path, work: Path) -> None:
    """The installer: the same folder, put in the Start menu, with an uninstaller."""
    iscc = find_iscc()
    if not iscc:
        if os.environ.get("CI"):
            raise SystemExit("Inno Setup 6 (ISCC.exe) is needed to build the Windows setup")
        print("Inno Setup 6 isn't installed: skipping the Windows setup")
        return
    from PIL import Image
    icon = work / "loft.ico"
    Image.open(ROOT / "desktop" / "app" / "icon.png").save(icon, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    subprocess.run([iscc, "/Q", f"/DAppVersion={VERSION}", f"/DSourceDir={folder}", f"/DOutputDir={dist}",
                    f"/DOutputName={NAME}-setup", f"/DIconFile={icon}",
                    str(ROOT / "packaging" / "windows" / "loft-server.iss")], check=True)
    print(f"Built {dist / (NAME + '-setup.exe')}")


if __name__ == "__main__":
    main()
