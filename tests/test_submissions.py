"""Members submit books; they wait for an admin, who approves (into the library) or declines."""
import os
import time

import pytest

from alcove import auth, notifications, submissions, uploads
from alcove.library import get_book
from conftest import jpg
from test_members import member

DETAILS = {"title": "Tale", "authors": ["A"], "series": "", "series_index": None, "description": "A tale.",
           "publisher": "", "published": "", "language": "en", "tags": []}


def epub(tmp_path, make_epub, title="Tale"):
    return make_epub(tmp_path / "src" / f"{title}.epub", title=title, author="A",
                     cover=jpg((200, 10, 10), (300, 450))).read_bytes()


@pytest.fixture
def people(cfg):
    return auth.create_user(cfg, "ann", "annannann", admin=True), auth.create_user(cfg, "sam", "samsamsam")


def test_a_submission_waits_then_is_approved(cfg, tmp_path, make_epub, people):
    admin, sam = people
    draft = uploads.start(cfg, "Tale.epub", [epub(tmp_path, make_epub)], owner=sam.id)
    sid = submissions.submit(cfg, sam, draft["token"], DETAILS)
    assert not any(cfg.books_dirs[0].rglob("*.epub"))          # nothing in the library yet
    assert [s["title"] for s in submissions.mine(cfg, sam.id)] == ["Tale"]
    assert submissions.mine(cfg, sam.id)[0]["status"] == "waiting"
    waiting = submissions.waiting(cfg)
    assert waiting[0]["by"] == "sam" and waiting[0]["details"]["title"] == "Tale"
    assert notifications.list_for(cfg, admin.id)["items"][0]["kind"] == "submission"

    bid = submissions.approve(cfg, sid, {**DETAILS, "title": "Tale, Fixed"})
    assert get_book(cfg, bid)["title"] == "Tale, Fixed"
    assert (cfg.books_dirs[0] / "A" / "Tale, Fixed" / "Tale.epub").is_file()
    mine = submissions.mine(cfg, sam.id)[0]
    assert mine["status"] == "approved" and mine["book_id"] == bid
    told = notifications.list_for(cfg, sam.id)["items"][0]
    assert told["kind"] == "approved" and told["link"] == f"#/book/{bid}"
    assert submissions.waiting(cfg) == []


def test_declining_says_why_and_clears_the_file(cfg, tmp_path, make_epub, people):
    _, sam = people
    draft = uploads.start(cfg, "Tale.epub", [epub(tmp_path, make_epub)], owner=sam.id)
    sid = submissions.submit(cfg, sam, draft["token"], DETAILS)
    submissions.decline(cfg, sid, "  We have it already  ")
    mine = submissions.mine(cfg, sam.id)[0]
    assert mine["status"] == "declined" and mine["reason"] == "We have it already"
    assert "We have it already" in notifications.list_for(cfg, sam.id)["items"][0]["text"]
    assert not (cfg.data_dir / "uploads" / draft["token"]).exists()
    with pytest.raises(ValueError):
        submissions.approve(cfg, sid)


def test_details_are_required_to_send(cfg, tmp_path, make_epub, people):
    _, sam = people
    draft = uploads.start(cfg, "Tale.epub", [epub(tmp_path, make_epub)], owner=sam.id)
    with pytest.raises(ValueError, match="at least one author"):
        submissions.submit(cfg, sam, draft["token"], {**DETAILS, "authors": []})
    submissions.submit(cfg, sam, draft["token"], DETAILS)
    with pytest.raises(ValueError, match="already"):
        submissions.submit(cfg, sam, draft["token"], DETAILS)


def test_drafts_belong_to_who_uploaded_them(cfg, tmp_path, make_epub, people):
    admin, sam = people
    other = auth.create_user(cfg, "bob", "bobbobbob")
    draft = uploads.start(cfg, "Tale.epub", [epub(tmp_path, make_epub)], owner=sam.id)
    with pytest.raises(LookupError):
        uploads.draft_cover(cfg, draft["token"], user=other)
    with pytest.raises(LookupError):
        submissions.submit(cfg, other, draft["token"], DETAILS)
    with pytest.raises(LookupError):  # an admin doesn't see a member's draft until it's sent
        uploads.draft_cover(cfg, draft["token"], user=admin)
    submissions.submit(cfg, sam, draft["token"], DETAILS)
    assert uploads.draft_cover(cfg, draft["token"], user=admin) is not None


def test_waiting_submissions_are_never_pruned(cfg, tmp_path, make_epub, people):
    _, sam = people
    sent = uploads.start(cfg, "Tale.epub", [epub(tmp_path, make_epub)], owner=sam.id)
    unsent = uploads.start(cfg, "Tale.epub", [epub(tmp_path, make_epub)], owner=sam.id)
    submissions.submit(cfg, sam, sent["token"], DETAILS)
    stale = time.time() - 30 * 86400
    for d in (sent, unsent):
        os.utime(cfg.data_dir / "uploads" / d["token"], (stale, stale))
    uploads.prune_drafts(cfg)
    assert (cfg.data_dir / "uploads" / sent["token"]).exists()
    assert not (cfg.data_dir / "uploads" / unsent["token"]).exists()


def test_taking_a_submission_back(cfg, tmp_path, make_epub, people):
    _, sam = people
    draft = uploads.start(cfg, "Tale.epub", [epub(tmp_path, make_epub)], owner=sam.id)
    sid = submissions.submit(cfg, sam, draft["token"], DETAILS)
    other = auth.create_user(cfg, "bob", "bobbobbob")
    with pytest.raises(LookupError):
        submissions.withdraw(cfg, other, sid)
    submissions.withdraw(cfg, sam, sid)
    assert submissions.mine(cfg, sam.id) == [] and submissions.waiting(cfg) == []


def test_submission_routes(client, tmp_path, make_epub):
    sam = member(client)
    data = epub(tmp_path, make_epub, "Fresh")
    r = sam.put("/api/uploads?name=Fresh.epub", content=data)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert sam.get(f"/api/uploads/{token}/cover").status_code == 200
    assert sam.post(f"/api/uploads/{token}/save", json={"details": DETAILS}).status_code == 403
    r = sam.post(f"/api/uploads/{token}/submit", json={"details": {**DETAILS, "title": "Fresh"}})
    assert r.status_code == 200, r.text
    assert [s["title"] for s in sam.get("/api/submissions/mine").json()] == ["Fresh"]
    assert sam.get("/api/submissions").status_code == 403

    waiting = client.get("/api/submissions").json()
    assert waiting[0]["by"] == "sam"
    assert client.get(f"/api/uploads/{token}/cover").status_code == 200
    r = client.post(f"/api/submissions/{waiting[0]['id']}/approve", json={"details": {**DETAILS, "title": "Fresh"}})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/books/{r.json()['book_id']}").json()["title"] == "Fresh"
    assert sam.get("/api/submissions/mine").json()[0]["status"] == "approved"
    assert client.post(f"/api/submissions/{waiting[0]['id']}/decline", json={"reason": "x"}).status_code == 400


def test_a_waiting_submission_is_only_declined_or_taken_back(cfg, tmp_path, make_epub, people):
    admin, sam = people
    draft = uploads.start(cfg, "Tale.epub", [epub(tmp_path, make_epub)], owner=sam.id)
    submissions.submit(cfg, sam, draft["token"], DETAILS)
    for who in (admin, sam):
        with pytest.raises(ValueError):
            uploads.discard(cfg, draft["token"], user=who)
    assert (cfg.data_dir / "uploads" / draft["token"]).exists()


def test_members_have_a_limit_on_unsent_uploads(cfg, tmp_path, make_epub, people, monkeypatch):
    admin, sam = people
    monkeypatch.setattr(uploads, "MAX_UNSENT", 2)
    data = epub(tmp_path, make_epub)
    uploads.start(cfg, "a.epub", [data], owner=sam.id, limited=True)
    uploads.start(cfg, "b.epub", [data], owner=sam.id, limited=True)
    with pytest.raises(ValueError, match="send or discard"):
        uploads.start(cfg, "c.epub", [data], owner=sam.id, limited=True)
    for name in ("d.epub", "e.epub", "f.epub"):  # admins adding a pile of books aren't limited
        uploads.start(cfg, name, [data], owner=admin.id)
