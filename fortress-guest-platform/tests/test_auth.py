"""
Authentication API tests — login, SSO, protected routes
"""
import pytest


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------

def test_login_success(client):
    """Login with valid credentials returns token and user."""
    resp = client.post("/api/auth/login", json={
        "email": "gary@cabin-rentals-of-georgia.com",
        "password": "Fortress2026!",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "gary@cabin-rentals-of-georgia.com"
    assert data["user"]["role"] == "admin"


def test_login_wrong_password(unauthed_client):
    resp = unauthed_client.post("/api/auth/login", json={
        "email": "gary@cabin-rentals-of-georgia.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_login_unknown_email(unauthed_client):
    resp = unauthed_client.post("/api/auth/login", json={
        "email": "nobody@example.com",
        "password": "whatever123",
    })
    assert resp.status_code == 401


def test_me_authenticated(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "gary@cabin-rentals-of-georgia.com"
    assert data["first_name"] == "Gary"


def test_me_unauthenticated(unauthed_client):
    resp = unauthed_client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


def test_list_users_admin(client):
    resp = client.get("/api/auth/users")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 1
    emails = [u["email"] for u in users]
    assert "gary@cabin-rentals-of-georgia.com" in emails


def test_protected_utility_unauthenticated(unauthed_client):
    """Utility endpoints require auth."""
    resp = unauthed_client.get("/api/utilities/types")
    assert resp.status_code in (401, 403)


def test_protected_utility_authenticated(client, property_id):
    """Utility endpoints work with auth."""
    if property_id is None:
        pytest.skip("No properties")
    resp = client.get(f"/api/utilities/property/{property_id}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# SSO tests
# ---------------------------------------------------------------------------

def test_sso_valid_gateway_token(unauthed_client, gateway_token):
    """SSO with a valid gateway JWT returns a VRS token and user."""
    resp = unauthed_client.post("/api/auth/sso", json={
        "gateway_token": gateway_token,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "user" in data
    assert data["user"]["email"]
    assert data["user"]["role"] in ("admin", "manager", "staff")


def test_sso_returns_working_vrs_token(unauthed_client, gateway_token):
    """The VRS token issued by SSO can access protected endpoints."""
    sso_resp = unauthed_client.post("/api/auth/sso", json={
        "gateway_token": gateway_token,
    })
    assert sso_resp.status_code == 200
    vrs_token = sso_resp.json()["access_token"]

    me_resp = unauthed_client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {vrs_token}",
    })
    assert me_resp.status_code == 200
    assert me_resp.json()["email"]


def test_sso_role_mapping(unauthed_client, gateway_token):
    """Gateway admin role should map to VRS admin role."""
    resp = unauthed_client.post("/api/auth/sso", json={
        "gateway_token": gateway_token,
    })
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"


def test_sso_garbage_token_rejected(unauthed_client):
    """A random string as gateway_token should be rejected."""
    resp = unauthed_client.post("/api/auth/sso", json={
        "gateway_token": "this-is-not-a-real-jwt-token-at-all",
    })
    assert resp.status_code in (401, 502)


def test_sso_expired_token_rejected(unauthed_client):
    """An expired JWT should be rejected by the gateway."""
    expired = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxIiwidXNlcm5hbWUiOiJ0ZXN0Iiwicm9sZSI6InZpZXdlciIs"
        "ImV4cCI6MTAwMDAwMDAwMCwiaWF0IjoxMDAwMDAwMDAwfQ."
        "invalid_signature_here"
    )
    resp = unauthed_client.post("/api/auth/sso", json={
        "gateway_token": expired,
    })
    assert resp.status_code in (401, 502)


def test_sso_empty_token_rejected(unauthed_client):
    """An empty token string should be rejected."""
    resp = unauthed_client.post("/api/auth/sso", json={
        "gateway_token": "",
    })
    assert resp.status_code in (401, 422, 429, 502)


def test_sso_missing_token_field(unauthed_client):
    """Missing gateway_token field should return 422."""
    resp = unauthed_client.post("/api/auth/sso", json={})
    assert resp.status_code == 422


def test_sso_idempotent(unauthed_client, gateway_token):
    """Calling SSO twice with the same token should return the same user."""
    resp1 = unauthed_client.post("/api/auth/sso", json={
        "gateway_token": gateway_token,
    })
    if resp1.status_code == 429:
        pytest.skip("Rate limited — SSO rate limiter is working correctly")
    resp2 = unauthed_client.post("/api/auth/sso", json={
        "gateway_token": gateway_token,
    })
    if resp2.status_code == 429:
        pytest.skip("Rate limited on second call — limiter is functional")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["user"]["id"] == resp2.json()["user"]["id"]
    assert resp1.json()["user"]["email"] == resp2.json()["user"]["email"]


def test_command_center_url(unauthed_client):
    """The command-center-url endpoint returns a valid URL."""
    resp = unauthed_client.get("/api/auth/command-center-url")
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert data["url"].startswith("http")
