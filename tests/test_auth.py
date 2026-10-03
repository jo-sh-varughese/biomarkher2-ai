"""Accounts, sessions, roles and the admin console.

The portal now sits in front of medical images and records clinical
opinions under a person's name, so the parts tested hardest here are the
ones whose failure would be silent: a route reachable without the right
role, a session that outlives a disabled account, a lockout that tells an
attacker which emails exist, the last administrator locking everyone out,
a password that ends up anywhere in plain text.
"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.auth import (
    PERMISSIONS,
    AuthError,
    AuthStore,
    hash_password,
    verify_password,
)
from tests.portal_client import TEST_PASSWORD, Running

OTHER_PASSWORD = "another long passphrase 42"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return AuthStore(tmp_path / "accounts.db", clock=clock)


def _admin(store, email="admin@example.org", name="Ada Admin"):
    return store.create_user(email=email, name=name, role="admin", password=TEST_PASSWORD)


def _code(excinfo) -> str:
    return excinfo.value.code


class FakeAnalyzer:
    provenance = {"run": "artifacts/phase2_unet", "epoch": 4, "architecture": "unet_resnet18"}

    def heatmap_legend(self):
        return {"stops": [], "ticks": [], "fade_below": 0}


@pytest.fixture
def state(tmp_path, clock):
    from app.server import State

    return State(
        FakeAnalyzer(), tmp_path / "missing", tmp_path / "reviews.jsonl", tmp_path / "dist",
        auth=AuthStore(tmp_path / "accounts.db", clock=clock),
    )


# ------------------------------------------------------------ passwords --

def test_passwords_are_salted_hashes_that_verify():
    first, second = hash_password(TEST_PASSWORD), hash_password(TEST_PASSWORD)
    assert first != second, "every hash needs its own salt"
    assert first.startswith("scrypt$") and TEST_PASSWORD not in first
    assert verify_password(TEST_PASSWORD, first)
    assert not verify_password(TEST_PASSWORD + "x", first)
    assert not verify_password(TEST_PASSWORD, "!")
    assert not verify_password(TEST_PASSWORD, "garbage")


def test_no_password_or_session_token_is_stored_in_plain_text(store, tmp_path):
    _admin(store)
    _, token, _ = store.authenticate("admin@example.org", TEST_PASSWORD)
    raw = (tmp_path / "accounts.db").read_bytes()
    wal = tmp_path / "accounts.db-wal"
    raw += wal.read_bytes() if wal.exists() else b""
    assert TEST_PASSWORD.encode() not in raw
    assert token.encode() not in raw


@pytest.mark.parametrize("password, code", [
    ("short1", "password_too_short"),
    ("password123", "password_common"),
    ("Password2026!", "password_common"),
    ("ada@example.org", "password_like_email"),
    ("aaaaaaaaaaaaaaa", "password_repetitive"),
    ("x" * 300, "password_too_long"),
])
def test_password_policy_refuses_guessable_passwords(store, password, code):
    with pytest.raises(AuthError) as excinfo:
        store.check_password(password, email="ada@example.org")
    assert _code(excinfo) == code


def test_password_minimum_follows_the_setting(store):
    store.check_password("twelve chars", email="a@b.org")
    store.update_settings({"password_min_length": 14}, actor=None)
    with pytest.raises(AuthError) as excinfo:
        store.check_password("twelve chars", email="a@b.org")
    assert _code(excinfo) == "password_too_short" and excinfo.value.extra["min"] == 14


# ---------------------------------------------------------------- users --

def test_emails_are_normalised_and_unique_regardless_of_case(store):
    user = store.create_user(email="  Anita.Menon@GMCK.edu.in ", name="Anita", role="pathologist",
                             password=TEST_PASSWORD)
    assert user["email"] == "anita.menon@gmck.edu.in"
    with pytest.raises(AuthError) as excinfo:
        store.create_user(email="ANITA.menon@gmck.edu.in", name="Other", role="viewer", password=TEST_PASSWORD)
    assert _code(excinfo) == "email_taken"
    assert "password_hash" not in user


def test_user_fields_are_validated(store):
    for kwargs, code in (
        ({"email": "not-an-email"}, "email_invalid"),
        ({"name": "A"}, "name_invalid"),
        ({"role": "superuser"}, "role_invalid"),
        ({"title": "x" * 81}, "field_too_long"),
    ):
        base = {"email": "v@example.org", "name": "Valid Name", "role": "viewer", "password": TEST_PASSWORD}
        with pytest.raises(AuthError) as excinfo:
            store.create_user(**{**base, **kwargs})
        assert _code(excinfo) == code


def test_every_role_has_exactly_the_documented_permissions():
    assert PERMISSIONS["viewer"] == {"view", "analyze", "report"}
    assert PERMISSIONS["pathologist"] == PERMISSIONS["viewer"] | {"review", "annotate"}
    assert PERMISSIONS["admin"] == PERMISSIONS["pathologist"] | {"admin"}


def test_the_last_administrator_cannot_be_removed(store):
    admin = _admin(store)
    other = store.create_user(email="p@example.org", name="Path", role="pathologist", password=TEST_PASSWORD)
    for action in (
        lambda: store.update_user(admin["id"], {"role": "viewer"}, actor=other),
        lambda: store.update_user(admin["id"], {"status": "disabled"}, actor=other),
        lambda: store.delete_user(admin["id"], actor=other),
    ):
        with pytest.raises(AuthError) as excinfo:
            action()
        assert _code(excinfo) == "last_admin"
    # With a second administrator, the first can step down.
    store.update_user(other["id"], {"role": "admin"}, actor=admin)
    assert store.update_user(admin["id"], {"role": "viewer"}, actor=other)["role"] == "viewer"


def test_an_administrator_cannot_demote_disable_or_delete_themselves(store):
    admin = _admin(store)
    _admin(store, email="second@example.org", name="Second Admin")
    for change in ({"role": "pathologist"}, {"status": "disabled"}):
        with pytest.raises(AuthError) as excinfo:
            store.update_user(admin["id"], change, actor=admin)
        assert _code(excinfo) == "self_change"
    with pytest.raises(AuthError) as excinfo:
        store.delete_user(admin["id"], actor=admin)
    assert _code(excinfo) == "self_delete"


def test_update_rejects_fields_that_are_not_editable(store):
    admin = _admin(store)
    user = store.create_user(email="v@example.org", name="Viewer", role="viewer", password=TEST_PASSWORD)
    with pytest.raises(AuthError) as excinfo:
        store.update_user(user["id"], {"password_hash": "x"}, actor=admin)
    assert _code(excinfo) == "field_unknown"
    with pytest.raises(AuthError) as excinfo:
        store.update_profile(user["id"], {"role": "admin"})
    assert _code(excinfo) == "field_unknown"


# -------------------------------------------------------------- sign-in --

def test_sign_in_starts_a_session_and_is_audited(store):
    _admin(store)
    user, token, session = store.authenticate("ADMIN@example.org", TEST_PASSWORD, ip="10.0.0.5")
    assert user["email"] == "admin@example.org" and user["last_login_ip"] == "10.0.0.5"
    resolved_user, resolved_session = store.resolve(token)
    assert resolved_user["id"] == user["id"] and resolved_session["csrf"] == session["csrf"]
    assert store.list_audit(category="signin")["events"][0]["action"] == "auth.login"


def test_wrong_password_and_unknown_email_get_the_same_answer(store):
    _admin(store)
    with pytest.raises(AuthError) as wrong:
        store.authenticate("admin@example.org", "not the password at all")
    with pytest.raises(AuthError) as unknown:
        store.authenticate("nobody@example.org", "not the password at all")
    assert (wrong.value.code, str(wrong.value), wrong.value.status) == (
        unknown.value.code, str(unknown.value), unknown.value.status)


def test_repeated_failures_lock_the_account_until_it_expires_or_is_unlocked(store, clock):
    admin = _admin(store)
    viewer = store.create_user(email="v@example.org", name="Viewer", role="viewer", password=TEST_PASSWORD)
    for _ in range(4):
        with pytest.raises(AuthError) as excinfo:
            store.authenticate("v@example.org", "wrong wrong wrong")
        assert _code(excinfo) == "invalid_credentials"
    with pytest.raises(AuthError) as excinfo:
        store.authenticate("v@example.org", "wrong wrong wrong")
    assert _code(excinfo) == "locked" and excinfo.value.extra["minutes"] == 15
    # Locked means locked -- even the right password is refused.
    with pytest.raises(AuthError) as excinfo:
        store.authenticate("v@example.org", TEST_PASSWORD)
    assert _code(excinfo) == "locked"
    assert store.get_user(viewer["id"])["locked"]

    store.unlock_user(viewer["id"], actor=admin)
    assert store.authenticate("v@example.org", TEST_PASSWORD)[0]["id"] == viewer["id"]

    for _ in range(5):
        with pytest.raises(AuthError):
            store.authenticate("v@example.org", "wrong wrong wrong")
    clock.advance(minutes=16)
    assert not store.get_user(viewer["id"])["locked"]
    # One mistake after the lock ran out does not re-lock.
    with pytest.raises(AuthError) as excinfo:
        store.authenticate("v@example.org", "wrong wrong wrong")
    assert _code(excinfo) == "invalid_credentials"
    assert store.authenticate("v@example.org", TEST_PASSWORD)[0]["failed_attempts"] == 0


def test_unknown_emails_lock_out_exactly_like_real_ones(store):
    """Otherwise the lockout message would reveal which addresses exist."""
    answers = []
    for _ in range(5):
        with pytest.raises(AuthError) as excinfo:
            store.authenticate("ghost@example.org", "wrong wrong wrong")
        answers.append(_code(excinfo))
    assert answers == ["invalid_credentials"] * 4 + ["locked"]


def test_disabled_and_pending_accounts_are_told_only_with_the_right_password(store):
    admin = _admin(store)
    viewer = store.create_user(email="v@example.org", name="Viewer", role="viewer", password=TEST_PASSWORD)
    store.update_user(viewer["id"], {"status": "disabled"}, actor=admin)
    with pytest.raises(AuthError) as excinfo:
        store.authenticate("v@example.org", "wrong wrong wrong")
    assert _code(excinfo) == "invalid_credentials"
    with pytest.raises(AuthError) as excinfo:
        store.authenticate("v@example.org", TEST_PASSWORD)
    assert _code(excinfo) == "account_disabled"

    store.request_access(name="New Person", email="new@example.org", password=TEST_PASSWORD)
    with pytest.raises(AuthError) as excinfo:
        store.authenticate("new@example.org", TEST_PASSWORD)
    assert _code(excinfo) == "account_pending"


def test_sessions_end_after_the_idle_timeout_and_the_maximum_age(store, clock):
    _admin(store)
    _, token, _ = store.authenticate("admin@example.org", TEST_PASSWORD)
    clock.advance(minutes=59)
    assert store.resolve(token) is not None
    clock.advance(minutes=61)
    assert store.resolve(token) is None, "an hour idle ends the session"

    _, token, _ = store.authenticate("admin@example.org", TEST_PASSWORD)
    for _ in range(13):
        clock.advance(minutes=55)
        assert store.resolve(token) is not None
    clock.advance(minutes=55)
    assert store.resolve(token) is None, "12 hours is the ceiling however active"


def test_keep_me_signed_in_skips_the_idle_timeout_but_not_its_own_limit(store, clock):
    _admin(store)
    _, token, session = store.authenticate("admin@example.org", TEST_PASSWORD, remember=True)
    assert session["remember"]
    clock.advance(days=3)
    assert store.resolve(token) is not None
    clock.advance(days=5)
    assert store.resolve(token) is None
    store.update_settings({"allow_remember_me": False}, actor=None)
    _, _, session = store.authenticate("admin@example.org", TEST_PASSWORD, remember=True)
    assert not session["remember"]


def test_disabling_or_deleting_an_account_ends_its_sessions(store):
    admin = _admin(store)
    store.create_user(email="p@example.org", name="Path", role="pathologist", password=TEST_PASSWORD)
    user, token, _ = store.authenticate("p@example.org", TEST_PASSWORD)
    store.update_user(user["id"], {"status": "disabled"}, actor=admin)
    assert store.resolve(token) is None
    store.update_user(user["id"], {"status": "active"}, actor=admin)
    _, token, _ = store.authenticate("p@example.org", TEST_PASSWORD)
    store.delete_user(user["id"], actor=admin)
    assert store.resolve(token) is None


def test_changing_a_password_needs_the_current_one_and_ends_other_sessions(store):
    _admin(store)
    user, keep, keep_session = store.authenticate("admin@example.org", TEST_PASSWORD)
    _, other, _ = store.authenticate("admin@example.org", TEST_PASSWORD)
    with pytest.raises(AuthError) as excinfo:
        store.change_password(user["id"], current="wrong wrong wrong", new=OTHER_PASSWORD)
    assert _code(excinfo) == "wrong_current_password"
    with pytest.raises(AuthError) as excinfo:
        store.change_password(user["id"], current=TEST_PASSWORD, new=TEST_PASSWORD)
    assert _code(excinfo) == "password_reused"
    store.change_password(user["id"], current=TEST_PASSWORD, new=OTHER_PASSWORD,
                          keep_session=keep_session["id_hash"])
    assert store.resolve(keep) is not None and store.resolve(other) is None
    assert store.authenticate("admin@example.org", OTHER_PASSWORD)


def test_an_administrator_set_password_must_be_changed_at_next_sign_in(store):
    admin = _admin(store)
    viewer = store.create_user(email="v@example.org", name="Viewer", role="viewer", password=TEST_PASSWORD)
    _, token, _ = store.authenticate("v@example.org", TEST_PASSWORD)
    updated = store.admin_set_password(viewer["id"], OTHER_PASSWORD, must_change=True, actor=admin)
    assert updated["must_change_password"]
    assert store.resolve(token) is None, "a reset ends the sessions the old password opened"
    user, _, _ = store.authenticate("v@example.org", OTHER_PASSWORD)
    assert user["must_change_password"]
    with pytest.raises(AuthError) as excinfo:
        store.admin_set_password(admin["id"], OTHER_PASSWORD, actor=admin)
    assert _code(excinfo) == "use_profile"


# ------------------------------------------------------ one-time links --

def test_an_invitation_link_sets_the_password_once_and_then_expires(store, clock):
    admin = _admin(store)
    invited = store.create_user(email="new@example.org", name="New Person", role="pathologist",
                                password=None, status="invited", actor=admin)
    assert not invited["has_password"]
    with pytest.raises(AuthError):
        store.authenticate("new@example.org", "")
    token, _ = store.create_link(invited["id"], kind="invite", actor=admin)
    assert store.inspect_link(token)["email"] == "new@example.org"
    user, session_token, _ = store.use_link(token, OTHER_PASSWORD)
    assert user["status"] == "active" and store.resolve(session_token)
    with pytest.raises(AuthError) as excinfo:
        store.use_link(token, "yet another passphrase")
    assert _code(excinfo) == "link_expired"

    token, _ = store.create_link(invited["id"], kind="reset", actor=admin)
    clock.advance(hours=25)
    with pytest.raises(AuthError) as excinfo:
        store.inspect_link(token)
    assert _code(excinfo) == "link_expired"


def test_a_new_link_cancels_the_previous_one(store):
    admin = _admin(store)
    viewer = store.create_user(email="v@example.org", name="Viewer", role="viewer", password=TEST_PASSWORD)
    first, _ = store.create_link(viewer["id"], kind="reset", actor=admin)
    second, _ = store.create_link(viewer["id"], kind="reset", actor=admin)
    with pytest.raises(AuthError):
        store.inspect_link(first)
    assert store.inspect_link(second)["kind"] == "reset"


# ------------------------------------------------------ first-run setup --

def test_setup_creates_the_first_administrator_once(store):
    assert store.needs_setup()
    token = store.setup_token()
    with pytest.raises(AuthError) as excinfo:
        store.complete_setup(token="wrong", name="Ada", email="ada@example.org", password=TEST_PASSWORD)
    assert _code(excinfo) == "setup_token_invalid"
    user, _, _ = store.complete_setup(token=token, name="Ada Admin", email="ada@example.org",
                                      password=TEST_PASSWORD)
    assert user["role"] == "admin" and not store.needs_setup()
    assert store.setup_token() is None
    with pytest.raises(AuthError) as excinfo:
        store.complete_setup(token=token, name="Eve", email="eve@example.org", password=TEST_PASSWORD)
    assert _code(excinfo) == "setup_done"


# ------------------------------------------------------ access requests --

def test_an_access_request_waits_for_approval_and_duplicates_look_the_same(store):
    admin = _admin(store)
    store.request_access(name="Dr New", email="new@example.org", password=TEST_PASSWORD,
                         registration="tc-1234", title="Resident", note="Joining the HER2 study")
    pending = store.find_user("new@example.org")
    assert pending["status"] == "pending" and pending["registration"] == "TC-1234"
    assert pending["request_note"] == "Joining the HER2 study"
    # An existing address gets exactly the same (silent) answer.
    store.request_access(name="Somebody", email="admin@example.org", password=TEST_PASSWORD)
    assert store.find_user("admin@example.org")["name"] == "Ada Admin"

    approved = store.approve_user(pending["id"], role="pathologist", actor=admin)
    assert approved["status"] == "active" and approved["role"] == "pathologist"
    assert store.authenticate("new@example.org", TEST_PASSWORD)[0]["id"] == pending["id"]


def test_access_requests_can_be_turned_off_and_are_rate_limited(store):
    _admin(store)
    store.update_settings({"allow_access_requests": False}, actor=None)
    with pytest.raises(AuthError) as excinfo:
        store.request_access(name="Dr New", email="new@example.org", password=TEST_PASSWORD)
    assert _code(excinfo) == "requests_closed"
    store.update_settings({"allow_access_requests": True}, actor=None)
    for n in range(5):
        store.request_access(name="Dr New", email=f"n{n}@example.org", password=TEST_PASSWORD, ip="1.2.3.4")
    with pytest.raises(AuthError) as excinfo:
        store.request_access(name="Dr New", email="n9@example.org", password=TEST_PASSWORD, ip="1.2.3.4")
    assert _code(excinfo) == "rate_limited"


def test_no_access_requests_before_there_is_an_administrator(store):
    with pytest.raises(AuthError) as excinfo:
        store.request_access(name="Dr New", email="new@example.org", password=TEST_PASSWORD)
    assert _code(excinfo) == "requests_closed"


# ------------------------------------------------------------- settings --

def test_settings_are_validated_and_every_change_is_audited(store):
    admin = _admin(store)
    for change, code in (
        ({"session_idle_minutes": 1}, "setting_range"),
        ({"session_idle_minutes": "60"}, "setting_invalid"),
        ({"allow_remember_me": "yes"}, "setting_invalid"),
        ({"announcement": "x" * 300}, "setting_range"),
        ({"no_such_setting": 1}, "setting_unknown"),
    ):
        with pytest.raises(AuthError) as excinfo:
            store.update_settings(change, actor=admin)
        assert _code(excinfo) == code
    settings = store.update_settings({"session_idle_minutes": 30, "announcement": "  Maintenance  at 18:00 "},
                                     actor=admin)
    assert settings["session_idle_minutes"] == 30 and settings["announcement"] == "Maintenance at 18:00"
    event = store.list_audit(category="settings")["events"][0]
    assert event["actor"]["email"] == "admin@example.org"
    assert event["detail"]["changes"]["session_idle_minutes"] == {"from": 60, "to": 30}


def test_the_audit_log_filters_pages_and_exports(store):
    admin = _admin(store)
    for n in range(3):
        store.create_user(email=f"u{n}@example.org", name=f"User {n}", role="viewer",
                          password=TEST_PASSWORD, actor=admin)
    with pytest.raises(AuthError):
        store.authenticate("u1@example.org", "wrong wrong wrong")
    first = store.list_audit(limit=2)
    assert len(first["events"]) == 2 and first["next"]
    rest = store.list_audit(before=first["next"], limit=100)
    assert all(e["id"] < first["next"] for e in rest["events"])
    assert {e["action"] for e in store.list_audit(category="signin")["events"]} == {"auth.login_failed"}
    assert store.list_audit(q="u2@example.org")["events"][0]["target"]["email"] == "u2@example.org"
    lines = store.audit_csv(category="accounts").splitlines()
    assert lines[0].startswith("time_utc,action,actor_email") and len(lines) == 5


# ----------------------------------------------------------------- HTTP --

PROTECTED = [
    ("GET", "/api/context"),
    ("GET", "/api/reviews"),
    ("POST", "/api/analyze"),
    ("POST", "/api/report"),
    ("POST", "/api/review"),
    ("POST", "/api/annotations"),
    ("GET", "/api/auth/sessions"),
    ("GET", "/api/admin/users"),
    ("GET", "/api/admin/audit.csv"),
    ("PATCH", "/api/admin/settings"),
]


def test_every_protected_route_refuses_a_signed_out_request(state):
    with Running(state, sign_in=False) as srv:
        for method, path in PROTECTED:
            response = srv.send(method, path, {} if method != "GET" else None)
            assert response.status == 401, (method, path)
            assert response.json["code"] == "unauthenticated"
        # "Who am I" answers rather than refusing, so a signed-out visit to
        # the sign-in page does not log an error.
        me = srv.send("GET", "/api/auth/me")
        assert me.status == 200 and me.json == {"user": None}


def test_sign_in_sets_a_hardened_cookie_and_never_returns_a_hash(state):
    state.auth.create_user(email="p@example.org", name="Path", role="pathologist", password=TEST_PASSWORD)
    with Running(state, sign_in=False) as srv:
        response = srv.browser.login("p@example.org")
        cookie = response.headers["set-cookie"]
    assert response.status == 200
    for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
        assert flag in cookie
    assert "Secure" not in cookie and "Max-Age" not in cookie, "a browser-session cookie by default"
    body = response.body.decode()
    assert "password_hash" not in body and "scrypt$" not in body and TEST_PASSWORD not in body
    assert response.json["user"]["role"] == "pathologist"
    assert response.json["permissions"] == sorted(PERMISSIONS["pathologist"])


def test_secure_cookies_and_hsts_when_served_over_https(state):
    state.secure_cookies = True
    with Running(state, sign_in=False) as srv:
        state.auth.create_user(email="p@example.org", name="Path", role="pathologist", password=TEST_PASSWORD)
        response = srv.browser.login("p@example.org", remember=True)
    assert "Secure" in response.headers["set-cookie"] and "Max-Age=" in response.headers["set-cookie"]
    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_state_changing_requests_need_the_sessions_csrf_token(state):
    with Running(state, role="pathologist") as srv:
        body = {"patch_id": "a.png", "score": "2+"}
        missing = srv.send("POST", "/api/review", body, csrf=False)
        forged = srv.send("POST", "/api/review", body, csrf=False, headers={"X-CSRF-Token": "forged"})
        good = srv.send("POST", "/api/review", body)
    assert missing.status == forged.status == 403 and missing.json["code"] == "csrf"
    assert good.status == 200


def test_bodies_must_be_json(state):
    with Running(state, sign_in=False) as srv:
        response = srv.send("POST", "/api/auth/login", None, headers={
            "Content-Type": "application/x-www-form-urlencoded", "Content-Length": "9",
        })
    assert response.status in (400, 415)


@pytest.mark.parametrize("role, allowed", [
    ("viewer", {"context", "reviews"}),
    ("pathologist", {"context", "reviews", "review", "annotate"}),
    ("admin", {"context", "reviews", "review", "annotate", "admin"}),
])
def test_each_role_reaches_exactly_its_routes(state, role, allowed):
    attempts = {
        "context": ("GET", "/api/context", None),
        "reviews": ("GET", "/api/reviews", None),
        "review": ("POST", "/api/review", {"patch_id": "a.png", "score": "1+"}),
        "annotate": ("POST", "/api/annotations",
                     {"patch_id": "a.png", "x": 0, "y": 0, "w": 0.2, "h": 0.2, "note": "here"}),
        "admin": ("GET", "/api/admin/overview", None),
    }
    with Running(state, role=role) as srv:
        reached = set()
        for name, (method, path, body) in attempts.items():
            response = srv.send(method, path, body)
            assert response.status in (200, 403), (name, response.status, response.body)
            if response.status == 200:
                reached.add(name)
            else:
                assert response.json["code"] == "forbidden"
    assert reached == allowed


def test_a_temporary_password_must_be_replaced_before_anything_else(state):
    state.auth.create_user(email="v@example.org", name="Viewer", role="viewer", password=TEST_PASSWORD,
                           must_change_password=True)
    with Running(state, sign_in=False) as srv:
        me = srv.browser.login("v@example.org")
        assert me.json["user"]["must_change_password"]
        blocked = srv.send("GET", "/api/context")
        assert blocked.status == 403 and blocked.json["code"] == "password_change_required"
        assert srv.send("GET", "/api/auth/me").status == 200
        changed = srv.send("POST", "/api/auth/password", {"current": TEST_PASSWORD, "new": OTHER_PASSWORD})
        assert changed.status == 200 and not changed.json["user"]["must_change_password"]
        assert srv.send("GET", "/api/context").status == 200


def test_the_admin_console_manages_an_account_end_to_end(state):
    with Running(state, role="admin", name="Ada Admin") as srv:
        created = srv.send("POST", "/api/admin/users", {
            "name": "Dr Ravi Nair", "email": "ravi@example.org", "role": "pathologist",
            "registration": "tc-5521", "access": "password", "password": OTHER_PASSWORD,
            "must_change_password": True,
        })
        assert created.status == 200, created.body
        user = created.json["user"]
        assert user["registration"] == "TC-5521" and user["must_change_password"]

        ravi = srv.client()
        assert ravi.login("ravi@example.org", OTHER_PASSWORD).status == 200
        assert ravi.send("POST", "/api/auth/password",
                         {"current": OTHER_PASSWORD, "new": "ravi's own passphrase"}).status == 200

        listing = srv.send("GET", "/api/admin/users?q=ravi").json["users"]
        assert [u["email"] for u in listing] == ["ravi@example.org"]
        detail = srv.send("GET", f"/api/admin/users/{user['id']}").json
        assert len(detail["sessions"]) == 1 and detail["activity"]

        updated = srv.send("PATCH", f"/api/admin/users/{user['id']}", {"role": "viewer", "title": "Observer"})
        assert updated.json["user"]["role"] == "viewer"
        assert ravi.send("POST", "/api/review", {"patch_id": "a.png", "score": "1+"}).status == 403

        assert srv.send("PATCH", f"/api/admin/users/{user['id']}", {"status": "disabled"}).status == 200
        assert ravi.send("GET", "/api/auth/me").json["user"] is None, "disabling ends the session at once"
        assert ravi.send("GET", "/api/context").status == 401

        assert srv.send("DELETE", f"/api/admin/users/{user['id']}").status == 200
        assert srv.send("GET", f"/api/admin/users/{user['id']}").status == 404

        # The console refuses to let the only administrator lock everyone out.
        me = srv.user["id"]
        refused = srv.send("PATCH", f"/api/admin/users/{me}", {"role": "viewer"})
        assert refused.status == 409 and refused.json["code"] == "self_change"


def test_an_invitation_over_http_ends_signed_in_with_the_chosen_password(state):
    with Running(state, role="admin") as srv:
        created = srv.send("POST", "/api/admin/users", {
            "name": "Dr Leela Das", "email": "leela@example.org", "role": "viewer", "access": "invite",
        }).json
        assert created["user"]["status"] == "invited"
        token = created["link"]["token"]
        assert created["link"]["path"] == f"/reset?token={token}"

        leela = srv.client()
        info = leela.send("POST", "/api/auth/link/inspect", {"token": token})
        assert info.json["email"] == "leela@example.org" and info.json["kind"] == "invite"
        used = leela.send("POST", "/api/auth/link", {"token": token, "password": OTHER_PASSWORD})
        assert used.status == 200 and leela.cookie
        leela.csrf = used.json["csrf"]
        assert leela.send("GET", "/api/context").status == 200
        again = srv.client().send("POST", "/api/auth/link", {"token": token, "password": "a different one!"})
        assert again.status == 410


def test_first_run_setup_over_http(state):
    with Running(state, sign_in=False) as srv:
        config = srv.send("GET", "/api/auth/config").json
        assert config["mode"] == "server" and config["setup_required"]
        assert not config["allow_access_requests"]
        body = {"name": "Ada Admin", "email": "ada@example.org", "password": TEST_PASSWORD}
        assert srv.send("POST", "/api/auth/setup", {**body, "token": "guess"}).status == 403
        done = srv.send("POST", "/api/auth/setup", {**body, "token": state.auth.setup_token()})
        assert done.status == 200 and done.json["user"]["role"] == "admin"
        assert not srv.send("GET", "/api/auth/config").json["setup_required"]


def test_signing_out_ends_the_session_on_the_server(state):
    with Running(state, role="viewer") as srv:
        stolen_cookie = srv.browser.cookie
        response = srv.send("POST", "/api/auth/logout")
        assert response.status == 200 and "Max-Age=0" in response.headers["set-cookie"]
        replay = srv.client()
        replay.cookie = stolen_cookie
        assert replay.send("GET", "/api/auth/me").json["user"] is None
        assert replay.send("GET", "/api/reviews").status == 401


def test_people_manage_their_own_sessions_and_profile(state):
    with Running(state, role="pathologist", name="Dr A Menon") as srv:
        phone = srv.client()
        phone.login(srv.email)
        sessions = srv.send("GET", "/api/auth/sessions").json["sessions"]
        assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
        own = next(s for s in sessions if s["current"])
        assert srv.send("DELETE", f"/api/auth/sessions/{own['id']}").status == 409
        assert srv.send("POST", "/api/auth/sessions/revoke-others").json["revoked"] == 1
        assert phone.send("GET", "/api/auth/me").json["user"] is None

        profile = srv.send("PATCH", "/api/auth/profile", {"name": "Dr Anita Menon", "registration": "tc-9"})
        assert profile.json["user"]["name"] == "Dr Anita Menon" and profile.json["user"]["registration"] == "TC-9"
        escalate = srv.send("PATCH", "/api/auth/profile", {"role": "admin"})
        assert escalate.status == 400 and escalate.json["code"] == "field_unknown"


def test_security_headers_are_on_every_response(state):
    with Running(state, sign_in=False) as srv:
        for path in ("/api/auth/config", "/api/context", "/login"):
            headers = srv.send("GET", path).headers
            assert headers["x-content-type-options"] == "nosniff", path
            assert headers["x-frame-options"] == "DENY", path
            assert headers["referrer-policy"] == "same-origin", path
            assert headers["cache-control"] == "no-store", path


def test_admin_exports_are_downloads_and_are_audited(state):
    with Running(state, role="admin") as srv:
        srv.send("POST", "/api/review", {"patch_id": "a.png", "score": "0"})
        users = srv.send("GET", "/api/admin/users.csv")
        audit = srv.send("GET", "/api/admin/audit.csv?category=signin")
        reviews = srv.send("GET", "/api/admin/export/reviews.jsonl")
        system = srv.send("GET", "/api/admin/system").json
    assert users.headers["content-type"].startswith("text/csv")
    assert "attachment" in users.headers["content-disposition"]
    assert users.body.decode().splitlines()[1].startswith("AB,admin@example.org,admin,active")
    assert audit.body.decode().startswith("time_utc,action")
    assert json.loads(reviews.body.decode().splitlines()[0])["score"] == "0"
    exported = state.auth.list_audit(category="data")["events"]
    assert {e["detail"]["file"] for e in exported} == {"users.csv", "audit.csv", "reviews.jsonl"}
    assert {c["id"] for c in system["checks"]} >= {"admins", "transport", "model", "conformal"}
    assert system["storage"]["reviews"]["entries"] == 1


def test_unknown_api_paths_and_methods_are_json_errors(state):
    with Running(state, sign_in=False) as srv:
        missing = srv.send("GET", "/api/nope")
        wrong_method = srv.send("DELETE", "/api/auth/config")
    assert missing.status == 404 and missing.json["code"] == "not_found"
    assert wrong_method.status == 405


def test_the_console_log_never_shows_a_one_time_token(capsys, state):
    from app.server import Handler

    handler = Handler.__new__(Handler)
    handler.client_address = ("127.0.0.1", 5555)
    handler.log_message('"%s" %s %s', "GET /reset?token=SECRET-TOKEN-123&x=1 HTTP/1.1", "200", "-")
    out = capsys.readouterr().out
    assert "SECRET-TOKEN-123" not in out and "token=[redacted]" in out


# ------------------------------------------------------------------ CLI --

def test_biomark_admin_creates_resets_and_unlocks(tmp_path, monkeypatch, capsys):
    from app.admin_cli import main

    db = str(tmp_path / "cli.db")
    monkeypatch.setattr("sys.stdin", io.StringIO(TEST_PASSWORD + "\n"))
    main(["--db", db, "create-admin", "--email", "Ops@Example.org", "--name", "Ops Admin", "--password-stdin"])
    store = AuthStore(db)
    admin = store.find_user("ops@example.org")
    assert admin["role"] == "admin" and store.authenticate("ops@example.org", TEST_PASSWORD)

    monkeypatch.setattr("sys.stdin", io.StringIO(OTHER_PASSWORD + "\n"))
    main(["--db", db, "reset-password", "--email", "ops@example.org", "--password-stdin"])
    assert AuthStore(db).find_user("ops@example.org")["must_change_password"]

    main(["--db", db, "list-users"])
    assert "ops@example.org" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--db", db, "unlock", "--email", "nobody@example.org"])


def test_the_schema_survives_reopening(tmp_path):
    first = AuthStore(tmp_path / "a.db")
    _admin(first)
    second = AuthStore(tmp_path / "a.db")
    assert second.find_user("admin@example.org")["role"] == "admin"
    with sqlite3.connect(tmp_path / "a.db") as db:
        assert db.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == "1"


def test_health_endpoint_is_public_and_says_nothing_sensitive(state):
    """Container health checks call it without a session; it must not leak details."""
    with Running(state, sign_in=False) as srv:
        response = srv.send("GET", "/api/health")
    assert response.status == 200 and response.json["status"] == "ok"
    assert set(response.json) == {"status", "stain_model", "prescore_model", "slides"}
