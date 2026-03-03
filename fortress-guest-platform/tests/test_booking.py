"""Tests for the Booking API."""
import pytest


def test_booking_search(client):
    resp = client.get("/api/booking/search", params={
        "check_in": "2026-06-01",
        "check_out": "2026-06-05",
        "guests": 2,
    })
    assert resp.status_code == 200


def test_booking_arrivals(client):
    resp = client.get("/api/booking/reservations/arrivals")
    assert resp.status_code == 200


def test_booking_departures(client):
    resp = client.get("/api/booking/reservations/departures")
    assert resp.status_code == 200


def test_booking_occupancy(client):
    resp = client.get("/api/booking/reservations/occupancy", params={"start": "2026-02-01", "end": "2026-02-28"})
    assert resp.status_code in (200, 422)


def test_booking_calendar(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/booking/calendar/{property_id}")
    assert resp.status_code == 200


def test_booking_pricing(client, property_id):
    if property_id is None:
        pytest.skip("No properties in database")
    resp = client.get(f"/api/booking/pricing/{property_id}", params={
        "check_in": "2026-06-01",
        "check_out": "2026-06-05",
    })
    assert resp.status_code in (200, 422)
