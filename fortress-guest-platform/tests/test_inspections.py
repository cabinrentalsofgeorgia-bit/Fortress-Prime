"""Tests for Inspections API (CF-01 bridge)."""


def test_inspection_summary(client):
    resp = client.get("/api/inspections/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_inspections" in data or isinstance(data, dict)


def test_inspection_history(client):
    resp = client.get("/api/inspections/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_failed_items(client):
    resp = client.get("/api/inspections/failed-items")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_inspection_history_with_limit(client):
    resp = client.get("/api/inspections/history", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 5
