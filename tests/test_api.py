def book_id(client, title):
    return next(b["id"] for b in client.get("/api/books?limit=100").json()["books"] if b["title"] == title)


def test_setup_flow(app_lib):
    assert app_lib.get("/api/status").json() == {"setup_needed": True}
    assert app_lib.get("/api/home").status_code == 401
    r = app_lib.post("/api/setup", json={"username": "admin", "password": "longpassword"})
    assert r.status_code == 200 and r.json()["admin"] is True
    assert app_lib.get("/api/status").json() == {"setup_needed": False}
    assert app_lib.get("/api/me").json()["username"] == "admin"
    assert app_lib.post("/api/setup", json={"username": "x", "password": "longpassword"}).status_code == 409


def test_setup_bad_password(app_lib):
    r = app_lib.post("/api/setup", json={"username": "admin", "password": "abc"})
    assert r.status_code == 400 and "characters" in r.json()["detail"]


def test_login_logout(client):
    client.post("/api/logout")
    assert client.get("/api/home").status_code == 401
    assert client.post("/api/login", json={"username": "admin", "password": "wrongwrong"}).status_code == 401
    assert client.post("/api/login", json={"username": "ADMIN", "password": "longpassword"}).status_code == 200
    assert client.get("/api/home").status_code == 200


def test_bearer_token(client):
    token = client.post("/api/login", json={"username": "admin", "password": "longpassword"}).json()["token"]
    client.cookies.clear()
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_members_and_admin_routes(client):
    r = client.post("/api/users", json={"username": "sam", "password": "longpassword"})
    assert r.status_code == 200 and r.json()["admin"] is False
    me = client.get("/api/me").json()
    assert client.delete(f"/api/users/{me['id']}").status_code == 400
    assert [u["username"] for u in client.get("/api/users").json()] == ["admin", "sam"]
    client.post("/api/login", json={"username": "sam", "password": "longpassword"})
    assert client.get("/api/home").status_code == 200
    assert client.post("/api/scan").status_code == 403
    assert client.get("/api/users").status_code == 403


def test_scan_route(client):
    assert client.post("/api/scan").status_code == 202
    assert set(client.get("/api/scan").json()) == {"running", "last"}


def test_home_and_book(client):
    home = client.get("/api/home").json()
    assert home["hero"] and home["rows"][0]["kind"] == "recent"
    b = client.get(f"/api/books/{book_id(client, 'It')}").json()
    assert b["description"] == "Derry." and "<" not in b["description"]
    assert client.get("/api/books/99999").status_code == 404


def test_browse_and_search(client):
    assert client.get("/api/books?kind=author&value=Stephen King").json()["total"] == 1
    assert [b["title"] for b in client.get("/api/search?q=tide").json()] == ["Tide Line"]
    assert client.get("/api/books?kind=nonsense&value=x").status_code == 400


def test_cover(client):
    r = client.get(f"/api/books/{book_id(client, 'It')}/cover?w=240")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert "max-age" in r.headers["cache-control"]
    assert client.get("/api/books/99999/cover").status_code == 404


def test_file_download_by_id(client, cfg):
    books = client.get("/api/books?limit=100").json()["books"]
    odd = next(x for x in books if "odd" in x["title"])
    fid = client.get(f"/api/books/{odd['id']}").json()["files"][0]["id"]
    r = client.get(f"/api/files/{fid}")
    assert r.status_code == 200
    assert r.content == (cfg.books_dirs[0] / "Odd" / "Who's #1? odd.pdf").read_bytes()
    assert "attachment" in r.headers["content-disposition"]
    assert client.get("/api/files/99999").status_code == 404
    assert client.get("/api/files/..%2F..%2Fetc%2Fpasswd").status_code in (404, 422)


def test_web_app_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
