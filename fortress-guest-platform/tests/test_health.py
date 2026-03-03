"""Tests for health check endpoints."""


def test_basic_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "Fortress Guest Platform"
    assert "version" in data


def test_deep_health(client):
    resp = client.get("/health/deep")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded")
    assert "checks" in data
    assert "database" in data["checks"]
    assert "redis" in data["checks"]
    assert "timestamp" in data


def test_readiness(client):
    resp = client.get("/health/ready")
    data = resp.json()
    assert data["status"] in ("healthy", "degraded")


def test_response_has_request_id(client):
    resp = client.get("/health")
    assert "x-request-id" in resp.headers
    assert "x-duration-ms" in resp.headers
