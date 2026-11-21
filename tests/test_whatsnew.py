"""The "What's new" notes the app shows after an update: one entry per release, newest first.
The release attaches the same file, so a server can show the next version's notes before it updates."""

import json
from pathlib import Path

from loft import updates

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "src" / "loft" / "web" / "whatsnew.json"


def test_every_release_has_notes_newest_first():
    import tomllib
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    assert notes[0]["version"] == version, "Write this version's notes at the top of src/loft/web/whatsnew.json"
    versions = [updates.parse(n["version"]) for n in notes]
    assert all(versions) and versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions)
    assert updates.release_notes(notes, "0.0.0", version) == notes   # every entry is one the app accepts
    for n in notes:
        assert n.get("new") or n.get("fixed"), n["version"]


def test_the_notes_are_served(client):
    r = client.get("/whatsnew.json")
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_the_release_attaches_them():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "src/loft/web/whatsnew.json" in workflow
