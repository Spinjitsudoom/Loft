import json

import pytest

from loft import autofill, editing, libsettings, lookups, openlibrary
from loft.db import session
from loft.titles import search_title, series_from_title


def test_titles_are_tidied_like_the_web_app_does():
    assert search_title("#04 Assassin's Creed - Revelations") == "Assassin's Creed: Revelations"
    assert search_title("Avatar_ The Last Airbender - The Sea (90)") == "Avatar: The Last Airbender: The Sea"
    assert search_title("12 - Brotherhood") == "Brotherhood"
    assert search_title("1984") == "1984"
    assert search_title("Fahrenheit 451") == "Fahrenheit 451"


def test_series_from_titles_like_the_web_app_does():
    assert series_from_title("#04 Assassin's Creed - Revelation") == ("Assassin's Creed", 4)
    assert series_from_title("Assassin's Creed Book 4") == ("Assassin's Creed", 4)
    assert series_from_title("Uprising #8") == ("Uprising", 8)
    assert series_from_title("Geronimo Stilton, Vol. 2: Cat and Mouse") == ("Geronimo Stilton", 2)
    assert series_from_title("Rumble in the Jungle (Geronimo Stilton #53)") == ("Geronimo Stilton", 53)
    for title in ("Fahrenheit 451", "Catch-22", "Assassin's Creed: Brotherhood", "1984"):
        assert series_from_title(title) is None


def c(title, authors=(), source="Google Books", **more):
    return {"source": source, "key": "", "title": title, "authors": list(authors), "published": "", "publisher": "",
            "language": "en", "isbn": "", "tags": [], "description": "", "cover_url": None, **more}


@pytest.mark.parametrize("book, cand, sure", [
    # Same title, same author (spelt another way): sure.
    (("Voices in the Dark", ["Junji Ito"]), c("Voices in the Dark", ["Junji Itou"]), True),
    (("Uzumaki", ["Ito, Junji"]), c("Uzumaki", ["Junji Ito"]), True),
    # Same title, someone else's: not this book.
    (("Uzumaki", ["Junji Ito"]), c("Uzumaki", ["Somebody Else"]), False),
    # Close enough titles (a letter apart), the author agreeing.
    (("Assassin's Creed: Revelation", ["Oliver Bowden"]), c("Assassin's Creed: Revelations", ["Oliver Bowden"]), True),
    # Different books.
    (("Brotherhood", ["Oliver Bowden"]), c("Renaissance", ["Oliver Bowden"]), False),
    (("Assassin's Creed: Brotherhood", ["Oliver Bowden"]), c("Assassin's Creed: Unity", ["Oliver Bowden"]), False),
    (("Assassin's Creed: The Fall #1", ["Karl Kerschl"]), c("Assassin's Creed: The Fall #2", ["Karl Kerschl"]), False),
    # The series said another way round.
    (("Geronimo Stilton #53: Rumble in the Jungle", ["Geronimo Stilton"]),
     c("Rumble in the Jungle (Geronimo Stilton #53)", ["Geronimo Stilton"]), True),
    (("Mighty Mount Kilimanjaro", ["Geronimo Stilton"]), c("Mighty Mount Kilimanjaro #41", ["Geronimo Stilton"]), True),
    # No author known: the whole title has to match, by someone.
    (("The Left Hand of Darkness", []), c("The Left Hand of Darkness", ["Ursula K. Le Guin"]), True),
    (("The Left Hand of Darkness", []), c("The Left Hand of Darkness", []), False),
    # ...a part title alone only when the match says it's in that series.
    (("#04 Assassin's Creed - Revelation", []), c("Revelations", ["Oliver Bowden"]), False),
    (("#04 Assassin's Creed - Revelation", []),
     c("Revelations", ["Oliver Bowden"], description="Assassin's Creed: Revelations is the novelisation…"), True),
])
def test_only_a_sure_match_is_used(book, cand, sure):
    title, authors = book
    assert autofill.is_sure(title, authors, cand) is sure


@pytest.fixture
def online(monkeypatch, cfg):
    """lookups.search answers from `answers` (a list of matches, or an exception); covers are tiny JPEGs."""
    from conftest import png
    asked = []
    answers = {"found": []}

    def search(c, **q):
        asked.append(q)
        value = answers["found"]
        if isinstance(value, Exception):
            raise value
        return [dict(x) for x in value]

    monkeypatch.setattr(lookups, "search", search)
    monkeypatch.setattr(openlibrary, "fetch_cover", lambda c, url: png((200, 30, 30), (60, 90)))
    autofill._enqueue(cfg)  # the library starts empty: nothing put aside
    return asked, answers


def book(cfg, book_id):
    with session(cfg.db_path) as con:
        return dict(con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone())


def state(cfg, book_id):
    with session(cfg.db_path) as con:
        return con.execute("SELECT state FROM autofill WHERE book_id = ?", (book_id,)).fetchone()["state"]


MATCH = c("Uzumaki", ["Junji Ito"], tags=["Horror", "Manga"], description="A town haunted by spirals.",
          publisher="VIZ", published="2013", cover_url="https://covers.openlibrary.org/b/id/1-L.jpg")


def test_a_new_book_is_filled_in_from_a_sure_match(cfg, add, online):
    asked, answers = online
    answers["found"] = [c("Uzumaki", ["Someone Else"], description="Not it."), MATCH]
    bid = add("Uzumaki", authors=["Junji Ito"])
    assert autofill.run(cfg, pause=0) == 1
    b = book(cfg, bid)
    assert b["description"] == "A town haunted by spirals." and json.loads(b["tags"]) == ["Horror", "Manga"]
    assert b["publisher"] == "VIZ" and b["published"] == "2013" and b["has_cover"] == 1
    # Filled in like the admin had: scans of a changed file leave it.
    assert {"description", "tags", "publisher", "cover"} <= set(json.loads(b["locked"]))
    assert asked[0]["title"] == "Uzumaki" and asked[0]["author"] == "Junji Ito"
    assert state(cfg, bid) == "filled"
    # Admins hear about it.
    with session(cfg.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0  # no one to tell yet: fine
    over = autofill.overview(cfg)
    assert over["filled"][0]["book"]["id"] == bid and over["filled"][0]["sources"] == ["Google Books"]
    assert set(over["filled"][0]["fields"]) == {"description", "tags", "publisher", "published", "language", "cover"}


def test_nothing_already_there_changes(cfg, add, online):
    _, answers = online
    answers["found"] = [MATCH]
    bid = add("Uzumaki", authors=["Junji Ito"], tags=["Mine"], description="My words.")
    editing.edit_book(cfg, bid, {"publisher": ""})  # the admin cleared it on purpose
    autofill.run(cfg, pause=0)
    b = book(cfg, bid)
    assert b["description"] == "My words." and json.loads(b["tags"]) == ["Mine"] and b["publisher"] == ""


def test_without_a_sure_match_nothing_changes(cfg, add, online):
    _, answers = online
    answers["found"] = [c("Uzumaki", ["Someone Else"], description="Not it.")]
    bid = add("Uzumaki", authors=["Junji Ito"])
    assert autofill.run(cfg, pause=0) == 0
    assert book(cfg, bid)["description"] == "" and state(cfg, bid) == "unsure"
    assert [b["id"] for b in autofill.overview(cfg)["unsure"]] == [bid]


def test_a_file_name_title_gets_the_real_one_and_its_series(cfg, add, online):
    _, answers = online
    answers["found"] = [c("Revelations", ["Oliver Bowden"],
                          description="Assassin's Creed: Revelations is the novelisation of the game.")]
    bid = add("#04 Assassin's Creed - Revelation", authors=[])
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET title_from_name = 1 WHERE id = ?", (bid,))
    autofill.run(cfg, pause=0)
    b = book(cfg, bid)
    assert b["title"] == "Revelations" and json.loads(b["authors"]) == ["Oliver Bowden"]
    assert b["series"] == "Assassin's Creed" and b["series_index"] == 4


def test_a_number_on_the_match_alone_isnt_a_series(cfg, add, online):
    _, answers = online
    answers["found"] = [c("Mighty Mount Kilimanjaro #41", ["Geronimo Stilton"], description="Up we go.")]
    bid = add("Mighty Mount Kilimanjaro", authors=["Geronimo Stilton"])
    autofill.run(cfg, pause=0)
    b = book(cfg, bid)
    assert b["description"] == "Up we go." and b["series"] == ""
    answers["found"] = [c("Rumble in the Jungle (Geronimo Stilton #53)", ["Geronimo Stilton"], description="Roar.")]
    bid = add("Rumble in the Jungle", authors=["Geronimo Stilton"])
    autofill.run(cfg, pause=0)
    b = book(cfg, bid)
    assert b["series"] == "Geronimo Stilton" and b["series_index"] == 53


def test_books_already_there_wait_for_the_admin(cfg, add, monkeypatch):
    monkeypatch.setattr(lookups, "search", lambda c, **q: [dict(MATCH)])
    monkeypatch.setattr(openlibrary, "fetch_cover", lambda c, url: b"")
    old = add("Uzumaki", authors=["Junji Ito"])
    assert autofill.run(cfg, pause=0) == 0          # the first run puts them aside
    assert state(cfg, old) == "before" and autofill.overview(cfg)["before"] == 1
    new = add("Uzumaki", authors=["Junji Ito"])
    assert autofill.run(cfg, pause=0) == 1 and state(cfg, new) == "filled"
    assert autofill.look_up_the_rest(cfg) == 1
    assert autofill.run(cfg, pause=0) == 1 and state(cfg, old) == "filled"


def test_switched_off_nothing_is_looked_up(cfg, add, online):
    asked, _ = online
    add("Uzumaki", authors=["Junji Ito"])
    libsettings.update_library(cfg, {"auto_lookup": False})
    assert autofill.run(cfg, pause=0) == 0 and asked == []
    libsettings.update_library(cfg, {"auto_lookup": True, "online_lookups": False})
    assert autofill.run(cfg, pause=0) == 0 and asked == []


def test_a_service_down_is_tried_again_on_later_scans(cfg, add, online):
    _, answers = online
    answers["found"] = openlibrary.LookupFailed("down")
    bid = add("Uzumaki", authors=["Junji Ito"])
    autofill.run(cfg, pause=0)
    assert state(cfg, bid) == "waiting"           # stays queued...
    autofill.run(cfg, pause=0)
    autofill.run(cfg, pause=0)
    assert state(cfg, bid) == "unsure"            # ...three times at most


def test_a_book_with_everything_isnt_looked_up(cfg, add, online, make_pdf):
    asked, _ = online
    bid = add("Full", tags=["x"], description="d")
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET has_cover = 1 WHERE id = ?", (bid,))
    autofill.run(cfg, pause=0)
    assert asked == [] and state(cfg, bid) == "complete"


def test_undo_puts_the_book_back(cfg, add, online):
    _, answers = online
    answers["found"] = [MATCH]
    bid = add("Uzumaki", authors=["Junji Ito"])
    autofill.run(cfg, pause=0)
    editing.edit_book(cfg, bid, {"publisher": "Kept"})   # changed since: stays
    autofill.undo(cfg, bid)
    b = book(cfg, bid)
    assert b["description"] == "" and json.loads(b["tags"]) == [] and b["has_cover"] == 0
    assert b["publisher"] == "Kept"
    assert json.loads(b["locked"]) == ["publisher"]
    assert state(cfg, bid) == "undone"
    autofill.run(cfg, pause=0)
    assert book(cfg, bid)["description"] == ""          # not looked up by itself again
    with pytest.raises(LookupError):
        autofill.undo(cfg, bid)


def test_admins_are_told_and_can_undo_from_the_app(client, cfg, online):
    _, answers = online
    answers["found"] = [c("Tide Line", ["Someone"], description="Waves.")]
    r = client.get("/api/library")
    assert r.json()["auto_lookup"] is True
    with session(cfg.db_path) as con:
        bid = con.execute("SELECT id FROM books WHERE title = 'Tide Line'").fetchone()["id"]
        con.execute("UPDATE autofill SET state = 'waiting'")  # as if just added
        con.execute("UPDATE books SET authors = '[]' WHERE id = ?", (bid,))
    autofill.run(cfg, pause=0)
    note = client.get("/api/notifications").json()["items"][0]
    assert note["link"] == "#/filled" and "Filled in details for" in note["text"]
    over = client.get("/api/autofill").json()
    assert bid in [f["book"]["id"] for f in over["filled"]]
    assert client.post(f"/api/autofill/{bid}/undo").status_code == 200
    assert client.post(f"/api/autofill/{bid}/undo").status_code == 404
    r = client.post("/api/autofill/rest")
    assert r.status_code == 202 and "queued" in r.json()
