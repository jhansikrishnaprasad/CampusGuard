"""Login-free local mode (CAMPUS_REQUIRE_LOGIN=false, the shipped default) and the strict mode used by the security tests."""
from fastapi.testclient import TestClient
from app import config
from app.main import app


def test_no_login_mode_opens_directly_as_admin(monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_LOGIN", False)
    with TestClient(app) as anon:                       # no cookie, no sign-in
        me = anon.get("/api/auth/me")
        assert me.status_code == 200 and me.json()["role"] == "admin" and me.json()["login_required"] is False
        assert anon.get("/api/dashboard").status_code == 200
        assert anon.get("/api/compliance/overview").status_code == 200


def test_strict_mode_still_requires_login(monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_LOGIN", True)
    with TestClient(app) as anon:
        assert anon.get("/api/auth/me").status_code == 401 and anon.get("/api/dashboard").status_code == 401
