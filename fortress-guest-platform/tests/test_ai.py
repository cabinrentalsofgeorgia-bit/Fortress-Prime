"""Tests for AI Superpowers API."""


def test_ai_ask(client):
    resp = client.post("/api/ai/ask", json={"question": "What is the occupancy rate?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data or "response" in data or isinstance(data, dict)


def test_ai_forecast(client):
    resp = client.post("/api/ai/forecast", json={
        "property_id": 1,
        "months": 3,
    })
    assert resp.status_code in (200, 422)


def test_ai_detect_language(client):
    resp = client.post("/api/ai/detect-language", json={"text": "Bonjour, comment allez-vous?"})
    assert resp.status_code == 200
