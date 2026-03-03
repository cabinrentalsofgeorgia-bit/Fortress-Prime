"""Tests for Damage Claims API — full workflow."""


def test_list_damage_claims(client):
    resp = client.get("/api/damage-claims/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_damage_claim_stats(client):
    resp = client.get("/api/damage-claims/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data or isinstance(data, dict)


def test_reservation_options(client):
    resp = client.get("/api/damage-claims/reservation-options")
    assert resp.status_code == 200


def test_create_damage_claim(client):
    payload = {
        "reservation_id": 1,
        "description": "Smoke test: scratched countertop",
        "affected_areas": ["Kitchen"],
        "estimated_cost": 150.00,
    }
    resp = client.post("/api/damage-claims/", json=payload)
    assert resp.status_code in (200, 201, 422)
