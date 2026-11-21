# PyInstaller recipe for the Loft server on Windows; packaging/build_server.py runs it. It makes
# dist/loft-server/ with two programs sharing one _internal folder: "Loft Server.exe" (the tray
# icon people start, no window) and loft-server.exe (the server, which the tray runs hidden, and
# which can still be run on its own in a console).
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ICON = os.environ.get("LOFT_ICON") or os.path.join(ROOT, "desktop", "app", "icon.png")

datas = collect_data_files("loft") + copy_metadata("loft")   # the web app; the version /api/ping reports
binaries = []
hidden = collect_submodules("loft") + collect_submodules("uvicorn")
for package in ("pypdfium2", "pypdfium2_raw"):
    d, b, h = collect_all(package)
    datas, binaries, hidden = datas + d, binaries + b, hidden + h

server = Analysis(
    [os.path.join(ROOT, "packaging", "server_entry.py")],
    datas=datas, binaries=binaries, hiddenimports=hidden, excludes=["tkinter"],
)
tray = Analysis(
    [os.path.join(ROOT, "packaging", "windows", "tray.py")],
    datas=[(os.path.join(ROOT, "desktop", "app", "icon.png"), ".")] + copy_metadata("loft"),
    hiddenimports=["pystray._win32", "loft.updates", "loft.config"],
    excludes=["tkinter"],
)

server_exe = EXE(
    PYZ(server.pure), server.scripts, [], exclude_binaries=True,
    name="loft-server", icon=ICON, console=True,
)
tray_exe = EXE(
    PYZ(tray.pure), tray.scripts, [], exclude_binaries=True,
    name="Loft Server", icon=ICON, console=False,
)
COLLECT(
    server_exe, server.binaries, server.datas,
    tray_exe, tray.binaries, tray.datas,
    name="loft-server",
)
