"""Tests for the Properties API."""
import pytest


def test_list_properties(client):
    resp = client.get("/api/properties/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_get_property_detail(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/properties/{property_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data


def test_get_property_not_found(client):
    resp = client.get("/api/properties/99999999")
    assert resp.status_code in (404, 422)
