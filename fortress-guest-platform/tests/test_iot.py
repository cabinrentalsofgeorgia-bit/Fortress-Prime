"""Tests for the IoT Devices API."""
import pytest


def test_iot_devices(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/iot/devices/{property_id}")
    assert resp.status_code == 200
