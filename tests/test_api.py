def book_id(client, title):
    return next(b["id"] for b in client.get("/api/books?limit=100").json()["books"] if b["title"] == title)


def test_setup_flow(app_lib):
    assert app_lib.get("/api/status").json() == {"setup_needed": True, "name": "", "join_requests": False}
    assert app_lib.get("/api/home").status_code == 401
    r = app_lib.post("/api/setup", json={"username": "admin", "password": "longpassword"})
    assert r.status_code == 200 and r.json()["admin"] is True
    assert app_lib.get("/api/status").json() == {"setup_needed": False, "name": "", "join_requests": False}
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
    assert set(client.get("/api/scan").json()) == {"running", "last", "report"}


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


def first_file(client, title):
    return client.get(f"/api/books/{book_id(client, title)}").json()["files"][0]["id"]


def test_manifest_and_pages(client):
    fid = first_file(client, "Three Pages")
    m = client.get(f"/api/files/{fid}/manifest").json()
    assert m["count"] == 3 and m["format"] == "pdf"
    r = client.get(f"/api/files/{fid}/pages/0?w=99999")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert "max-age" in r.headers["cache-control"]
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(r.content)).width == 2400
    assert client.get(f"/api/files/{fid}/pages/-1").status_code == 404
    assert client.get(f"/api/files/{fid}/pages/3").status_code == 404
    assert client.get("/api/files/99999/manifest").status_code == 404


def test_unreadable_files(client):
    r = client.get(f"/api/files/{first_file(client, 'Tale')}/manifest")
    assert r.status_code == 415 and r.json()["reason"] == "format" and "download" in r.json()["detail"]
    r = client.get(f"/api/files/{first_file(client, 'Locked')}/manifest")
    assert r.status_code == 415 and r.json()["reason"] == "protected"
    assert client.get(f"/api/files/{first_file(client, 'Locked')}/pages/0").status_code == 415


def test_progress_round_trip(client):
    bid, fid = book_id(client, "Three Pages"), first_file(client, "Three Pages")
    r = client.put(f"/api/books/{bid}/progress", json={"file_id": fid, "page": 1, "pages": 3})
    assert r.status_code == 200 and r.json()["page"] == 1
    assert client.get(f"/api/books/{bid}").json()["progress"]["page"] == 1
    other_fid = first_file(client, "It")
    assert client.put(f"/api/books/{bid}/progress", json={"file_id": other_fid, "page": 1, "pages": 3}).status_code == 400
    assert client.put("/api/books/99999/progress", json={"file_id": fid, "page": 1, "pages": 3}).status_code == 404


def test_bookmarks_api(client):
    bid, fid = book_id(client, "Three Pages"), first_file(client, "Three Pages")
    mark = client.post(f"/api/books/{bid}/bookmarks", json={"file_id": fid, "page": 2, "note": "here"}).json()
    assert [m["page"] for m in client.get(f"/api/books/{bid}/bookmarks").json()] == [2]
    client.post("/api/users", json={"username": "sam", "password": "longpassword"})
    client.post("/api/login", json={"username": "sam", "password": "longpassword"})
    assert client.get(f"/api/books/{bid}/bookmarks").json() == []
    assert client.delete(f"/api/bookmarks/{mark['id']}").status_code == 404
    client.post("/api/login", json={"username": "admin", "password": "longpassword"})
    assert client.delete(f"/api/bookmarks/{mark['id']}").status_code == 200


def test_settings_api(client):
    assert client.get("/api/settings").json()["reading"]["theme"] == "dark"
    r = client.patch("/api/settings", json={"reading": {"theme": "sepia"}})
    assert r.status_code == 200 and r.json()["reading"]["theme"] == "sepia"
    r = client.patch("/api/settings", json={"reading": {"theme": "pink"}})
    assert r.status_code == 400 and "reading.theme" in r.json()["detail"]


def test_password_change_keeps_this_device(client):
    old = client.post("/api/login", json={"username": "admin", "password": "longpassword"}).json()["token"]
    assert client.post("/api/me/password", json={"current": "nope-nope", "new": "brandnewpw"}).status_code == 400
    r = client.post("/api/me/password", json={"current": "longpassword", "new": "brandnewpw"})
    assert r.status_code == 200
    assert client.get("/api/me").status_code == 200  # this device: new cookie
    client.cookies.clear()
    assert client.get("/api/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_sign_out_everywhere_keeps_this_device(client):
    old = client.post("/api/login", json={"username": "admin", "password": "longpassword"}).json()["token"]
    assert client.post("/api/me/signout-everywhere").status_code == 200
    assert client.get("/api/me").status_code == 200
    client.cookies.clear()
    assert client.get("/api/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_progress_rejects_infinite_time(client):
    bid, fid = book_id(client, "Three Pages"), first_file(client, "Three Pages")
    r = client.put(f"/api/books/{bid}/progress", content=b'{"file_id": %d, "page": 1, "pages": 3, "at": 1e999}' % fid,
                   headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422)
    assert client.get(f"/api/books/{bid}").status_code == 200


def epub_file(client, title="Rich"):
    books = client.get("/api/search?q=" + title).json()
    return client.get(f"/api/books/{books[0]['id']}").json()


def test_flow_outline_and_chapters(client):
    b = epub_file(client)
    f = b["files"][0]
    assert f["readable"] == "flow"
    outline = client.get(f"/api/files/{f['id']}/flow").json()
    assert [c["title"] for c in outline["chapters"]] == ["One", "Two", "Three"]
    assert outline["toc"][1] == {"title": "Two", "chapter": 1, "anchor": "", "level": 0}
    r = client.get(f"/api/files/{f['id']}/chapters/0")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "<script" not in r.text and "x()" not in r.text
    assert f'src="/api/files/{f["id"]}/res/OEBPS/Images/p.png"' in r.text and 'width="60"' in r.text
    assert 'data-chapter="1"' in r.text
    assert client.get(f"/api/files/{f['id']}/chapters/3").status_code == 404
    assert client.get(f"/api/files/{f['id']}/chapters/-1").status_code == 404


def test_flow_resources(client):
    f = epub_file(client)["files"][0]
    r = client.get(f"/api/files/{f['id']}/res/OEBPS/Images/p.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get(f"/api/files/{f['id']}/res/OEBPS/Text/one.xhtml").status_code == 404
    assert client.get(f"/api/files/{f['id']}/res/../../etc/passwd").status_code == 404
    assert client.get(f"/api/files/{f['id']}/res/OEBPS/content.opf").status_code == 404


def test_flow_protected_and_pdf(client):
    locked = epub_file(client, "Sealed")["files"][0]
    r = client.get(f"/api/files/{locked['id']}/flow")
    assert r.status_code == 415 and r.json()["reason"] == "protected"
    pdf = client.get(f"/api/books/{book_id(client, 'Three Pages')}").json()["files"][0]
    assert pdf["readable"] == "pages"
    assert client.get(f"/api/files/{pdf['id']}/flow").status_code == 415


def test_flow_progress_with_locator(client):
    b = epub_file(client)
    fid = b["files"][0]["id"]
    r = client.put(f"/api/books/{b['id']}/progress",
                   json={"file_id": fid, "page": 5, "pages": 20, "locator": {"chapter": 1, "progress": 0.5}})
    assert r.status_code == 200
    assert client.get(f"/api/books/{b['id']}").json()["progress"]["locator"] == {"chapter": 1, "progress": 0.5}
    bad = client.put(f"/api/books/{b['id']}/progress",
                     json={"file_id": fid, "page": 5, "pages": 20, "locator": {"chapter": -2, "progress": 0.5}})
    assert bad.status_code == 400
    mark = client.post(f"/api/books/{b['id']}/bookmarks",
                       json={"file_id": fid, "page": 5, "locator": {"chapter": 2, "progress": 0.1}}).json()
    assert mark["locator"] == {"chapter": 2, "progress": 0.1}


def test_flow_file_broken_after_opening_is_damaged_not_500(client, cfg):
    b = epub_file(client)
    fid = b["files"][0]["id"]
    assert client.get(f"/api/files/{fid}/flow").status_code == 200
    (cfg.books_dirs[0] / "Reader" / "Rich.epub").write_bytes(b"no longer a zip")  # replaced, not yet rescanned
    r = client.get(f"/api/files/{fid}/chapters/0")
    assert r.status_code == 415 and r.json()["reason"] == "damaged"
    r = client.get(f"/api/files/{fid}/res/OEBPS/Images/p.png")
    assert r.status_code == 415


def test_web_app_files_are_revalidated(client):
    """After an update, browsers must check for new app files rather than run a stale cached copy."""
    for path in ("/", "/js/reader.js", "/vendor/page-flip.browser.js", "/style.css"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers.get("cache-control") == "no-cache", path


def test_people_admin_and_passwords(client, app_lib):
    from fastapi.testclient import TestClient
    sam_id = client.post("/api/users", json={"username": "sam", "password": "samsamsam"}).json()["id"]
    me = client.get("/api/me").json()
    sam = TestClient(app_lib.app)
    sam_token = sam.post("/api/login", json={"username": "sam", "password": "samsamsam"}).json()["token"]
    for call in (lambda: sam.patch(f"/api/users/{me['id']}", json={"admin": False}),
                 lambda: sam.post(f"/api/users/{me['id']}/password", json={"password": "hijacked1"}),
                 lambda: sam.delete(f"/api/users/{me['id']}")):
        assert call().status_code == 403

    r = client.patch(f"/api/users/{sam_id}", json={"admin": True})
    assert r.status_code == 200 and r.json()["admin"] is True
    assert sam.get("/api/users").status_code == 200  # takes effect at once
    assert client.patch(f"/api/users/{sam_id}", json={"admin": False}).json()["admin"] is False
    assert sam.get("/api/users").status_code == 403  # and so does taking it away

    r = client.patch(f"/api/users/{me['id']}", json={"admin": False})
    assert r.status_code == 400 and "at least one admin" in r.json()["detail"]
    assert client.patch("/api/users/9999", json={"admin": True}).status_code == 404

    assert client.post(f"/api/users/{sam_id}/password", json={"password": "short"}).status_code == 400
    assert client.post(f"/api/users/{sam_id}/password", json={"password": "newpassword"}).status_code == 200
    assert sam.get("/api/me", headers={"Authorization": f"Bearer {sam_token}"}).status_code == 401
    assert sam.post("/api/login", json={"username": "sam", "password": "newpassword"}).status_code == 200


def test_giving_up_your_own_admin_keeps_you_signed_in(client):
    sam_id = client.post("/api/users", json={"username": "sam", "password": "samsamsam"}).json()["id"]
    client.patch(f"/api/users/{sam_id}", json={"admin": True})
    me = client.get("/api/me").json()
    r = client.patch(f"/api/users/{me['id']}", json={"admin": False})
    assert r.status_code == 200 and r.json()["admin"] is False
    assert client.get("/api/me").json()["admin"] is False


def test_the_sign_in_cookie_is_secure_over_https(app_lib):
    # Behind https (tailscale serve, a proxy) the cookie is never sent over plain http.
    from fastapi.testclient import TestClient
    https = TestClient(app_lib.app, base_url="https://testserver")
    r = https.post("/api/setup", json={"username": "admin", "password": "longpassword"})
    assert "secure" in r.headers["set-cookie"].lower()
    r = app_lib.post("/api/login", json={"username": "admin", "password": "longpassword"})
    assert "secure" not in r.headers["set-cookie"].lower()


def test_ping_says_this_is_loft(app_lib):
    # The Android app checks the address it's given is a Loft server before saving it.
    r = app_lib.get("/api/ping")
    assert r.status_code == 200 and r.json()["app"] == "loft" and r.json()["version"]
    assert r.headers["access-control-allow-origin"] == "*"   # asked from the app's own start page
