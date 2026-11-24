import io
import json
import urllib.error

import pytest

from loft import autofill, hardcover, isbndb, libsettings, lookups, openlibrary

HC_DOC = {"id": 1, "title": "Revelations", "subtitle": "", "author_names": ["Oliver Bowden"], "release_year": 2011,
          "isbns": ["0141046783", "9780141046785"], "genres": ["Fiction", "Historical"],
          "description": "<p>Ezio walks in the footsteps of Altaïr.</p>",
          "featured_series": {"position": 4, "series": {"name": "Assassin's Creed"}},
          "image": {"url": "https://assets.hardcover.app/edition/1/cover.jpg", "width": 400}}
ISBNDB_BOOK = {"title": "Uzumaki", "title_long": "Uzumaki (3-in-1 Deluxe Edition)", "isbn": "1421561328",
               "isbn13": "9781421561325", "authors": ["Ito, Junji"], "publisher": "VIZ Media",
               "language": "en", "date_published": "2013-10-15", "subjects": ["Comics & Graphic Novels / Manga / Horror"],
               "synopsis": "Kurouzu-cho, a small fogbound town…", "image": "https://images.isbndb.com/covers/13/25/9781421561325.jpg"}


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "no", {}, io.BytesIO(b""))


@pytest.fixture
def hc(monkeypatch, cfg):
    """Hardcover faked: answers["reply"] is what it gives back (a dict, or an exception)."""
    sent = []
    answers = {"reply": {"data": {"search": {"results": {"found": 1, "hits": [{"document": HC_DOC}]}}}}}

    def post(url, body, token, limit):
        sent.append((url, json.loads(body), token))
        if "books(" in json.loads(body)["query"]:        # the editions of the books found
            if isinstance(answers.get("editions"), Exception):
                raise answers["editions"]
            return json.dumps({"data": {"books": answers.get("editions") or []}}).encode()
        if isinstance(answers["reply"], Exception):
            raise answers["reply"]
        return json.dumps(answers["reply"]).encode()

    monkeypatch.setattr(hardcover, "_post", post)
    return sent, answers


@pytest.fixture
def idb(monkeypatch):
    sent = []
    answers = {"reply": {"books": [ISBNDB_BOOK]}}

    def get(url, key, limit):
        sent.append((url, key))
        reply = answers["reply"](url) if callable(answers["reply"]) else answers["reply"]
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply).encode()

    monkeypatch.setattr(isbndb, "_get", get)
    return sent, answers


TOKEN = "eyJhbGciOiJIUzI1NiJ9.abcdefghijklmnop.qrstuvwxyz"


def test_hardcover_matches_carry_the_series(cfg, hc):
    sent, _ = hc
    libsettings.update_library(cfg, {"hardcover_token": f"Bearer {TOKEN}"})  # pasted as Hardcover shows it
    assert libsettings.hardcover_token(cfg) == TOKEN
    sent.clear()
    found = hardcover.search(cfg, title="Revelations", author="Oliver Bowden")
    assert found == [{
        "key": "", "source": "Hardcover", "title": "Revelations", "authors": ["Oliver Bowden"], "published": "2011",
        "publisher": "", "language": "", "isbn": "9780141046785", "tags": ["Fiction", "Historical"],
        "description": "Ezio walks in the footsteps of Altaïr.", "series": "Assassin's Creed", "series_index": 4.0,
        "cover_url": "https://assets.hardcover.app/edition/1/cover.jpg",
        "thumb_url": "https://assets.hardcover.app/edition/1/cover.jpg"}]
    url, body, token = sent[0]
    assert url == "https://api.hardcover.app/v1/graphql" and token == TOKEN
    assert body["variables"] == {"q": "Revelations Oliver Bowden", "n": 6} and 'query_type: "Book"' in body["query"]


def test_hardcover_says_series_other_ways_and_drops_odd_covers(cfg, hc):
    doc = {"title": "Uzumaki", "author_names": ["Junji Ito"], "series_names": ["Uzumaki"],
           "featured_series_position": 1, "image": {"url": "https://elsewhere.example/x.jpg"}}
    c = hardcover._candidate(doc)
    assert (c["series"], c["series_index"], c["cover_url"]) == ("Uzumaki", 1.0, None)
    c = hardcover._candidate({"title": "X", "series_names": ["A", "B"], "featured_series_position": "1"})
    assert (c["series"], c["series_index"]) == ("", None)


@pytest.mark.parametrize("failure, message", [(http_error(401), "refused"), (http_error(429), "limit"),
                                              (http_error(500), "didn’t answer"), (OSError("down"), "didn’t answer")])
def test_hardcover_failing(cfg, hc, failure, message):
    _, answers = hc
    libsettings.update_library(cfg, {"hardcover_token": TOKEN})
    answers["reply"] = failure
    with pytest.raises(openlibrary.LookupFailed, match=message):
        hardcover.search(cfg, title="x")


def test_a_hardcover_token_is_checked_before_it_is_saved(cfg, hc):
    _, answers = hc
    answers["reply"] = http_error(401)
    with pytest.raises(ValueError, match="refused that token"):
        libsettings.update_library(cfg, {"hardcover_token": TOKEN})
    assert libsettings.get_library(cfg)["hardcover"] is False
    with pytest.raises(ValueError, match="doesn’t look right"):
        libsettings.update_library(cfg, {"hardcover_token": "has spaces in it"})


def test_isbndb_finds_the_plan_its_key_works_at(cfg, idb):
    sent, answers = idb
    answers["reply"] = lambda url: http_error(403) if "api2" in url else {"book": ISBNDB_BOOK}
    lib = libsettings.update_library(cfg, {"isbndb_key": "12345_abcdefghij"})
    assert lib["isbndb"] is True and "isbndb_key" not in lib and "isbndb_host" not in lib
    assert libsettings.isbndb_key(cfg) == ("12345_abcdefghij", "https://api.premium.isbndb.com")
    assert [u for u, _ in sent] == ["https://api2.isbndb.com/book/9780140328721",
                                    "https://api.premium.isbndb.com/book/9780140328721"]
    answers["reply"] = http_error(401)
    with pytest.raises(ValueError, match="refused that key"):
        libsettings.update_library(cfg, {"isbndb_key": "67890_abcdefghij"})
    libsettings.update_library(cfg, {"isbndb_key": ""})
    assert libsettings.isbndb_key(cfg) == ("", "")


def test_isbndb_matches(cfg, idb):
    sent, answers = idb
    answers["reply"] = {"book": ISBNDB_BOOK}
    libsettings.update_library(cfg, {"isbndb_key": "12345_abcdefghij"})
    other = {**ISBNDB_BOOK, "title": "Uzumaki", "authors": ["Someone Else"], "image": "https://evil.example/x.jpg"}
    answers["reply"] = {"total": 2, "books": [other, ISBNDB_BOOK]}
    sent.clear()
    found = isbndb.search(cfg, title="Uzumaki", author="Junji Ito")
    assert sent[0][0] == "https://api2.isbndb.com/books/Uzumaki?page=1&pageSize=20&column=title"
    assert sent[0][1] == "12345_abcdefghij"
    assert found[0] == {"key": "", "source": "ISBNdb", "title": "Uzumaki", "authors": ["Ito, Junji"],
                        "published": "2013-10-15", "publisher": "VIZ Media", "language": "en", "isbn": "9781421561325",
                        "tags": ["Comics & Graphic Novels", "Manga", "Horror"],
                        "description": "Kurouzu-cho, a small fogbound town…",
                        "cover_url": "https://images.isbndb.com/covers/13/25/9781421561325.jpg",
                        "thumb_url": "https://images.isbndb.com/covers/13/25/9781421561325.jpg"}
    assert found[1]["authors"] == ["Someone Else"] and found[1]["cover_url"] is None
    answers["reply"] = {"book": ISBNDB_BOOK}
    assert isbndb.search(cfg, isbn="978-1-4215-6132-5")[0]["title"] == "Uzumaki"
    assert sent[-1][0] == "https://api2.isbndb.com/book/9781421561325"
    answers["reply"] = http_error(404)
    assert isbndb.search(cfg, title="Nothing at all") == []
    answers["reply"] = http_error(403)
    with pytest.raises(openlibrary.LookupFailed, match="refused"):
        isbndb.search(cfg, title="x")


def test_lookups_ask_every_source_with_a_key_hardcover_first(cfg, hc, idb, monkeypatch):
    _, answers = idb
    answers["reply"] = {"book": ISBNDB_BOOK}
    libsettings.update_library(cfg, {"hardcover_token": TOKEN, "isbndb_key": "12345_abcdefghij"})
    answers["reply"] = {"books": [ISBNDB_BOOK]}
    monkeypatch.setattr(openlibrary, "_get", lambda url, limit: json.dumps({"docs": []}).encode())
    found = lookups.search(cfg, title="Revelations")
    assert [c["source"] for c in found] == ["Hardcover", "ISBNdb"]
    # Switched off, none of them is asked.
    libsettings.update_library(cfg, {"online_lookups": False})
    with pytest.raises(openlibrary.LookupsOff):
        lookups.search(cfg, title="Revelations")


def test_covers_from_hardcover_and_isbndb_can_be_fetched(cfg, monkeypatch):
    monkeypatch.setattr(openlibrary, "_get", lambda url, limit: b"JPEG")
    assert openlibrary.fetch_cover(cfg, "https://assets.hardcover.app/edition/1/cover.jpg") == b"JPEG"
    assert openlibrary.fetch_cover(cfg, "https://images.isbndb.com/covers/13/25/9781421561325.jpg") == b"JPEG"
    with pytest.raises(ValueError):
        openlibrary.fetch_cover(cfg, "http://images.isbndb.com/covers/x.jpg")


def test_a_new_book_takes_the_series_hardcover_gives(cfg, add, monkeypatch):
    monkeypatch.setattr(lookups, "search", lambda c, **q: [hardcover._candidate(HC_DOC)])
    monkeypatch.setattr(openlibrary, "fetch_cover", lambda c, url: b"")
    autofill._enqueue(cfg)
    bid = add("Revelations", authors=["Oliver Bowden"])
    autofill.run(cfg, pause=0)
    from loft.db import session
    with session(cfg.db_path) as con:
        b = con.execute("SELECT * FROM books WHERE id = ?", (bid,)).fetchone()
    assert (b["series"], b["series_index"]) == ("Assassin's Creed", 4.0)
    assert b["description"] == "Ezio walks in the footsteps of Altaïr."


def test_the_app_never_gets_the_token_or_key_back(client, hc, idb):
    _, answers = idb
    answers["reply"] = {"book": ISBNDB_BOOK}
    r = client.patch("/api/library", json={"hardcover_token": TOKEN, "isbndb_key": "12345_abcdefghij"})
    assert r.status_code == 200, r.text
    body = r.text + client.get("/api/library").text
    assert TOKEN not in body and "12345_abcdefghij" not in body and "isbndb_host" not in body
    assert r.json()["hardcover"] is True and r.json()["isbndb"] is True


def edition(publisher=None, language=None):
    return {"publisher": {"name": publisher} if publisher else None, "language": {"code2": language} if language else None}


def test_hardcover_matches_bring_their_editions_publisher(cfg, hc):
    # The search index has no publisher; one more question asks for the books' default editions.
    sent, answers = hc
    libsettings.update_library(cfg, {"hardcover_token": TOKEN})
    answers["editions"] = [{"id": int(HC_DOC["id"]), "default_ebook_edition": edition("Penguin Books", "en"),
                            "default_physical_edition": edition("Penguin", "sk")}]
    found = hardcover.search(cfg, title="Revelations", author="Oliver Bowden")
    assert (found[0]["publisher"], found[0]["language"]) == ("Penguin Books", "en")   # the ebook first
    assert sent[-1][1]["variables"] == {"ids": [int(HC_DOC["id"])]} and sent[-1][2] == TOKEN
    answers["editions"] = [{"id": int(HC_DOC["id"]), "default_ebook_edition": edition(None, "nl"),
                            "default_physical_edition": edition("Penguin", "en")}]
    found = hardcover.search(cfg, title="Revelations", author="Oliver Bowden")
    assert (found[0]["publisher"], found[0]["language"]) == ("Penguin", "en")         # else the print edition


@pytest.mark.parametrize("trouble", [http_error(500), OSError("down"), [{"id": "nonsense"}]])
def test_hardcover_matches_come_without_a_publisher_when_editions_fail(cfg, hc, trouble):
    _, answers = hc
    libsettings.update_library(cfg, {"hardcover_token": TOKEN})
    answers["editions"] = trouble
    found = hardcover.search(cfg, title="Revelations", author="Oliver Bowden")
    assert found[0]["title"] == "Revelations" and found[0]["publisher"] == ""
