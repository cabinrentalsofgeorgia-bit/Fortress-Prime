"""Tests for the Global Search API."""


def test_global_search(client):
    resp = client.get("/api/search/", params={"q": "cabin"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, (list, dict))


def test_search_empty_query(client):
    resp = client.get("/api/search/", params={"q": ""})
    assert resp.status_code in (200, 422)
