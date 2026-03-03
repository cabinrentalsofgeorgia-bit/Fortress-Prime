"""Tests for the Guests API."""
import pytest


def test_list_guests(client):
    resp = client.get("/api/guests/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_arriving_today(client):
    resp = client.get("/api/guests/arriving/today")
    assert resp.status_code == 200


def test_departing_today(client):
    resp = client.get("/api/guests/departing/today")
    assert resp.status_code == 200


def test_staying_now(client):
    resp = client.get("/api/guests/staying/now")
    assert resp.status_code == 200


def test_guest_analytics(client):
    resp = client.get("/api/guests/analytics")
    assert resp.status_code == 200


def test_get_guest_detail(client, guest_id):
    if guest_id is None:
        pytest.skip("No guests in database")
    resp = client.get(f"/api/guests/{guest_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data


def test_get_guest_360(client, guest_id):
    if guest_id is None:
        pytest.skip("No guests in database")
    resp = client.get(f"/api/guests/{guest_id}/360")
    assert resp.status_code == 200


def test_get_guest_activity(client, guest_id):
    if guest_id is None:
        pytest.skip("No guests in database")
    resp = client.get(f"/api/guests/{guest_id}/activity")
    assert resp.status_code == 200


def test_nps_survey(client):
    resp = client.get("/api/guests/surveys/nps")
    assert resp.status_code == 200


def test_reviews_analytics(client):
    resp = client.get("/api/guests/reviews/analytics")
    assert resp.status_code == 200
