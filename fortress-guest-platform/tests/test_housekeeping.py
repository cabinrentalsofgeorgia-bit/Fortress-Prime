"""Tests for the Housekeeping API."""
import pytest


def test_housekeeping_today(client):
    resp = client.get("/api/housekeeping/today")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_housekeeping_week(client):
    resp = client.get("/api/housekeeping/week")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, (list, dict))


def test_auto_schedule(client):
    resp = client.post("/api/housekeeping/auto-schedule")
    assert resp.status_code in (200, 201, 422)


def test_cleaning_status(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/housekeeping/status/{property_id}")
    assert resp.status_code == 200


def test_linen_requirements(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/housekeeping/linen/{property_id}")
    assert resp.status_code == 200
