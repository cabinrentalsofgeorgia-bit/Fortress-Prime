import pytest

from backend.integrations.streamline_vrs import (
    StreamlineVRS,
    StreamlineAuthError,
    StreamlineMethodNotAllowed,
    StreamlineRateLimitError,
    StreamlineVRSError,
)


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.is_closed = False

    async def post(self, url, json=None):
        self.calls.append((url, json))
        if not self._responses:
            return _FakeResp(status_code=500, payload={"status": {"code": "E9999", "description": "no response"}})
        return self._responses.pop(0)

    async def aclose(self):
        self.is_closed = True


@pytest.mark.asyncio
async def test_health_check_not_configured(monkeypatch):
    client = StreamlineVRS()
    client.token_key = ""
    client.token_secret = ""
    result = await client.health_check()
    assert result["status"] == "not_configured"


@pytest.mark.asyncio
async def test_call_rate_limited(monkeypatch):
    s = StreamlineVRS()
    fake = _FakeClient([_FakeResp(status_code=429)])
    async def _get_client():
        return fake
    monkeypatch.setattr(s, "_get_client", _get_client)

    with pytest.raises((StreamlineRateLimitError, StreamlineVRSError)):
        await s._call("GetPropertyList")


@pytest.mark.asyncio
async def test_call_http_error(monkeypatch):
    s = StreamlineVRS()
    fake = _FakeClient([_FakeResp(status_code=500, text="boom")])
    async def _get_client():
        return fake
    monkeypatch.setattr(s, "_get_client", _get_client)

    with pytest.raises(StreamlineVRSError):
        await s._call("GetPropertyList")


@pytest.mark.asyncio
async def test_call_method_not_allowed(monkeypatch):
    s = StreamlineVRS()
    fake = _FakeClient(
        [
            _FakeResp(
                status_code=200,
                payload={"status": {"code": "E0014", "description": "method forbidden"}},
            )
        ]
    )
    async def _get_client():
        return fake
    monkeypatch.setattr(s, "_get_client", _get_client)

    with pytest.raises(StreamlineMethodNotAllowed):
        await s._call("GetSignedDocuments")


@pytest.mark.asyncio
async def test_call_token_renewal_failure(monkeypatch):
    s = StreamlineVRS()
    fake = _FakeClient(
        [
            _FakeResp(status_code=200, payload={"status": {"code": "E0015", "description": "expired"}}),
            _FakeResp(status_code=200, payload={"status": {"code": "E0015", "description": "expired again"}}),
        ]
    )
    async def _get_client():
        return fake
    monkeypatch.setattr(s, "_get_client", _get_client)

    async def _renew_fail():
        raise StreamlineAuthError("renew fail")

    monkeypatch.setattr(s, "_renew_token", _renew_fail)

    with pytest.raises(StreamlineAuthError):
        await s._call("GetPropertyList")


@pytest.mark.asyncio
async def test_call_success_returns_data(monkeypatch):
    s = StreamlineVRS()
    fake = _FakeClient([_FakeResp(status_code=200, payload={"data": {"property": [{"id": 1}]}})])
    async def _get_client():
        return fake
    monkeypatch.setattr(s, "_get_client", _get_client)

    data = await s._call("GetPropertyList")
    assert "property" in data
    assert data["property"][0]["id"] == 1


@pytest.mark.asyncio
async def test_health_check_connected(monkeypatch):
    s = StreamlineVRS()
    s.token_key = "key"
    s.token_secret = "secret"

    async def _fake_call(method, extra_params=None):
        return {"property": [{"id": 1}, {"id": 2}]}

    monkeypatch.setattr(s, "_call", _fake_call)
    result = await s.health_check()
    assert result["status"] == "connected"
    assert result["properties_found"] == 2

