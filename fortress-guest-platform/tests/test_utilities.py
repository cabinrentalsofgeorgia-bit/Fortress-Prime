"""Tests for the Property Utilities & Services API."""
import pytest


def test_service_types(client):
    resp = client.get("/api/utilities/types")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert "internet" in data
    assert "electric" in data
    assert "water" in data
    assert "gas" in data


def test_list_property_utilities(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/utilities/property/{property_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_create_utility(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    payload = {
        "property_id": property_id,
        "service_type": "trash",
        "provider_name": "Test Waste Services",
        "account_holder": "Test Owner",
        "monthly_budget": 45.00,
    }
    resp = client.post("/api/utilities/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["provider_name"] == "Test Waste Services"
    assert data["service_type"] == "trash"
    assert data["monthly_budget"] == 45.00
    assert "id" in data

    # Clean up
    client.delete(f"/api/utilities/{data['id']}")


def test_utility_password_encryption(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    payload = {
        "property_id": property_id,
        "service_type": "security",
        "provider_name": "ADT Security",
        "portal_username": "testuser",
        "portal_password": "MySecretPass!",
    }
    resp = client.post("/api/utilities/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    utility_id = data["id"]
    assert data["has_portal_password"] is True
    assert "portal_password" not in data

    # Reveal password
    resp = client.get(f"/api/utilities/{utility_id}/password")
    assert resp.status_code == 200
    assert resp.json()["password"] == "MySecretPass!"

    # Clean up
    client.delete(f"/api/utilities/{utility_id}")


def test_add_reading(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    # Create utility
    resp = client.post("/api/utilities/", json={
        "property_id": property_id,
        "service_type": "propane",
        "provider_name": "Test Propane Co",
    })
    utility_id = resp.json()["id"]

    # Add reading
    resp = client.post(f"/api/utilities/{utility_id}/readings", json={
        "reading_date": "2026-02-10",
        "cost": 125.50,
        "usage_amount": 50.0,
        "usage_unit": "gal",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["cost"] == 125.50
    assert data["usage_unit"] == "gal"

    # List readings
    resp = client.get(f"/api/utilities/{utility_id}/readings")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Clean up
    client.delete(f"/api/utilities/{utility_id}")


def test_cost_analytics(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/utilities/analytics/{property_id}", params={"period": "ytd"})
    assert resp.status_code == 200
    data = resp.json()
    assert "by_service" in data
    assert "total" in data
    assert "daily_breakdown" in data


def test_portfolio_summary(client):
    resp = client.get("/api/utilities/analytics/portfolio/summary", params={"period": "mtd"})
    assert resp.status_code == 200
    data = resp.json()
    assert "properties" in data
    assert "grand_total" in data
