"""What the standalone Loft server runs (packaging/build_server.py builds it with PyInstaller)."""
import multiprocessing
import sys

from loft import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Run by the Windows tray, what Loft says goes to server.log, which Python would otherwise
    # write in the old Windows code page: a book title it can't spell would stop the server.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
