"""Tests for the AI Agent API."""


def test_agent_stats(client):
    resp = client.get("/api/agent/stats")
    assert resp.status_code == 200


def test_agent_templates(client):
    resp = client.get("/api/agent/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, (list, dict))
