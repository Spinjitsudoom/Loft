"""Members: asking to join, and notifications."""
import pytest
from fastapi.testclient import TestClient

from alcove import auth, joining, libsettings, notifications
from alcove.db import session


def member(client, name="sam", password="samsamsam"):
    """A second client, signed in as a member (made by the admin signed in on `client`)."""
    r = client.post("/api/users", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    other = TestClient(client.app)
    assert other.post("/api/login", json={"username": name, "password": password}).status_code == 200
    return other


# ---------- notifications ----------

def test_notifications(cfg):
    a = auth.create_user(cfg, "ann", "annannann", admin=True)
    b = auth.create_user(cfg, "bob", "bobbobbob")
    with session(cfg.db_path) as con:
        notifications.notify(con, [b.id], "reply", "Ann replied to you", "#/book/1")
        notifications.notify(con, notifications.admins(con), "join", "Someone asked to join", "#/admin")
    mine = notifications.list_for(cfg, b.id)
    assert mine["unread"] == 1 and mine["items"][0]["text"] == "Ann replied to you"
    assert mine["items"][0]["link"] == "#/book/1" and mine["items"][0]["read"] is False
    assert notifications.list_for(cfg, a.id)["items"][0]["kind"] == "join"
    notifications.mark_read(cfg, b.id)
    assert notifications.list_for(cfg, b.id)["unread"] == 0
    auth.delete_user(cfg, b.id)  # their notifications go with them
    with session(cfg.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (b.id,)).fetchone()[0] == 0


def test_notification_routes(client):
    sam = member(client)
    with session(client.app.state.cfg.db_path) as con:
        uid = con.execute("SELECT id FROM users WHERE username = 'sam'").fetchone()["id"]
        notifications.notify(con, [uid], "reply", "Hello", "#/")
    r = sam.get("/api/notifications").json()
    assert r["unread"] == 1
    assert sam.post("/api/notifications/read").status_code == 200
    assert sam.get("/api/notifications").json()["unread"] == 0
    assert client.get("/api/notifications").json()["items"] == []


# ---------- asking to join ----------

def test_asking_to_join_is_off_until_the_admin_turns_it_on(cfg):
    auth.create_user(cfg, "ann", "annannann", admin=True)
    with pytest.raises(ValueError, match="isn’t taking"):
        joining.ask(cfg, "newbie", "newbienewbie", "")
    libsettings.update_library(cfg, {"join_requests": True})
    joining.ask(cfg, "newbie", "newbienewbie", "  I’m Ann’s brother  ")
    waiting = joining.waiting(cfg)
    assert [(w["username"], w["note"]) for w in waiting] == [("newbie", "I’m Ann’s brother")]
    assert "password" not in str(waiting) and "hash" not in str(waiting)


def test_approving_and_declining(cfg):
    admin = auth.create_user(cfg, "ann", "annannann", admin=True)
    libsettings.update_library(cfg, {"join_requests": True})
    joining.ask(cfg, "newbie", "newbienewbie", "")
    joining.ask(cfg, "other", "otherother", "")
    assert notifications.list_for(cfg, admin.id)["unread"] == 2
    first, second = joining.waiting(cfg)
    user = joining.approve(cfg, first["id"])
    assert user.username == "newbie" and not user.admin
    assert auth.authenticate(cfg, "newbie", "newbienewbie", "1.2.3.4") is not None
    joining.decline(cfg, second["id"])
    assert joining.waiting(cfg) == []
    assert auth.authenticate(cfg, "other", "otherother", "1.2.3.5") is None


def test_names_and_limits(cfg, monkeypatch):
    auth.create_user(cfg, "ann", "annannann", admin=True)
    libsettings.update_library(cfg, {"join_requests": True})
    with pytest.raises(ValueError, match="already"):
        joining.ask(cfg, "ANN", "whateverwhatever", "")
    joining.ask(cfg, "newbie", "newbienewbie", "")
    with pytest.raises(ValueError, match="already"):
        joining.ask(cfg, "Newbie", "newbienewbie", "")
    with pytest.raises(ValueError):
        joining.ask(cfg, "short", "pw", "")
    with pytest.raises(ValueError, match="note"):
        joining.ask(cfg, "longnote", "longnotelongnote", "x" * 501)
    monkeypatch.setattr(joining, "MAX_WAITING", 1)
    with pytest.raises(ValueError, match="too many"):
        joining.ask(cfg, "third", "thirdthird", "")


def test_join_routes(client):
    assert client.get("/api/status").json()["join_requests"] is False
    stranger = TestClient(client.app)
    assert stranger.post("/api/join", json={"username": "newbie", "password": "newbienewbie"}).status_code == 403
    client.patch("/api/library", json={"join_requests": True})
    assert stranger.get("/api/status").json()["join_requests"] is True
    r = stranger.post("/api/join", json={"username": "newbie", "password": "newbienewbie", "note": "hi"})
    assert r.status_code == 200, r.text
    waiting = client.get("/api/join-requests").json()
    assert [w["username"] for w in waiting] == ["newbie"]
    assert client.post(f"/api/join-requests/{waiting[0]['id']}/approve").json()["username"] == "newbie"
    assert stranger.post("/api/login", json={"username": "newbie", "password": "newbienewbie"}).status_code == 200
    assert stranger.get("/api/join-requests").status_code == 403
    assert client.delete("/api/join-requests/999").status_code == 404
