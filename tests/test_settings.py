
import pytest

from loft import auth
from loft.settings import DEFAULTS, get_settings, update_settings


@pytest.fixture
def user(cfg):
    return auth.create_user(cfg, "sam", "longpassword")


def test_defaults(cfg, user):
    assert get_settings(cfg, user.id) == DEFAULTS
    assert DEFAULTS["reading"]["mode"] == "pages" and DEFAULTS["look"]["accent"] == "brass"


def test_patch_keeps_the_rest(cfg, user):
    s = update_settings(cfg, user.id, {"reading": {"theme": "sepia"}})
    assert s["reading"]["theme"] == "sepia"
    assert s["reading"]["mode"] == "pages"
    assert s["look"] == DEFAULTS["look"]
    s = update_settings(cfg, user.id, {"look": {"accent": "sage", "cover_size": "large"}})
    assert get_settings(cfg, user.id)["reading"]["theme"] == "sepia"
    assert get_settings(cfg, user.id)["look"]["accent"] == "sage"


def test_home_rows_reorder(cfg, user):
    rows = [{"kind": k, "visible": k != "recent"} for k in ("genres", "recent", "series", "shelves", "continue")]
    assert update_settings(cfg, user.id, {"look": {"home_rows": rows}})["look"]["home_rows"] == rows


@pytest.mark.parametrize("patch,key", [
    ({"reading": {"colour": "x"}}, "reading.colour"),
    ({"reading": {"theme": "pink"}}, "reading.theme"),
    ({"reading": {"epub_size": 300}}, "reading.epub_size"),
    ({"reading": {"spread": "yes"}}, "reading.spread"),
    ({"look": {"home_rows": [{"kind": "recent", "visible": True}] * 4}}, "look.home_rows"),
    ({"look": {"home_rows": [{"kind": "recent", "visible": True}]}}, "look.home_rows"),
    ({"other": {}}, "other"),
])
def test_bad_settings_refused(cfg, user, patch, key):
    with pytest.raises(ValueError, match=key.replace(".", r"\.")):
        update_settings(cfg, user.id, patch)
    assert get_settings(cfg, user.id) == DEFAULTS


def test_settings_go_with_the_account(cfg, user):
    update_settings(cfg, user.id, {"reading": {"theme": "black"}})
    auth.delete_user(cfg, user.id)
    other = auth.create_user(cfg, "sam2", "longpassword")
    assert get_settings(cfg, other.id) == DEFAULTS
    from loft.db import session
    with session(cfg.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM user_settings").fetchone()[0] == 0


def test_defaults_are_not_shared(cfg, user):
    s = get_settings(cfg, user.id)
    s["look"]["home_rows"].clear()
    assert get_settings(cfg, user.id)["look"]["home_rows"] == DEFAULTS["look"]["home_rows"]
