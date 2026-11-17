import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from alcove import anilist, googlebooks, libsettings, lookups, openlibrary

KEY = "AIzaSyTestKey_0123456789abcdefghijkl"
VOLUME = {"id": "vOiCeS123", "volumeInfo": {
    "title": "Voices in the Dark", "authors": ["Junji Ito"], "publisher": "VIZ Media LLC",
    "publishedDate": "2025-10-21",
    "description": "<p>Seven <b>horror</b> stories &amp; more.</p><p>From the master of horror.</p>",
    "industryIdentifiers": [{"type": "ISBN_10", "identifier": "1974753123"},
                            {"type": "ISBN_13", "identifier": "9781974753123"}],
    "categories": ["Comics & Graphic Novels / Manga / Horror", "Comics & Graphic Novels / General"],
    "language": "en", "imageLinks": {"thumbnail": "http://books.google.com/books/content?id=vOiCeS123&zoom=1"}}}
BARE = {"id": "bare1", "volumeInfo": {"title": "Bare", "publishedDate": "2003-05-01T00:00:00Z"}}


def http_error(code):
    return urllib.error.HTTPError("https://www.googleapis.com/books/v1/volumes", code, "no", {}, None)


@pytest.fixture
def net(monkeypatch):
    sent = []
    answers = {"https://www.googleapis.com/": {"items": [VOLUME, BARE]},
               "https://openlibrary.org/": {"docs": [{"title": "Uzumaki"}]},
               "https://books.google.com/": b"JPEG"}

    def fake_get(url, limit):
        sent.append(url)
        for prefix, value in answers.items():
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return value if isinstance(value, bytes) else json.dumps(value).encode()
        raise AssertionError(url)

    monkeypatch.setattr(openlibrary, "_get", fake_get)
    monkeypatch.setattr(anilist, "_post", lambda *a: json.dumps({"data": {"Page": {"media": []}}}).encode())
    return sent, answers


def with_key(cfg, net):
    libsettings.update_library(cfg, {"google_books_key": KEY})
    net[0].clear()


def test_google_books_candidates(cfg, net):
    sent, _ = net
    with_key(cfg, net)
    found = googlebooks.search(cfg, title="Voices in the Dark", author="Junji Ito")
    assert found[0] == {
        "key": "", "source": "Google Books", "title": "Voices in the Dark", "authors": ["Junji Ito"],
        "published": "2025-10-21", "publisher": "VIZ Media LLC", "language": "en", "isbn": "9781974753123",
        "tags": ["Comics & Graphic Novels", "Manga", "Horror"],
        "description": "Seven horror stories & more.\n\nFrom the master of horror.",
        "cover_url": "https://books.google.com/books/content?id=vOiCeS123&printsec=frontcover&img=1&fife=w1200-h1800",
        "thumb_url": "https://books.google.com/books/content?id=vOiCeS123&printsec=frontcover&img=1&zoom=1",
    }
    assert found[1]["published"] == "2003-05-01" and found[1]["cover_url"] is None and found[1]["authors"] == []
    q = parse_qs(urlparse(sent[0]).query)
    assert q["q"] == ['intitle:"Voices in the Dark" inauthor:"Junji Ito"'] and q["key"] == [KEY]


def test_isbn_comes_first(cfg, net):
    sent, _ = net
    with_key(cfg, net)
    googlebooks.search(cfg, title="x", isbn="978-1-974753-12-3")
    assert parse_qs(urlparse(sent[0]).query)["q"] == ["isbn:9781974753123"]


@pytest.mark.parametrize("failure, message", [
    (http_error(400), "refused the key"), (http_error(403), "refused the key"),
    (http_error(429), "daily limit"), (OSError("down"), "didn’t answer"), (b"<html>", "didn’t answer"),
])
def test_google_books_failing(cfg, net, failure, message):
    _, answers = net
    with_key(cfg, net)
    answers["https://www.googleapis.com/"] = failure
    with pytest.raises(openlibrary.LookupFailed, match=message):
        googlebooks.search(cfg, title="x")


def test_without_a_key_google_books_isnt_asked(cfg, net):
    sent, _ = net
    assert [c["source"] for c in lookups.search(cfg, title="Uzumaki")] == ["Open Library"]
    assert not any("googleapis" in u for u in sent)


def test_with_a_key_google_books_comes_first(cfg, net):
    with_key(cfg, net)
    assert [c["source"] for c in lookups.search(cfg, title="Uzumaki")] == ["Google Books"] * 2 + ["Open Library"]


def test_when_both_fail_both_are_named(cfg, net, monkeypatch):
    _, answers = net
    with_key(cfg, net)
    monkeypatch.setattr(anilist, "_post", lambda *a: (_ for _ in ()).throw(OSError("down")))
    answers["https://www.googleapis.com/"] = OSError("down")
    answers["https://openlibrary.org/"] = OSError("down")
    with pytest.raises(openlibrary.LookupFailed, match="Google Books, Open Library and AniList didn’t answer"):
        lookups.search(cfg, title="Uzumaki", comic=True)


def test_saving_a_key_checks_it_and_never_shows_it(cfg, net):
    sent, answers = net
    lib = libsettings.update_library(cfg, {"google_books_key": f"  {KEY} "})
    assert lib["google_books"] is True and KEY not in json.dumps(lib)
    assert len(sent) == 1 and parse_qs(urlparse(sent[0]).query)["key"] == [KEY]
    assert googlebooks.key(cfg) == KEY

    answers["https://www.googleapis.com/"] = http_error(400)
    with pytest.raises(ValueError, match="refused"):
        libsettings.update_library(cfg, {"google_books_key": "AIzaSyAnotherKey_0123456789abcdefgh"})
    assert googlebooks.key(cfg) == KEY  # the old one stays
    with pytest.raises(ValueError, match="google_books_key"):
        libsettings.update_library(cfg, {"google_books_key": "not a key!"})

    assert libsettings.update_library(cfg, {"google_books_key": ""})["google_books"] is False
    assert googlebooks.key(cfg) == ""


def test_a_key_saved_while_lookups_are_off_isnt_checked(cfg, net):
    sent, _ = net
    libsettings.update_library(cfg, {"online_lookups": False, "google_books_key": KEY})
    assert sent == [] and googlebooks.key(cfg) == KEY


def test_covers_can_come_from_google_books(cfg, net):
    url = "https://books.google.com/books/content?id=vOiCeS123&printsec=frontcover&img=1&fife=w1200-h1800"
    assert openlibrary.fetch_cover(cfg, url) == b"JPEG"
    with pytest.raises(ValueError):
        openlibrary.fetch_cover(cfg, "https://books.google.com/url?q=https://evil.example/")


def test_the_key_stays_out_of_the_api(client, cfg, net):
    r = client.patch("/api/library", json={"google_books_key": KEY})
    assert r.status_code == 200 and r.json()["google_books"] is True
    assert KEY not in client.get("/api/library").text
    assert client.patch("/api/library", json={"google_books_key": 5}).status_code == 400
