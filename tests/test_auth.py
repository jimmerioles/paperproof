from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from paperproof.api.factory import create_app
from paperproof.auth import (
    LoginLimiter,
    SessionManager,
    get_user_by_username,
    set_admin_password,
    verify_password,
)
from paperproof.config import Settings
from paperproof.db import session

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
PASSWORD = "correct horse battery staple"


def csrf_from(html: str) -> str:
    match = CSRF_RE.search(html)
    assert match is not None
    return match.group(1)


@pytest.fixture()
def auth_settings(tmp_path: Path) -> Settings:
    resolved = Settings(
        data_dir=tmp_path / "auth",
        session_secret="test-session-secret",
        login_max_attempts=2,
        login_window_seconds=60,
        login_lockout_seconds=60,
    )
    resolved.ensure_dirs()
    return resolved


@pytest.fixture()
def auth_client(auth_settings: Settings):
    app = create_app(auth_settings)
    with TestClient(app) as client:
        yield client


def create_admin(settings: Settings, username: str = "admin", password: str = PASSWORD) -> None:
    with session(settings) as conn:
        set_admin_password(conn, username, password)


def login(client: TestClient, username: str = "admin", password: str = PASSWORD):
    page = client.get("/login")
    token = csrf_from(page.text)
    return client.post(
        "/login",
        data={
            "csrf_token": token,
            "username": username,
            "password": password,
            "next": "/",
        },
        follow_redirects=False,
    )


def test_unauthenticated_request_redirects(auth_client: TestClient) -> None:
    response = auth_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_login_page_without_admin_explains_setup(auth_client: TestClient) -> None:
    response = auth_client.get("/login")
    assert response.status_code == 200
    assert "No admin account yet." in response.text
    assert "paperproof auth set-password" in response.text
    assert 'name="csrf_token"' in response.text


def test_login_and_logout(auth_client: TestClient, auth_settings: Settings) -> None:
    create_admin(auth_settings)
    response = login(auth_client)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie

    dashboard = auth_client.get("/")
    assert dashboard.status_code == 200
    assert "admin" in dashboard.text
    token = csrf_from(dashboard.text)

    logout = auth_client.post(
        "/logout",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"

    again = auth_client.get("/", follow_redirects=False)
    assert again.status_code == 303


def test_bad_password_is_generic(auth_client: TestClient, auth_settings: Settings) -> None:
    create_admin(auth_settings)
    response = login(auth_client, password="this is not the password")
    assert response.status_code == 401
    assert "Invalid username or password." in response.text
    assert "Traceback" not in response.text


def test_csrf_is_required_for_state_changes(
    auth_client: TestClient, auth_settings: Settings
) -> None:
    create_admin(auth_settings)
    assert login(auth_client).status_code == 303
    response = auth_client.post("/logout", follow_redirects=False)
    assert response.status_code == 403
    assert auth_client.get("/", follow_redirects=False).status_code == 200


def test_login_is_rate_limited(auth_client: TestClient, auth_settings: Settings) -> None:
    create_admin(auth_settings)
    first = login(auth_client, password="wrong password one")
    assert first.status_code == 401
    second = login(auth_client, password="wrong password two")
    assert second.status_code == 429
    third = login(auth_client)
    assert third.status_code == 429
    assert "Too many attempts" in third.text


def test_auth_cannot_be_disabled_in_prod(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            data_dir=tmp_path / "prod",
            auth_disabled=True,
            env="prod",
            session_secret="test",
        )


def test_secure_cookie_in_prod(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "prod",
        env="prod",
        session_secret="test-session-secret",
    )
    settings.ensure_dirs()
    create_admin(settings)
    app = create_app(settings)
    with TestClient(app, base_url="https://testserver") as client:
        response = login(client)
    assert response.status_code == 303
    assert "Secure" in response.headers.get("set-cookie", "")


def test_password_hash_is_argon2(auth_settings: Settings) -> None:
    create_admin(auth_settings)
    with session(auth_settings) as conn:
        row = get_user_by_username(conn, "admin")
    assert row is not None
    assert str(row["password_hash"]).startswith("$argon2id$")
    valid, needs_rehash = verify_password(str(row["password_hash"]), PASSWORD)
    assert valid is True
    assert needs_rehash is False


def test_login_limiter_uses_a_time_window() -> None:
    limiter = LoginLimiter(max_attempts=2, window_seconds=10, lockout_seconds=30)
    assert limiter.record_failure("key", now=100.0) == 0
    assert limiter.record_failure("key", now=101.0) == 30
    assert limiter.locked_for("key", now=102.0) == 29
    assert limiter.locked_for("key", now=131.0) == 0


def test_session_tokens_are_signed_and_expire() -> None:
    manager = SessionManager("secret", 60)
    session_data = manager.new(uid="usr_test")
    value = manager.dumps(session_data)
    loaded = manager.loads(value)
    assert loaded is not None
    assert loaded.uid == "usr_test"
    assert loaded.csrf == session_data.csrf
    assert manager.loads(value + "tampered") is None


def test_secret_file_is_private(tmp_path: Path) -> None:
    from paperproof.auth import load_session_secret

    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    secret = load_session_secret(settings)
    path = settings.data_dir / "session-secret"
    assert secret
    assert path.exists()
    assert (path.stat().st_mode & 0o077) == 0
    assert load_session_secret(settings) == secret


def test_admin_password_can_be_updated(auth_settings: Settings) -> None:
    create_admin(auth_settings, password=PASSWORD)
    with session(auth_settings) as conn:
        action = set_admin_password(conn, "admin", "a different long password")
    assert action == "updated"
    with session(auth_settings) as conn:
        row = get_user_by_username(conn, "admin")
    assert row is not None
    valid, _ = verify_password(str(row["password_hash"]), "a different long password")
    assert valid is True


def test_upload_requires_and_accepts_csrf(
    auth_client: TestClient,
    auth_settings: Settings,
    sample_paths: list[Path],
) -> None:
    create_admin(auth_settings)
    assert login(auth_client).status_code == 303
    token = csrf_from(auth_client.get("/").text)
    path = sample_paths[1]
    with path.open("rb") as handle:
        response = auth_client.post(
            "/documents",
            data={"csrf_token": token},
            files={"files": (path.name, handle, "application/pdf")},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "Apartment Lease" in auth_client.get("/").text
