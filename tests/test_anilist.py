import json
import socket

import pytest

from alcove import anilist, libsettings, lookups, openlibrary

VOICES = {
    "id": 3126, "title": {"romaji": "Yami no Koe", "english": "Voices in the Dark"}, "startDate": {"year": 2003},
    "description": "Horror comic in 7 stories:<br>\nStory 1: Blood-sucking Darkness<br>Story 2: The Ghosts &amp; Golden Time"
                   "<br><br>\n(Source: daniel-lau.com)<br><br>\n<i>Chapter 5 was adapted in episode 10 of the anime.</i>",
    "genres": ["Horror", "Mystery", "Supernatural", "A", "B", "C", "D", "E", "F"],
    "coverImage": {"extraLarge": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx3126.jpg",
                   "large": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx3126.jpg"},
    "staff": {"edges": [{"role": "Story & Art", "node": {"name": {"full": "Junji Itou"}}},
                        {"role": "Translator (Spanish)", "node": {"name": {"full": "Ana Caro"}}}]},
}
OTHER = {"id": 9, "title": {"romaji": "Yami no Koe Gaiden", "english": None}, "startDate": {"year": None},
         "description": None, "genres": [], "coverImage": {"extraLarge": None, "large": None},
         "staff": {"edges": [{"role": "Story", "node": {"name": {"full": "Someone Else"}}},
                             {"role": "Art", "node": {"name": {"full": "An Artist"}}},
                             {"role": "Assistant", "node": {"name": {"full": "A Helper"}}}]}}


def page(*media):
    return {"data": {"Page": {"media": list(media)}}}


OL_DOC = {"key": "/works/OL1W", "title": "Uzumaki", "author_name": ["Junji Ito"]}


@pytest.fixture
def net(monkeypatch):
    """Both services faked: answers[name] is a reply, an exception, or a list of AniList pages."""
    sent = {"openlibrary": [], "anilist": []}
    answers = {"openlibrary": {"docs": []}, "anilist": page(), "cover": b"JPEG"}

    def reply(name):
        value = answers[name]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, bytes) else json.dumps(value).encode()

    def fake_get(url, limit):
        if url.startswith("https://openlibrary.org/"):
            sent["openlibrary"].append(url)
            return reply("openlibrary")
        sent["cover"] = url
        return reply("cover")

    def fake_post(url, body, limit):
        assert url == "https://graphql.anilist.co"
        sent["anilist"].append(json.loads(body))
        return reply("anilist")

    monkeypatch.setattr(openlibrary, "_get", fake_get)
    monkeypatch.setattr(anilist, "_post", fake_post)
    return sent, answers


def test_anilist_candidates(cfg, net):
    sent, answers = net
    answers["anilist"] = page(VOICES, OTHER)
    found = anilist.search(cfg, title="Voices in the Dark", author="Junji Ito")
    assert found[0] == {
        "key": "", "source": "AniList", "title": "Voices in the Dark", "authors": ["Junji Itou"], "published": "2003",
        "publisher": "", "language": "", "isbn": "",
        "tags": ["Horror", "Mystery", "Supernatural", "A", "B", "C", "D", "E"],
        "description": "Horror comic in 7 stories:\nStory 1: Blood-sucking Darkness\nStory 2: The Ghosts & Golden Time",
        "cover_url": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx3126.jpg",
        "thumb_url": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx3126.jpg",
    }
    assert found[1]["title"] == "Yami no Koe Gaiden" and found[1]["authors"] == ["Someone Else", "An Artist"]
    assert found[1]["published"] == "" and found[1]["cover_url"] is None and found[1]["description"] == ""
    # Only the title goes to AniList, and adult-only entries are left out.
    request = sent["anilist"][0]
    assert request["variables"] == {"search": "Voices in the Dark"}
    assert "isAdult: false" in request["query"]


def test_the_author_given_comes_first(cfg, net):
    _, answers = net
    answers["anilist"] = page(OTHER, VOICES)
    found = anilist.search(cfg, title="Voices in the Dark", author="Junji Ito")
    assert [c["title"] for c in found] == ["Voices in the Dark", "Yami no Koe Gaiden"]


@pytest.mark.parametrize("failure", [socket.timeout("timed out"), OSError("down"), b"<html>Busy</html>",
                                     {"errors": [{"message": "Too Many Requests"}], "data": None}])
def test_anilist_failing(cfg, net, failure):
    _, answers = net
    answers["anilist"] = failure
    with pytest.raises(openlibrary.LookupFailed, match="AniList didn’t answer"):
        anilist.search(cfg, title="x")


def test_anilist_needs_a_title_and_respects_lookups_off(cfg, net):
    sent, _ = net
    with pytest.raises(ValueError):
        anilist.search(cfg, title="  ")
    libsettings.update_library(cfg, {"online_lookups": False})
    with pytest.raises(openlibrary.LookupsOff):
        anilist.search(cfg, title="x")
    assert sent["anilist"] == []


def test_comics_ask_both(cfg, net):
    sent, answers = net
    answers["openlibrary"] = {"docs": [OL_DOC]}
    answers["anilist"] = page(VOICES)
    found = lookups.search(cfg, title="Uzumaki", author="Junji Ito", comic=True)
    assert [c["source"] for c in found] == ["Open Library", "AniList"]


def test_other_books_ask_anilist_only_when_open_library_has_nothing(cfg, net):
    sent, answers = net
    answers["openlibrary"] = {"docs": [OL_DOC]}
    assert [c["source"] for c in lookups.search(cfg, title="Uzumaki")] == ["Open Library"]
    assert sent["anilist"] == []
    answers["openlibrary"] = {"docs": []}
    answers["anilist"] = page(VOICES)
    assert [c["source"] for c in lookups.search(cfg, title="Voices in the Dark")] == ["AniList"]


def test_one_service_down_still_gives_the_others_matches(cfg, net):
    _, answers = net
    answers["openlibrary"] = OSError("down")
    answers["anilist"] = page(VOICES)
    assert [c["source"] for c in lookups.search(cfg, title="Voices in the Dark", comic=True)] == ["AniList"]
    answers["openlibrary"] = {"docs": [OL_DOC]}
    answers["anilist"] = OSError("down")
    assert [c["source"] for c in lookups.search(cfg, title="Uzumaki", comic=True)] == ["Open Library"]


def test_a_service_down_is_said_rather_than_no_match(cfg, net):
    _, answers = net
    answers["anilist"] = OSError("down")
    with pytest.raises(openlibrary.LookupFailed, match="AniList didn’t answer"):
        lookups.search(cfg, title="Voices in the Dark")
    answers["openlibrary"] = OSError("down")
    with pytest.raises(openlibrary.LookupFailed, match="Open Library and AniList didn’t answer"):
        lookups.search(cfg, title="Voices in the Dark")
    answers["anilist"] = page()
    with pytest.raises(openlibrary.LookupFailed, match="Open Library didn’t answer"):
        lookups.search(cfg, title="Voices in the Dark")


def test_an_isbn_alone_isnt_sent_to_anilist(cfg, net):
    sent, _ = net
    assert lookups.search(cfg, isbn="9781421561325", comic=True) == []
    assert sent["anilist"] == [] and len(sent["openlibrary"]) == 1


def test_covers_can_come_from_anilist(cfg, net):
    sent, _ = net
    url = "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx3126.jpg"
    assert openlibrary.fetch_cover(cfg, url) == b"JPEG" and sent["cover"] == url
    for bad in ("https://s4.anilist.co/elsewhere/x.jpg", "https://anilist.co/file/anilistcdn/x.jpg",
                "http://s4.anilist.co/file/anilistcdn/x.jpg"):
        with pytest.raises(ValueError):
            openlibrary.fetch_cover(cfg, bad)


def test_lookup_route_asks_anilist_for_comics(client, cfg, net):
    sent, answers = net
    answers["openlibrary"] = {"docs": [OL_DOC]}
    answers["anilist"] = page(VOICES)
    assert [c["source"] for c in client.get("/api/lookup?title=Uzumaki").json()] == ["Open Library"]
    r = client.get("/api/lookup?title=Uzumaki&comic=true")
    assert [c["source"] for c in r.json()] == ["Open Library", "AniList"]
    answers["openlibrary"] = OSError("down")
    answers["anilist"] = OSError("down")
    r = client.get("/api/lookup?title=Uzumaki&comic=true")
    assert r.status_code == 502 and "by hand" in r.json()["detail"]
