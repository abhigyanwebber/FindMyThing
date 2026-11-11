"""Authenticated API client helpers for tests."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from tests.helpers import make_user

ORIGIN = "http://localhost:5173"
PASSWORD = "correct horse battery staple"  # matches tests.helpers.pw_hash()


class Api:
    """TestClient wrapper that always sends Origin and the session's CSRF token."""

    def __init__(self, app, user, csrf: str):
        self.http = TestClient(app, headers={"Origin": ORIGIN})
        self.user = user
        self.csrf = csrf

    def _h(self, extra=None):
        return {"X-CSRF-Token": self.csrf, **(extra or {})}

    def get(self, url, **kw):
        return self.http.get(url, **kw)

    def post(self, url, json=None, **kw):
        headers = self._h(kw.pop("headers", None))
        return self.http.post(url, json=json, headers=headers, **kw) if json is not None or "files" not in kw else self.http.post(url, headers=headers, **kw)

    def patch(self, url, json=None, **kw):
        return self.http.patch(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.http.request("DELETE", url, headers=self._h(kw.pop("headers", None)), **kw)

    def delete_json(self, url, json):
        return self.http.request("DELETE", url, json=json, headers=self._h())


def login_api(app, db, role: str = "STUDENT", name: str = "Test User") -> Api:
    user = make_user(db, role, name)
    db.commit()
    c = TestClient(app, headers={"Origin": ORIGIN})
    r = c.post("/api/auth/login", json={"email": user.email_normalized, "password": PASSWORD})
    assert r.status_code == 200, r.text
    api = Api(app, user, r.json()["csrf_token"])
    api.http.cookies.update(c.cookies)
    return api


def report_body(rtype="FOUND", category_id=None, location_id=None, **over):
    from tests.helpers import cat, loc

    body = {
        "report_type": rtype, "category_id": str(category_id or cat()), "location_id": str(location_id or loc()),
        "title": "Black laptop bag", "description": "Black laptop bag with a charger inside",
        "occurred_on": dt.date.today().isoformat(),
    }
    body.update(over)
    return body


def login_existing(app, user) -> Api:
    """Open an additional independent session for an existing user (used by concurrency tests)."""
    c = TestClient(app, headers={"Origin": ORIGIN})
    r = c.post("/api/auth/login", json={"email": user.email_normalized, "password": PASSWORD})
    assert r.status_code == 200, r.text
    api = Api(app, user, r.json()["csrf_token"])
    api.http.cookies.update(c.cookies)
    return api