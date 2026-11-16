import pytest

from alcove import auth


def test_create_and_authenticate(cfg):
    assert not auth.has_users(cfg)
    u = auth.create_user(cfg, "Etta", "longpassword", admin=True)
    assert u.admin and u.username == "Etta"
    assert auth.has_users(cfg)
    assert auth.authenticate(cfg, "etta", "longpassword", "1.1.1.1") == u
    assert auth.authenticate(cfg, "etta", "wrong-pass", "1.1.1.1") is None
    assert auth.authenticate(cfg, "nobody", "longpassword", "1.1.1.1") is None


def test_token_round_trip(cfg):
    u = auth.create_user(cfg, "sam", "longpassword")
    assert auth.user_from_token(cfg, auth.make_token(cfg, u)) == u
    assert auth.user_from_token(cfg, "garbage") is None
    assert auth.user_from_token(cfg, None) is None


def test_new_password_signs_out_everywhere(cfg):
    u = auth.create_user(cfg, "sam", "longpassword")
    token = auth.make_token(cfg, u)
    auth.set_password(cfg, u.id, "another-password")
    assert auth.user_from_token(cfg, token) is None
    assert auth.authenticate(cfg, "sam", "another-password", "ip") is not None


def test_lockout_after_eight_wrong_passwords(cfg):
    auth.create_user(cfg, "sam", "longpassword")
    for _ in range(8):
        assert auth.authenticate(cfg, "sam", "nope-nope", "9.9.9.9") is None
    assert auth.authenticate(cfg, "sam", "longpassword", "9.9.9.9") is None
    assert auth.authenticate(cfg, "sam", "longpassword", "8.8.8.8") is not None


@pytest.mark.parametrize("name,password", [("bad/name", "longpassword"), ("ok", "abc"), ("", "longpassword")])
def test_bad_accounts_refused(cfg, name, password):
    with pytest.raises(ValueError):
        auth.create_user(cfg, name, password)


def test_duplicate_name_refused(cfg):
    auth.create_user(cfg, "Sam", "longpassword")
    with pytest.raises(ValueError, match="already"):
        auth.create_user(cfg, "sam", "longpassword")


def test_list_and_delete(cfg):
    a = auth.create_user(cfg, "a1", "longpassword", admin=True)
    b = auth.create_user(cfg, "b1", "longpassword")
    token = auth.make_token(cfg, b)
    assert [u.username for u in auth.list_users(cfg)] == ["a1", "b1"]
    auth.delete_user(cfg, b.id)
    assert [u.id for u in auth.list_users(cfg)] == [a.id]
    assert auth.user_from_token(cfg, token) is None


def test_change_password(cfg):
    u = auth.create_user(cfg, "sam", "longpassword")
    old_token = auth.make_token(cfg, u)
    with pytest.raises(ValueError, match="current password"):
        auth.change_password(cfg, u.id, "wrong-one", "newpassword")
    assert auth.user_from_token(cfg, old_token) == u
    updated = auth.change_password(cfg, u.id, "longpassword", "newpassword")
    assert auth.user_from_token(cfg, old_token) is None
    assert auth.user_from_token(cfg, auth.make_token(cfg, updated)) == updated
    assert auth.authenticate(cfg, "sam", "newpassword", "ip-cp") is not None


def test_sign_out_everywhere(cfg):
    u = auth.create_user(cfg, "sam", "longpassword")
    token = auth.make_token(cfg, u)
    updated = auth.sign_out_everywhere(cfg, u.id)
    assert auth.user_from_token(cfg, token) is None
    assert auth.user_from_token(cfg, auth.make_token(cfg, updated)) == updated
