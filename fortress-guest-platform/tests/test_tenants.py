"""Tests for the Tenants API."""


def test_list_tenants(client):
    resp = client.get("/api/tenants/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
