from pathlib import Path

import pytest

from alcove.formats import format_of


@pytest.mark.parametrize("name,fmt", [
    ("A/B.PDF", "pdf"), ("x.cbr", "cbr"), ("x.azw3", "azw3"), ("x.epub", "epub"),
    ("x.cbz", "cbz"), ("x.cb7", "cb7"), ("x.mobi", "mobi"), ("x.azw", "azw"), ("x.fb2", "fb2"),
])
def test_book_formats(name, fmt):
    assert format_of(Path(name)) == fmt


@pytest.mark.parametrize("name", ["x.docx", "metadata.opf", "cover.jpg", "metadata.db", "noext", ".pdf", "passwords.txt"])
def test_not_books(name):
    assert format_of(Path(name)) is None


def test_txt_only_when_allowed():
    assert format_of(Path("notes.txt"), allow_txt=True) == "txt"
