"""Asking for books: anyone asks, others vote, an admin adds it (or says why not)."""
import pytest

from alcove import auth, notifications
from alcove import book_requests as requests
from test_members import member


@pytest.fixture
def people(cfg):
    return (auth.create_user(cfg, "ann", "annannann", admin=True), auth.create_user(cfg, "sam", "samsamsam"),
            auth.create_user(cfg, "bob", "bobbobbob"))


def test_asking_and_voting(cfg, people):
    admin, sam, bob = people
    first = requests.ask(cfg, sam, "  Gyo  ", "Junji Ito", "the fish one")
    second = requests.ask(cfg, bob, "Tomie")
    assert notifications.list_for(cfg, admin.id)["unread"] == 2
    requests.vote(cfg, bob.id, second, False)  # the asker's own vote can be taken back too
    requests.vote(cfg, sam.id, second, True)
    requests.vote(cfg, bob.id, first, True)
    requests.vote(cfg, bob.id, first, True)    # once each
    seen = requests.listing(cfg, bob.id)
    assert [(r["title"], r["votes"], r["voted"], r["mine"]) for r in seen] == [
        ("Gyo", 2, True, False), ("Tomie", 1, False, True)]
    assert seen[0]["by"] == "sam" and seen[0]["author"] == "Junji Ito" and seen[0]["note"] == "the fish one"


def test_the_same_book_twice(cfg, people):
    _, sam, bob = people
    requests.ask(cfg, sam, "Gyo")
    with pytest.raises(ValueError, match="vote"):
        requests.ask(cfg, bob, "gyo ")
    with pytest.raises(ValueError):
        requests.ask(cfg, bob, "   ")


def test_adding_the_book_tells_everyone_who_wanted_it(cfg, people, add):
    admin, sam, bob = people
    rid = requests.ask(cfg, sam, "Gyo")
    requests.vote(cfg, bob.id, rid, True)
    book = add("Gyo", ["Junji Ito"])
    requests.fulfil(cfg, rid, book)
    for who in (sam, bob):
        told = notifications.list_for(cfg, who.id)["items"][0]
        assert told["kind"] == "request_added" and told["link"] == f"#/book/{book}"
    assert requests.listing(cfg, sam.id) == []
    done = requests.listing(cfg, sam.id, closed=True)[0]
    assert done["status"] == "added" and done["book_id"] == book
    with pytest.raises(ValueError):
        requests.fulfil(cfg, rid, book)
    with pytest.raises(LookupError):
        requests.fulfil(cfg, requests.ask(cfg, sam, "Tomie"), 99999)


def test_declining_and_taking_back(cfg, people):
    _, sam, bob = people
    rid = requests.ask(cfg, sam, "Gyo")
    requests.decline(cfg, rid, "Not out in English yet")
    assert "Not out in English yet" in notifications.list_for(cfg, sam.id)["items"][0]["text"]
    assert requests.listing(cfg, sam.id, closed=True)[0]["reason"] == "Not out in English yet"
    other = requests.ask(cfg, sam, "Tomie")
    with pytest.raises(LookupError):
        requests.remove(cfg, bob, other)
    requests.remove(cfg, sam, other)
    assert requests.listing(cfg, sam.id) == []


def test_request_routes(client, add):
    sam = member(client)
    r = sam.post("/api/requests", json={"title": "Gyo", "author": "Junji Ito"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert client.post(f"/api/requests/{rid}/vote", json={"on": True}).status_code == 200
    assert [x["votes"] for x in sam.get("/api/requests").json()] == [2]
    assert sam.post(f"/api/requests/{rid}/fulfil", json={"book_id": 1}).status_code == 403
    book = add("Gyo", ["Junji Ito"])
    assert client.post(f"/api/requests/{rid}/fulfil", json={"book_id": book}).status_code == 200
    assert sam.get("/api/requests?closed=true").json()[0]["status"] == "added"
    assert sam.post("/api/requests", json={"title": ""}).status_code == 400


def test_finished_requests_can_be_cleared_away(cfg, people, add):
    admin, sam, bob = people
    added = requests.ask(cfg, sam, "Gyo")
    requests.fulfil(cfg, added, add("Gyo"))
    declined = requests.ask(cfg, sam, "Tomie")
    requests.decline(cfg, declined, "")
    with pytest.raises(LookupError):
        requests.remove(cfg, bob, added)          # not someone else's
    requests.remove(cfg, sam, declined)           # the asker can
    requests.remove(cfg, admin, added)            # an admin can
    assert requests.listing(cfg, sam.id, closed=True) == []
