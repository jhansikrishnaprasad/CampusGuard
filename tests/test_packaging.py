"""Windows-packaging support: launcher helpers, writable-home redirection, clean-shutdown endpoint, build files.

These tests do NOT build the .exe (PyInstaller needs Windows). The real packaging test is `build_exe.ps1`, which runs `CampusGuard.exe --selftest`.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.routers import system

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import launcher  # noqa: E402

PW = "test-password-123"


def test_home_dir_is_outside_program_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("CAMPUS_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert launcher.home_dir() == (tmp_path / "CampusGuard").resolve()
    monkeypatch.setenv("CAMPUS_HOME", str(tmp_path / "custom"))
    assert launcher.home_dir() == (tmp_path / "custom").resolve()


def test_prepare_home_creates_folders_and_never_overwrites_env(tmp_path):
    launcher.prepare_home(tmp_path)
    assert all((tmp_path / d).is_dir() for d in ("data", "models", "reference_images", "logs")) and (tmp_path / ".env").exists()
    (tmp_path / ".env").write_text("MINE=1")
    launcher.prepare_home(tmp_path)
    assert (tmp_path / ".env").read_text() == "MINE=1"


def test_find_free_port_skips_busy_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1); busy = s.getsockname()[1]
    try:
        assert launcher.find_free_port(busy) != busy
    finally:
        s.close()


def test_campus_home_redirects_all_writable_paths(tmp_path):
    code = "from app import config as c; print(c.BASE_DIR); print(c.DATA_DIR); print(c.MODELS_DIR); print(c.resolve_path('models/x.pt')); print(c.STATIC_DIR.is_dir())"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, CAMPUS_HOME=str(tmp_path))).stdout.split("\n")
    assert out[0] == str(tmp_path.resolve()) and out[1].startswith(str(tmp_path.resolve())) and out[2].startswith(str(tmp_path.resolve()))
    assert out[3] == str(tmp_path.resolve() / "models" / "x.pt") and out[4] == "True"      # static files stay with the code, data goes to the home


def test_unwritable_home_gives_readable_error():
    r = subprocess.run([sys.executable, str(ROOT / "launcher.py")], capture_output=True, text=True, env=dict(os.environ, CAMPUS_HOME="/proc/forbidden/x"))
    assert r.returncode == 2 and "writable folder" in r.stderr


def _login(c):
    assert c.post("/api/auth/login", json={"username": "admin", "password": PW}).status_code == 200


def test_shutdown_endpoint_disabled_by_default():
    with TestClient(app) as c:
        _login(c)
        assert c.post("/api/system/shutdown").status_code == 403
        assert c.get("/api/auth/me").json()["can_shutdown"] is False


def test_shutdown_only_for_loopback_and_only_when_enabled(monkeypatch):
    called = []
    monkeypatch.setattr(config, "ALLOW_SHUTDOWN", True)
    monkeypatch.setattr(system, "shutdown_hook", lambda: called.append(1))
    with TestClient(app, client=("203.0.113.5", 4000)) as remote:          # another computer: refused
        _login(remote)
        assert remote.post("/api/system/shutdown").status_code == 403
    assert not called
    with TestClient(app, client=("127.0.0.1", 4000)) as local:             # this computer: accepted
        _login(local)
        assert local.get("/api/auth/me").json()["can_shutdown"] is True
        assert local.post("/api/system/shutdown").json()["ok"] is True
    time.sleep(1.2)
    assert called == [1]


def test_unauthenticated_shutdown_rejected(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_SHUTDOWN", True)
    with TestClient(app, client=("127.0.0.1", 4000)) as anon:
        assert anon.post("/api/system/shutdown").status_code == 401


def test_build_files_are_consistent():
    spec = (ROOT / "CampusGuard.spec").read_text(encoding="utf-8")
    assert "launcher.py" in spec and "app/static" in spec and "torch" in spec and 'name="CampusGuard"' in spec
    build = (ROOT / "build_exe.ps1").read_text(encoding="utf-8")
    assert "--selftest" in build and "SELF-TEST FAILED" in build and "PyInstaller" in build
    assert "pyinstaller==" in (ROOT / "requirements-build.txt").read_text(encoding="utf-8")
    for f in ("LICENSE", "THIRD_PARTY_NOTICES.md", ".env.example", "Dockerfile", "docker-compose.yml", "Caddyfile"):
        assert (ROOT / f).exists(), f
    for pattern in (".env", "*.pt", "*.mp4", "dist/"):
        assert pattern in (ROOT / ".gitignore").read_text(encoding="utf-8"), pattern


def test_github_workflows_and_publish_script_present_and_free_of_secrets():
    exe = (ROOT / ".github" / "workflows" / "build-windows-exe.yml").read_text(encoding="utf-8")
    assert "windows-latest" in exe and "--selftest" in exe and "CampusGuard.spec" in exe and "upload-artifact" in exe
    tests_yml = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "pytest" in tests_yml and "ubuntu-latest" in tests_yml
    pub = (ROOT / "scripts" / "publish_to_github.ps1").read_text(encoding="utf-8")
    assert "gh auth login --web" in pub and "Type YES" in pub
    for text in (exe, tests_yml, pub):
        for bad in ("password=", "ghp_", "github_pat_"):
            assert bad not in text.lower(), bad


def test_docker_files_do_not_expose_app_port_or_secrets():
    comp = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'expose: ["8000"]' in comp and "8000:8000" not in comp and "ADMIN_PASSWORD:?" in comp
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "CAMPUS_REQUIRE_LOGIN=true" in docker and "COOKIE_SECURE=true" in docker and "--workers\", \"1\"" in docker
