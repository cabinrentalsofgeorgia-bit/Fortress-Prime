"""Tests for the Messages API."""


def test_list_messages(client):
    resp = client.get("/api/messages/")
    assert resp.status_code == 200


def test_message_threads(client):
    resp = client.get("/api/messages/threads")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_message_stats(client):
    resp = client.get("/api/messages/stats")
    assert resp.status_code == 200


def test_unread_messages(client):
    resp = client.get("/api/messages/unread")
    assert resp.status_code == 200
