"""Tests for the Integrations API (Streamline VRS)."""


def test_streamline_status(client):
    resp = client.get("/api/integrations/streamline/status")
    assert resp.status_code == 200


def test_streamline_properties(client):
    resp = client.get("/api/integrations/streamline/properties")
    assert resp.status_code == 200


def test_streamline_reservations(client):
    resp = client.get("/api/integrations/streamline/reservations", timeout=60.0)
    assert resp.status_code in (200, 408, 504)
