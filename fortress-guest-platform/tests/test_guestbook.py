"""Tests for the Guestbook API."""


def test_list_guestbooks(client):
    resp = client.get("/api/guestbook/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_guestbook_extras(client):
    resp = client.get("/api/guestbook/extras")
    assert resp.status_code == 200
