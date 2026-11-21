"""What the standalone Loft server runs (packaging/build_server.py builds it with PyInstaller)."""
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

from loft import main

TRAY = "Loft Server.exe"   # on Windows, what people start: it runs this server hidden


def started_by_hand(platform: str, env, argv: list[str], console_processes: int) -> bool:
    """Windows gave this program a console of its own: it was double-clicked, or started by a
    shortcut (or update) from before the tray. Not when the tray started it, or when it was
    typed in a terminal, which shares its console."""
    return (platform == "win32" and not env.get("LOFT_TRAY_PID") and len(argv) == 1
            and console_processes == 1)


def console_processes() -> int:
    import ctypes
    return ctypes.windll.kernel32.GetConsoleProcessList((ctypes.c_uint * 4)(), 4)


def hand_to_tray() -> None:
    """Run Loft from the tray instead of in this console window, and close it."""
    tray = Path(sys.executable).with_name(TRAY)
    if tray.is_file() and started_by_hand(sys.platform, os.environ, sys.argv, console_processes()):
        subprocess.Popen([str(tray)], close_fds=True, cwd=str(tray.parent),
                         creationflags=subprocess.DETACHED_PROCESS)
        sys.exit(0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.platform == "win32":
        hand_to_tray()
    # Run by the Windows tray, what Loft says goes to server.log, which Python would otherwise
    # write in the old Windows code page: a book title it can't spell would stop the server.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
