"""The stacks: the library as bookcases, signed by series, section or author, with filters."""
import pytest

from loft import auth, browse, libsettings, reading
from loft.db import session


@pytest.fixture
def shelves(cfg, add):
    """A small library with the kinds of tags lookups leave behind."""
    ids = {
        "uzumaki": add("Uzumaki", ["Junji Ito"], tags=["Manga", "Horror"]),
        "promise": add("The Promise 1", ["Gene Luen Yang"], series="Avatar", index=1,
                       tags=["Comics & Graphic Novels", "Juvenile Fiction"]),
        "search": add("The Search 1", ["Gene Luen Yang"], series="Avatar", index=4,
                      tags=["Comics & Graphic Novels", "Media Tie-In"]),
        "cheese": add("The Curse of the Cheese Pyramid", ["Geronimo Stilton"], series="Geronimo Stilton", index=2,
                      tags=["Juvenile Fiction", "General"]),
        "renaissance": add("Renaissance", ["Oliver Bowden"], series="Assassin's Creed", index=1,
                           tags=["Historical Fiction", "Media Tie-In"]),
        "odd": add("A Book of Odds", ["Nobody Special"], tags=["General"]),
    }
    return ids


def test_sections_are_suggested_from_the_tags(cfg, shelves):
    sections = libsettings.get_library(cfg)["sections"]
    names = [s["name"] for s in sections]
    assert names[:4] == ["Manga", "Graphic novels", "Children’s", "Historical"]
    assert libsettings.get_library(cfg)["sections_suggested"] is True
    assert "Fantasy" not in names  # only what the library has


def test_a_book_stands_in_one_section(cfg, shelves):
    admin = auth.create_user(cfg, "ann", "annannann", admin=True)
    got = browse.stacks(cfg, admin, by="section")
    cases = {c["title"]: [b["title"] for b in c["books"]] for c in got["cases"]}
    assert cases["Manga"] == ["Uzumaki"]
    assert cases["Graphic novels"] == ["The Promise 1", "The Search 1"]   # not also under Children's
    assert cases["Children’s"] == ["The Curse of the Cheese Pyramid"]
    assert cases["Historical"] == ["Renaissance"]
    assert cases["Other"] == ["A Book of Odds"]
    assert list(cases)[-1] == "Other" and got["total"] == 6


def test_the_admins_own_sections(cfg, shelves):
    admin = auth.create_user(cfg, "ann", "annannann", admin=True)
    libsettings.update_library(cfg, {"sections": [
        {"name": "Comics", "tags": ["comics & graphic novels", "Manga"]},
        {"name": "Kids", "tags": ["Juvenile Fiction"]},
    ]})
    lib = libsettings.get_library(cfg)
    assert lib["sections_suggested"] is False and [s["name"] for s in lib["sections"]] == ["Comics", "Kids"]
    cases = {c["title"]: len(c["books"]) for c in browse.stacks(cfg, admin, by="section")["cases"]}
    assert cases == {"Comics": 3, "Kids": 1, "Other": 2}   # tags match whatever their case
    libsettings.update_library(cfg, {"sections": None})
    assert libsettings.get_library(cfg)["sections_suggested"] is True


@pytest.mark.parametrize("bad", [
    [{"name": "", "tags": []}], [{"name": "A", "tags": []}, {"name": "a", "tags": []}],
    [{"name": "x" * 41, "tags": []}], [{"name": "A", "tags": "Manga"}], "Manga",
    [{"name": f"S{i}", "tags": []} for i in range(31)],
])
def test_sections_are_checked(cfg, bad):
    with pytest.raises(ValueError):
        libsettings.update_library(cfg, {"sections": bad})


def test_series_cases_then_standalones_together(cfg, shelves):
    admin = auth.create_user(cfg, "ann", "annannann", admin=True)
    got = browse.stacks(cfg, admin, by="series")
    assert [c["title"] for c in got["cases"]] == ["Assassin's Creed", "Avatar", "Geronimo Stilton", "Not in a series"]
    avatar = next(c for c in got["cases"] if c["title"] == "Avatar")
    assert [b["title"] for b in avatar["books"]] == ["The Promise 1", "The Search 1"]   # in series order
    loose = got["cases"][-1]
    assert loose["kind"] == "loose" and [b["title"] for b in loose["books"]] == ["Uzumaki", "A Book of Odds"]  # Ito, Special


def test_by_author_on_lettered_shelves(cfg, shelves, add):
    admin = auth.create_user(cfg, "ann", "annannann", admin=True)
    add("Untitled scan", [])
    got = browse.stacks(cfg, admin, by="author")
    # By surname, as a library shelves them: Bowden; Ito; Special, Stilton; Yang; then no author.
    assert [(c["title"], c["kind"]) for c in got["cases"]] == [
        ("B", "letter"), ("I", "letter"), ("S", "letter"), ("Y", "letter"), ("No author", "letter")]
    s_case = next(c for c in got["cases"] if c["title"] == "S")
    assert [b["authors"][0] for b in s_case["books"]] == ["Nobody Special", "Geronimo Stilton"]


def test_filters_and_counts(cfg, shelves):
    admin = auth.create_user(cfg, "ann", "annannann", admin=True)
    with session(cfg.db_path) as con:
        fid = con.execute("SELECT id FROM book_files WHERE book_id = ?", (shelves["promise"],)).fetchone()["id"]
    reading.save_progress(cfg, admin.id, shelves["promise"], file_id=fid, page=3, pages=10)
    got = browse.stacks(cfg, admin, by="section", status="reading")
    assert got["total"] == 1 and got["cases"][0]["books"][0]["progress"]["page"] == 3
    assert got["facets"]["status"] == {"unread": 5, "reading": 1, "finished": 0}
    got = browse.stacks(cfg, admin, by="series", section="Graphic novels", author="Gene Luen Yang")
    assert got["total"] == 2
    assert got["facets"]["section"]["Graphic novels"] == 2 and got["facets"]["section"]["Manga"] == 0
    assert got["facets"]["author"]["Gene Luen Yang"] == 2
    assert browse.stacks(cfg, admin, by="series", fmt="epub")["total"] == 0
    assert browse.stacks(cfg, admin, by="series")["facets"]["format"] == {"pdf": 6}
    with pytest.raises(ValueError):
        browse.stacks(cfg, admin, by="shoe size")


def test_each_book_knows_its_size_for_its_spine(cfg, shelves):
    admin = auth.create_user(cfg, "ann", "annannann", admin=True)
    book = browse.stacks(cfg, admin, by="series")["cases"][0]["books"][0]
    assert {"id", "title", "color", "has_cover", "size", "pages", "section", "progress"} <= set(book)


def test_stacks_route(client, add):
    add("Uzumaki", ["Junji Ito"], tags=["Manga"])
    r = client.get("/api/stacks?by=section")
    assert r.status_code == 200 and r.json()["cases"][0]["title"] == "Manga"
    assert client.get("/api/stacks?by=nonsense").status_code == 400
    assert client.get("/api/library").json()["sections_suggested"] is True


def test_what_each_section_holds_and_whats_left(cfg, shelves):
    report = browse.sections_report(cfg)
    counts = {s["name"]: s["count"] for s in report["sections"]}
    assert counts["Graphic novels"] == 2 and counts["Manga"] == 1
    assert report["other"]["count"] == 1 and report["other"]["untagged"] == 0
    assert report["other"]["tags"] == [["General", 1]]   # what the books left in Other are tagged
    assert report["suggested"] is True


def test_sections_route_is_for_admins(client, add):
    from test_members import member
    add("Uzumaki", ["Junji Ito"], tags=["Manga"])
    assert client.get("/api/sections").json()["sections"][0]["name"] == "Manga"
    assert member(client).get("/api/sections").status_code == 403
