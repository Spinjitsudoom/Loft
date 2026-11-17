import json
import socket
from urllib.parse import parse_qs, urlparse

import pytest

from alcove import libsettings, openlibrary
from alcove.filemeta import read_file_meta

FULL = {"key": "/works/OL45883W", "title": "The Long Way to a Small, Angry Planet",
        "author_name": ["Becky Chambers"], "first_publish_year": 2014, "publisher": ["Hodder", "Harper Voyager"],
        "language": ["eng"], "subject": [f"S{i}" for i in range(12)], "isbn": ["9781473619814", "1473619815"],
        "cover_i": 8233941}


@pytest.fixture
def calls(monkeypatch):
    seen = []
    responses = {}

    def fake_get(url, limit):
        seen.append(url)
        for prefix, body in responses.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise AssertionError(f"unexpected {url}")

    monkeypatch.setattr(openlibrary, "_get", fake_get)
    return seen, responses


def test_search_maps_candidates(cfg, calls):
    seen, responses = calls
    responses["https://openlibrary.org/search.json"] = {"docs": [FULL, {"title": "Bare"}]}
    found = openlibrary.search(cfg, title="Long Way", author="Chambers")
    assert found[0] == {"key": "/works/OL45883W", "title": "The Long Way to a Small, Angry Planet",
                        "authors": ["Becky Chambers"], "published": "2014", "publisher": "", "language": "eng",
                        "tags": [f"S{i}" for i in range(8)], "isbn": "9781473619814",
                        "cover_url": "https://covers.openlibrary.org/b/id/8233941-L.jpg?default=false"}
    one = openlibrary._candidate({"title": "One", "publisher": ["Tor"], "language": ["eng", "fre"]})
    assert one["publisher"] == "Tor" and one["language"] == ""
    assert found[1] == {"key": "", "title": "Bare", "authors": [], "published": "", "publisher": "", "language": "",
                        "tags": [], "isbn": "", "cover_url": None}
    q = parse_qs(urlparse(seen[0]).query)
    assert q["title"] == ["Long Way"] and q["author"] == ["Chambers"] and "isbn" not in q


def test_isbn_comes_first(cfg, calls):
    seen, responses = calls
    responses["https://openlibrary.org/search.json"] = {"docs": [FULL]}
    openlibrary.search(cfg, title="Long Way", isbn="978-1-4736-1981-4")
    q = parse_qs(urlparse(seen[0]).query)
    assert q["isbn"] == ["9781473619814"] and "title" not in q


def test_search_needs_something_to_look_for(cfg, calls):
    with pytest.raises(ValueError):
        openlibrary.search(cfg)


@pytest.mark.parametrize("body, want", [
    ({"description": "Plain."}, "Plain."),
    ({"description": {"type": "/type/text", "value": "Wrapped.\r\n\r\nTwo."}}, "Wrapped.\n\nTwo."),
    ({"title": "No blurb"}, ""),
])
def test_description(cfg, calls, body, want):
    _, responses = calls
    responses["https://openlibrary.org/works/OL45883W.json"] = body
    assert openlibrary.description(cfg, "/works/OL45883W") == want


def test_description_key_is_checked(cfg, calls):
    seen, _ = calls
    with pytest.raises(ValueError):
        openlibrary.description(cfg, "/../../admin")
    assert seen == []


@pytest.mark.parametrize("failure", [socket.timeout("timed out"), OSError("no route"), b"<html>Busy</html>"])
def test_open_library_failing(cfg, calls, failure):
    _, responses = calls
    responses["https://openlibrary.org/search.json"] = failure
    with pytest.raises(openlibrary.LookupFailed, match="didn’t answer"):
        openlibrary.search(cfg, title="x")


def test_lookups_off_sends_nothing(cfg, calls):
    seen, _ = calls
    libsettings.update_library(cfg, {"online_lookups": False})
    with pytest.raises(openlibrary.LookupsOff):
        openlibrary.search(cfg, title="x")
    with pytest.raises(openlibrary.LookupsOff):
        openlibrary.fetch_cover(cfg, "https://covers.openlibrary.org/b/id/1-L.jpg")
    assert seen == []


@pytest.mark.parametrize("url", ["http://169.254.169.254/latest", "https://evil.example/a.jpg",
                                 "http://covers.openlibrary.org/b/id/1-L.jpg",
                                 "https://covers.openlibrary.org.evil.example/x.jpg", "file:///etc/passwd"])
def test_covers_only_from_open_library(cfg, calls, url):
    seen, _ = calls
    with pytest.raises(ValueError):
        openlibrary.fetch_cover(cfg, url)
    assert seen == []


def test_fetch_cover(cfg, calls):
    _, responses = calls
    responses["https://covers.openlibrary.org/"] = b"JPEGDATA"
    assert openlibrary.fetch_cover(cfg, "https://covers.openlibrary.org/b/id/1-L.jpg?default=false") == b"JPEGDATA"


def test_epub_isbn(tmp_path, make_epub):
    import zipfile
    path = make_epub(tmp_path / "a.epub", title="T", author="A")
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    files["OEBPS/content.opf"] = files["OEBPS/content.opf"].replace(
        b"<dc:language>", b"<dc:identifier>urn:uuid:1234</dc:identifier>"
                          b"<dc:identifier>urn:isbn:9780141439518</dc:identifier><dc:language>")
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    assert read_file_meta(path, "epub").isbn == "9780141439518"


def test_lookup_routes(client, cfg, calls):
    from conftest import jpg
    from test_api import book_id
    _, responses = calls
    responses["https://openlibrary.org/search.json"] = {"docs": [FULL]}
    responses["https://openlibrary.org/works/"] = {"description": "Blurb"}
    responses["https://covers.openlibrary.org/"] = jpg((9, 9, 9), (300, 450))
    assert client.get("/api/lookup?title=Long").json()[0]["authors"] == ["Becky Chambers"]
    assert client.get("/api/lookup").status_code == 400
    assert client.get("/api/lookup/description?key=/works/OL45883W").json() == {"description": "Blurb"}
    assert client.get("/api/lookup/description?key=nope").status_code == 400
    bid = book_id(client, "Tale")
    r = client.post(f"/api/books/{bid}/cover/lookup", json={"url": "https://covers.openlibrary.org/b/id/1-L.jpg"})
    assert r.status_code == 200 and r.json()["has_cover"] is True
    assert client.post(f"/api/books/{bid}/cover/lookup", json={"url": "https://evil.example/x"}).status_code == 400
    responses["https://openlibrary.org/search.json"] = OSError("down")
    r = client.get("/api/lookup?title=Long")
    assert r.status_code == 502 and "by hand" in r.json()["detail"]
    client.patch("/api/library", json={"online_lookups": False})
    assert client.get("/api/lookup?title=Long").status_code == 403
