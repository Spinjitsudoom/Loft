"""Talking about a book without spoiling it: messages from further ahead than you are marked."""
import pytest

from alcove import auth, discussion, notifications, reading
from test_members import member


@pytest.fixture
def people(cfg):
    return (auth.create_user(cfg, "ann", "annannann", admin=True), auth.create_user(cfg, "sam", "samsamsam"),
            auth.create_user(cfg, "bob", "bobbobbob"))


def at(cfg, user, book, page, pages=100):
    reading.save_progress(cfg, user.id, book, file_id=_file(cfg, book), page=page, pages=pages)


def _file(cfg, book):
    from alcove.db import session
    with session(cfg.db_path) as con:
        return con.execute("SELECT id FROM book_files WHERE book_id = ?", (book,)).fetchone()["id"]


def test_messages_carry_where_the_writer_was(cfg, people, add):
    _, sam, bob = people
    book = add("Gyo")
    discussion.post(cfg, sam, book, "Can’t wait to start")          # no progress yet: at the start
    at(cfg, sam, book, 49)
    discussion.post(cfg, sam, book, "  The fish   walk!  ")
    msgs = discussion.thread(cfg, bob, book)["messages"]
    assert [(m["body"], m["place"], m["by"]) for m in msgs] == [
        ("Can’t wait to start", "", "sam"), ("The fish walk!", "Page 50", "sam")]
    assert msgs[1]["position"] == pytest.approx(49 / 99)


def test_messages_from_further_ahead_are_marked(cfg, people, add):
    _, sam, bob = people
    book = add("Gyo")
    at(cfg, sam, book, 79)
    discussion.post(cfg, sam, book, "The ending!")
    at(cfg, bob, book, 19)
    mine_view = discussion.thread(cfg, bob, book)
    assert mine_view["messages"][0]["ahead"] is True
    at(cfg, bob, book, 89)
    assert discussion.thread(cfg, bob, book)["messages"][0]["ahead"] is False
    # The writer never has their own message hidden; nor does anyone who has finished the book.
    assert discussion.thread(cfg, sam, book)["messages"][0]["ahead"] is False
    at(cfg, sam, book, 99)
    discussion.post(cfg, sam, book, "Done")
    at(cfg, bob, book, 99)
    assert not any(m["ahead"] for m in discussion.thread(cfg, bob, book)["messages"])


def test_replies_and_notifications(cfg, people, add):
    _, sam, bob = people
    book = add("Gyo")
    first = discussion.post(cfg, sam, book, "Who else is reading?")
    reply = discussion.post(cfg, bob, book, "Me!", parent_id=first["id"])
    deeper = discussion.post(cfg, sam, book, "Nice", parent_id=reply["id"])
    assert reply["parent_id"] == first["id"] and deeper["parent_id"] == first["id"]  # one level of replies
    told = notifications.list_for(cfg, sam.id)["items"]
    assert told[0]["kind"] == "reply" and "bob" in told[0]["text"] and told[0]["link"] == f"#/book/{book}?discussion=1"
    assert notifications.list_for(cfg, bob.id)["items"][0]["kind"] == "reply"   # sam answered bob's reply
    with pytest.raises(LookupError):
        discussion.post(cfg, sam, add("Other"), "x", parent_id=first["id"])   # a reply stays in its book


def test_editing_and_removing(cfg, people, add):
    admin, sam, bob = people
    book = add("Gyo")
    first = discussion.post(cfg, sam, book, "Thoughts?")
    discussion.post(cfg, bob, book, "Yes", parent_id=first["id"])
    with pytest.raises(LookupError):
        discussion.edit(cfg, bob, first["id"], "hijacked")
    discussion.edit(cfg, sam, first["id"], "Thoughts, anyone?")
    msgs = discussion.thread(cfg, bob, book)["messages"]
    assert msgs[0]["body"] == "Thoughts, anyone?" and msgs[0]["edited"]
    with pytest.raises(LookupError):
        discussion.remove(cfg, bob, first["id"])
    discussion.remove(cfg, sam, first["id"])          # has a reply: stays as a gap
    msgs = discussion.thread(cfg, bob, book)["messages"]
    assert msgs[0]["removed"] and msgs[0]["body"] == "" and len(msgs) == 2
    discussion.remove(cfg, admin, msgs[1]["id"])      # an admin can remove anyone's
    # The gap left for the reply goes too once nothing is under it.
    assert discussion.thread(cfg, bob, book)["messages"] == []


def test_checks(cfg, people, add):
    _, sam, _ = people
    book = add("Gyo")
    with pytest.raises(ValueError):
        discussion.post(cfg, sam, book, "   ")
    with pytest.raises(ValueError):
        discussion.post(cfg, sam, book, "x" * 4001)
    with pytest.raises(LookupError):
        discussion.post(cfg, sam, 99999, "hello")


def test_only_new_messages(cfg, people, add):
    _, sam, bob = people
    book = add("Gyo")
    a = discussion.post(cfg, sam, book, "one")
    discussion.post(cfg, sam, book, "two")
    assert [m["body"] for m in discussion.thread(cfg, bob, book, after=a["id"])["messages"]] == ["two"]


def test_discussion_routes(client, add):
    sam = member(client)
    book = add("Gyo")
    r = sam.post(f"/api/books/{book}/discussion", json={"body": "Hello"})
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert client.get(f"/api/books/{book}/discussion").json()["messages"][0]["by"] == "sam"
    assert client.patch(f"/api/messages/{mid}", json={"body": "nope"}).status_code == 404
    assert sam.patch(f"/api/messages/{mid}", json={"body": "Hello all"}).status_code == 200
    assert client.delete(f"/api/messages/{mid}").status_code == 200
    assert sam.get(f"/api/books/{book}/discussion").json()["messages"] == []
    assert sam.post(f"/api/books/{book}/discussion", json={"body": ""}).status_code == 400
