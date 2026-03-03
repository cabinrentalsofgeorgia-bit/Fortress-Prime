"""
Shared fixtures for the Fortress Guest Platform test suite.
Uses the real database with the running backend for integration tests.
"""
import os
import pytest
import httpx

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8100")
TEST_TIMEOUT = 30.0


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def auth_token():
    """Authenticate as admin and return JWT token."""
    with httpx.Client(base_url=BASE_URL, timeout=TEST_TIMEOUT) as c:
        resp = c.post("/api/auth/login", json={
            "email": "gary@cabin-rentals-of-georgia.com",
            "password": "Fortress2026!",
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        return resp.json()["access_token"]


@pytest.fixture(scope="session")
def client(auth_token):
    """Synchronous httpx client with auth headers pre-set."""
    with httpx.Client(
        base_url=BASE_URL,
        timeout=TEST_TIMEOUT,
        headers={"Authorization": f"Bearer {auth_token}"},
    ) as c:
        yield c


@pytest.fixture(scope="session")
def unauthed_client():
    """Client without auth for testing 401 responses."""
    with httpx.Client(base_url=BASE_URL, timeout=TEST_TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def gateway_token():
    """Get a valid gateway JWT for SSO testing."""
    gateway_url = os.getenv("GATEWAY_URL", "http://localhost:8000")
    with httpx.Client(base_url=gateway_url, timeout=TEST_TIMEOUT) as c:
        resp = c.post("/v1/auth/login", json={
            "username": "garymknight",
            "password": "Fortress2026!",
        })
        if resp.status_code != 200:
            pytest.skip("Gateway unavailable or garymknight password unknown")
        return resp.json()["access_token"]


@pytest.fixture(scope="session")
def property_id(client):
    """Get the first property ID from the live database."""
    resp = client.get("/api/properties/")
    if resp.status_code == 200:
        props = resp.json()
        if props:
            return props[0]["id"]
    return None


@pytest.fixture(scope="session")
def reservation_id(client):
    """Get the first reservation ID."""
    resp = client.get("/api/reservations/")
    if resp.status_code == 200:
        res = resp.json()
        if res:
            return res[0]["id"]
    return None


@pytest.fixture(scope="session")
def guest_id(client):
    """Get the first guest ID."""
    resp = client.get("/api/guests/", params={"limit": 1})
    if resp.status_code == 200:
        guests = resp.json()
        if guests:
            return guests[0]["id"]
    return None
