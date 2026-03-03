"""Tests for the Review Queue API."""


def test_review_queue(client):
    resp = client.get("/api/review/queue")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, (list, dict))


def test_review_queue_stats(client):
    resp = client.get("/api/review/queue/stats")
    assert resp.status_code == 200


def test_review_queue_detail_unknown(client):
    resp = client.get("/api/review/queue/99999999")
    assert resp.status_code in (404, 422)


def test_review_queue_approve_unknown(client):
    resp = client.post("/api/review/queue/99999999/approve", json={})
    assert resp.status_code in (404, 422)


def test_review_queue_edit_unknown(client):
    resp = client.post("/api/review/queue/99999999/edit", json={"draft": "updated"})
    assert resp.status_code in (404, 422)


def test_review_queue_reject_unknown(client):
    resp = client.post("/api/review/queue/99999999/reject", json={})
    assert resp.status_code in (404, 422)
