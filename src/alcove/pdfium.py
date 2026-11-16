"""PDFium isn't thread-safe: every use of it in Alcove goes through open_pdf(), which holds one
process-wide lock for as long as the document is open."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK = threading.RLock()


@contextmanager
def open_pdf(path: Path) -> Iterator["pdfium.PdfDocument"]:  # noqa: F821
    import pypdfium2 as pdfium

    with LOCK:
        doc = pdfium.PdfDocument(str(path))
        try:
            yield doc
        finally:
            doc.close()
