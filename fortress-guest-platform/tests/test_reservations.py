"""Tests for the Reservations API."""
import pytest


def test_list_reservations(client):
    resp = client.get("/api/reservations/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_arriving_today(client):
    resp = client.get("/api/reservations/arriving/today")
    assert resp.status_code == 200


def test_departing_today(client):
    resp = client.get("/api/reservations/departing/today")
    assert resp.status_code == 200


def test_get_reservation_detail(client, reservation_id):
    if reservation_id is None:
        pytest.skip("No reservations in database")
    resp = client.get(f"/api/reservations/{reservation_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data


def test_get_reservation_full(client, reservation_id):
    if reservation_id is None:
        pytest.skip("No reservations in database")
    resp = client.get(f"/api/reservations/{reservation_id}/full")
    assert resp.status_code == 200
