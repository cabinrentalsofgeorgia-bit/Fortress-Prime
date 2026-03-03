"""Tests for the Direct Booking API."""


def test_direct_booking_config(client):
    resp = client.get("/api/direct-booking/config")
    assert resp.status_code == 200


def test_direct_booking_availability(client):
    resp = client.get("/api/direct-booking/availability", params={
        "check_in": "2026-07-01",
        "check_out": "2026-07-04",
    })
    assert resp.status_code == 200
