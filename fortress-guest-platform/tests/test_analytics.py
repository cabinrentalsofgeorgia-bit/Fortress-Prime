"""Tests for the Analytics API."""


def test_dashboard_stats(client):
    resp = client.get("/api/analytics/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
