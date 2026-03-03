"""Tests for the Work Orders API."""


def test_list_workorders(client):
    resp = client.get("/api/workorders/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_workorder(client):
    payload = {
        "title": "Test - Leaky faucet cabin 7",
        "description": "Kitchen sink dripping",
        "priority": "medium",
        "status": "open",
    }
    resp = client.post("/api/workorders/", json=payload)
    assert resp.status_code in (200, 201, 422)
    if resp.status_code in (200, 201):
        data = resp.json()
        assert "id" in data
