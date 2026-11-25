"""Post-deployment smoke test.

Run against a running compose stack:

    SMOKE_BASE_URL=https://localhost:8443 \
    SMOKE_PASSWORD='...' \
    uv run python scripts/smoke.py
"""

from __future__ import annotations

import os
import re
import sys
import time
import warnings

import httpx

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def fail(message: str) -> None:
    print(f"smoke failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    warnings.filterwarnings("ignore")
    base_url = os.environ.get("SMOKE_BASE_URL", "https://localhost:8443")
    username = os.environ.get("SMOKE_USERNAME", "admin")
    password = os.environ.get("SMOKE_PASSWORD")
    if not password:
        fail("SMOKE_PASSWORD is not set")

    client = httpx.Client(
        base_url=base_url,
        verify=False,  # noqa: S501 - local Caddy uses an internal CA
        follow_redirects=False,
        timeout=30.0,
    )
    try:
        ready = False
        for _ in range(30):
            try:
                health = client.get("/healthz")
                if health.status_code == 200 and health.json().get("status") == "ok":
                    ready = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        if not ready:
            fail("health check did not become ready")

        login_page = client.get("/login")
        if login_page.status_code != 200:
            fail(f"login page returned {login_page.status_code}")
        match = CSRF_RE.search(login_page.text)
        if not match:
            fail("login page has no CSRF token")

        login = client.post(
            "/login",
            data={
                "csrf_token": match.group(1),
                "username": username,
                "password": password,
                "next": "/",
            },
        )
        if login.status_code != 303:
            fail(f"login returned {login.status_code}: {login.text[:200]}")

        dashboard = client.get("/")
        if dashboard.status_code != 200:
            fail(f"dashboard returned {dashboard.status_code}")
        if "Terms with receipts." not in dashboard.text:
            fail("dashboard did not render the product heading")
        if "Studio Lease" not in dashboard.text:
            fail("dashboard did not show the seeded document")
        if not dashboard.headers.get("x-request-id"):
            fail("dashboard response has no X-Request-ID")

        print(f"smoke passed against {base_url}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
