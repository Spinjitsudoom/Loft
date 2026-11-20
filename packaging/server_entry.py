"""What the standalone Loft server runs (packaging/build_server.py builds it with PyInstaller)."""
import multiprocessing

from loft import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
