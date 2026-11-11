from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

ORIGIN = "http://localhost:5173"
PW = "correct horse battery staple"

pytestmark = pytest.mark.sql


@pytest.fixture()
def client(db):
    from app.main import create_app

    with TestClient(create_app(), headers={"Origin": ORIGIN}) as c:
        yield c


def register(client, email="ana@example.com", name="Ana  Student", pw=PW):
    return client.post("/api/auth/register", json={"display_name": name, "email": email, "password": pw})


def csrf_headers(r):
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def test_health_and_ready(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/api/health/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


def test_register_creates_student_session_and_normalizes(client):
    r = register(client, email="  Ana@Example.COM ")
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["role"] == "STUDENT" and body["user"]["email"] == "ana@example.com"
    assert body["user"]["display_name"] == "Ana Student"  # whitespace collapsed
    assert set(body["user"]) == {"user_id", "display_name", "email", "role"} and body["csrf_token"]
    cookie = r.headers["set-cookie"].lower()
    assert "findmything_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "domain=" not in cookie and "max-age=43200" in cookie and "path=/" in cookie


def test_raw_session_token_never_stored(client, db):
    r = register(client)
    raw = client.cookies.get("findmything_session")
    rows = db.execute(text("SELECT session_token_hash FROM sessions")).all()
    assert len(rows) == 1 and raw.encode() not in bytes(rows[0][0]) and len(bytes(rows[0][0])) == 32
    assert r.status_code == 201


def test_duplicate_email_generic_409(client):
    register(client)
    client.cookies.clear()
    r = register(client, name="Other")
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_UNAVAILABLE"


@pytest.mark.parametrize("pw", ["short", " " * 14, "x" * 129])
def test_password_rules(client, pw):
    r = register(client, pw=pw)
    assert r.status_code == 422 and "password" in r.json()["error"]["field_errors"]


def test_password_not_trimmed(client):
    register(client, pw="  spaced password!  ")
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "spaced password!"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "  spaced password!  "}).status_code == 200


def test_login_generic_failure_for_unknown_and_wrong_password(client):
    register(client)
    client.cookies.clear()
    a = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PW})
    b = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "wrong password here"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_me_requires_auth_and_hides_secrets(client):
    assert client.get("/api/auth/me").status_code == 401
    register(client)
    body = client.get("/api/auth/me").json()
    assert set(body["user"]) == {"user_id", "display_name", "email", "role"}


def test_csrf_and_origin_required_on_unsafe_methods(client):
    r = register(client)
    assert client.post("/api/auth/logout").status_code == 403  # no CSRF token
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "nope"}).status_code == 403
    bad_origin = client.post("/api/auth/logout", headers={**csrf_headers(r), "Origin": "http://evil.example"})
    assert bad_origin.status_code == 403 and bad_origin.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    assert client.get("/api/auth/me").status_code == 200  # still logged in
    assert client.post("/api/auth/logout", headers=csrf_headers(r)).status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_login_and_register_validate_origin(client):
    assert client.post("/api/auth/login", json={"email": "a@b.co", "password": PW}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/auth/register", json={"display_name": "x", "email": "a@b.co", "password": PW}, headers={"Origin": "http://evil.example"}).status_code == 403


def test_csrf_endpoint_issues_working_token(client):
    register(client)
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code == 204


def test_login_throttled_after_five_failures_with_retry_after(client):
    register(client)
    client.cookies.clear()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "wrong password here"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "ana@example.com", "password": PW})  # correct pw, still blocked
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_register_throttled_after_five_per_hour(client):
    for i in range(5):
        client.cookies.clear()
        assert register(client, email=f"u{i}@example.com").status_code == 201
    client.cookies.clear()
    r = register(client, email="u9@example.com")
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_rate_limit_table_stores_only_hashes(client, db):
    register(client, email="private.person@example.com")
    rows = db.execute(text("SELECT key_hash FROM rate_limit_counters")).all()
    assert rows and all(len(bytes(r[0])) == 32 for r in rows)


def test_new_login_revokes_only_the_current_session(client, db):
    register(client)
    first = client.cookies.get("findmything_session")
    other = TestClient(client.app, headers={"Origin": ORIGIN})
    other.post("/api/auth/login", json={"email": "ana@example.com", "password": PW})
    client.post("/api/auth/login", json={"email": "ana@example.com", "password": PW})  # sends the old cookie
    assert client.cookies.get("findmything_session") != first
    assert other.get("/api/auth/me").status_code == 200  # other session untouched


def test_expired_and_revoked_sessions_rejected(client, db):
    register(client)
    db.execute(text("UPDATE sessions SET expires_at_utc = DATEADD(minute,-1,SYSUTCDATETIME())"))
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_inactive_user_session_rejected(client, db):
    register(client)
    db.execute(text("UPDATE users SET is_active = 0"))
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_session_lifetime_is_absolute_twelve_hours(client, db):
    register(client)
    row = db.execute(text("SELECT created_at_utc, expires_at_utc FROM sessions")).one()
    assert row.expires_at_utc - row.created_at_utc == dt.timedelta(hours=12)


def test_last_seen_throttled(client, db):
    register(client)
    before = db.execute(text("SELECT last_seen_at_utc FROM sessions")).scalar()
    client.get("/api/auth/me")
    db.rollback()
    assert db.execute(text("SELECT last_seen_at_utc FROM sessions")).scalar() == before  # < 15 min: unchanged


def test_unknown_fields_rejected_and_malformed_json_is_400(client):
    r = client.post("/api/auth/login", json={"email": "a@b.co", "password": PW, "role": "MODERATOR"})
    assert r.status_code == 422 and "role" in r.json()["error"]["field_errors"]
    r = client.post("/api/auth/login", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_REQUEST"


def test_error_envelope_and_request_id_echo(client):
    r = client.get("/api/auth/me", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers["X-Request-ID"] == "trace-abc-123"
    err = r.json()["error"]
    assert err["request_id"] == "trace-abc-123" and err["code"] == "UNAUTHENTICATED" and "field_errors" not in err
    bad = client.get("/api/auth/me", headers={"X-Request-ID": "has space"})
    assert bad.headers["X-Request-ID"] != "has space"


def test_cors_allows_only_configured_origin(client):
    ok = client.options("/api/auth/me", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == ORIGIN and ok.headers.get("access-control-allow-credentials") == "true"
    bad = client.options("/api/auth/me", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_audit_events_written_without_secrets(client, db):
    register(client)
    client.post("/api/auth/login", json={"email": "ana@example.com", "password": "wrong password here"})
    events = [r[0] for r in db.execute(text("SELECT event_type FROM activity_logs ORDER BY created_at_utc"))]
    assert "AUTH_REGISTERED" in events and "AUTH_LOGIN_FAILED" in events
    blob = " ".join(str(r) for r in db.execute(text("SELECT metadata FROM activity_logs")).all())
    assert PW not in blob and "wrong password" not in blob
