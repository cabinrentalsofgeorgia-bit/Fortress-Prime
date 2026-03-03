"""Tests for the Owner Portal API."""


def test_owner_dashboard(client):
    resp = client.get("/api/owner/dashboard/1")
    assert resp.status_code in (200, 404)


def test_owner_statements(client):
    resp = client.get("/api/owner/statements/1")
    assert resp.status_code in (200, 404)


def test_owner_documents(client):
    resp = client.get("/api/owner/documents/1")
    assert resp.status_code in (200, 404)


def test_owner_reservations(client):
    resp = client.get("/api/owner/reservations/1")
    assert resp.status_code in (200, 404)


def test_owner_work_orders(client):
    resp = client.get("/api/owner/work-orders/1")
    assert resp.status_code in (200, 404)
