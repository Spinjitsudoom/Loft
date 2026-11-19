import json

import pytest

from loft import library
from loft.db import session


def titles(cards):
    return [c["title"] for c in cards]


def test_home_rows(cfg, add):
    for i in range(20):
        add(f"Loose {i:02}")
    add("Ten", series="Saga", index=10)
    add("One", series="Saga", index=1)
    add("Two", series="Saga", index=2)
    add("Solo", series="Alone", index=1)  # a series of one gets no row
    for t in ("Horror A", "Horror B", "Horror C"):
        add(t, tags=["Horror"])
    add("Rare", tags=["Rare", "Horror"])
    add("Rare 2", tags=["Rare"])
    home = library.home(cfg, None)
    assert home["hero"]["title"] == "Rare 2"
    rows = home["rows"]
    assert rows[0]["title"] == "Recently added" and rows[0]["kind"] == "recent" and len(rows[0]["books"]) == 15
    saga = next(r for r in rows if r["kind"] == "series")
    assert (saga["title"], saga["value"], titles(saga["books"])) == ("Saga", "Saga", ["One", "Two", "Ten"])
    assert not any(r["value"] == "Alone" for r in rows)
    tag_rows = [r for r in rows if r["kind"] == "tag"]
    assert [r["value"] for r in tag_rows] == ["Horror"]  # "Rare" has only 2 books
    assert titles(tag_rows[0]["books"]) == ["Horror A", "Horror B", "Horror C", "Rare"]


def test_card_shape(cfg, add):
    bid = add("The Long Road", authors=["A. Marlow"], series="Road", index=2)
    card = library.home(cfg, None)["hero"]
    assert card.pop("cover_v") > 0
    assert card == {"id": bid, "title": "The Long Road", "authors": ["A. Marlow"], "series": "Road",
                    "series_index": 2.0, "has_cover": False, "color": None}


def test_empty_library(cfg):
    assert library.home(cfg, None) == {"hero": None, "hero_kind": None, "hero_progress": None, "rows": []}


def test_list_books_filters_and_sorts(cfg, add):
    add("Banana", authors=["Zed"], tags=["Fruit"])
    add("The Apple", authors=["Amy"], tags=["Fruit"])
    add("Cherry", authors=["Amy"])
    assert titles(library.list_books(cfg, kind=None, value=None)["books"]) == ["The Apple", "Banana", "Cherry"]
    assert titles(library.list_books(cfg, kind="tag", value="Fruit")["books"]) == ["The Apple", "Banana"]
    r = library.list_books(cfg, kind="author", value="Amy", sort="added")
    assert (r["total"], titles(r["books"])) == (2, ["Cherry", "The Apple"])
    assert library.list_books(cfg, kind=None, value=None, offset=1, limit=1)["books"][0]["title"] == "Banana"


def test_get_book(cfg, add):
    one = add("One", series="Saga", index=1, tags=["X"], description="Para one.\n\nPara two.")
    add("Two", series="Saga", index=2)
    b = library.get_book(cfg, one)
    assert b["description"] == "Para one.\n\nPara two."
    assert b["tags"] == ["X"]
    assert [f["format"] for f in b["files"]] == ["pdf"] and "id" in b["files"][0] and "path" not in b["files"][0]
    assert titles(b["series_books"]) == ["Two"]
    assert library.get_book(cfg, 9999) is None


def test_search(cfg, add):
    add("Tide Line", authors=["J. Okafor"])
    add("Night Atlas", authors=["Mara Öst"], series="Atlas")
    assert titles(library.search(cfg, "tide")) == ["Tide Line"]
    assert titles(library.search(cfg, "Ökafor")) == ["Tide Line"]
    assert titles(library.search(cfg, "ost")) == ["Night Atlas"]
    assert titles(library.search(cfg, "nig atl")) == ["Night Atlas"]
    assert library.search(cfg, '"); DROP TABLE books; --') == []
    assert library.search(cfg, "   ") == []
    assert library.search(cfg, "AND OR NOT *") == []
