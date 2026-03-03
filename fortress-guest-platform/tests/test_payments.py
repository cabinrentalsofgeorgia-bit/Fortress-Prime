"""Tests for Payments API endpoints."""


def test_payments_config(client):
    resp = client.get("/api/payments/config")
    assert resp.status_code == 200
    payload = resp.json()
    assert "publishable_key" in payload
    assert "configured" in payload


def test_payments_create_intent_unknown_reservation(client):
    resp = client.post(
        "/api/payments/create-intent",
        json={"reservation_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert resp.status_code in (404, 422)


def test_payments_reservation_lookup_unknown(client):
    resp = client.get("/api/payments/reservation/00000000-0000-0000-0000-000000000001")
    assert resp.status_code in (404, 422)


def test_payments_webhook_missing_signature(client):
    resp = client.post("/api/payments/webhook", content=b"{}")
    assert resp.status_code == 400
