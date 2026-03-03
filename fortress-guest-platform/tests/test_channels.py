"""Tests for the Channel Manager API."""
import pytest


def test_channel_manager_status(client):
    resp = client.get("/api/channel-manager/status")
    assert resp.status_code == 200


def test_channel_manager_mappings(client):
    resp = client.get("/api/channel-manager/mappings")
    assert resp.status_code == 200


def test_channel_status(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/channels/status/{property_id}")
    assert resp.status_code == 200


def test_channel_performance(client):
    resp = client.get("/api/channels/performance", params={"period": "30d"})
    assert resp.status_code in (200, 422)
