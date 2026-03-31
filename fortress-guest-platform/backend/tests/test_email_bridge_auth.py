from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

def _install_stub_module(module_name: str, *class_names: str) -> None:
    module = types.ModuleType(module_name)
    for class_name in class_names:
        setattr(module, class_name, type(class_name, (), {}))
    sys.modules.setdefault(module_name, module)


_install_stub_module(
    "backend.models.financial_primitives",
    "Fee",
    "Tax",
    "PropertyTax",
    "PropertyFee",
)
_install_stub_module("backend.models.media", "PropertyImage")
_install_stub_module("backend.models.property_stay_restriction", "PropertyStayRestriction")
_install_stub_module("backend.models.pricing_override", "PricingOverride")

import run  # noqa: F401
import backend.models  # noqa: F401
import backend.api.email_bridge as email_bridge_api
from backend.core import security_swarm
from backend.core.database import get_db


def _result(value=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _payload() -> dict:
    return {
        "sender_email": "bridge-smoke@example.com",
        "sender_name": "Bridge Smoke",
        "subject": "CABIN_VRS smoke",
        "body": "Testing authenticated email bridge ingress.",
    }


@pytest.mark.asyncio
async def test_email_bridge_requires_swarm_token() -> None:
    app = FastAPI()
    app.include_router(email_bridge_api.router, prefix="/api/email-bridge")
    session = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/email-bridge/ingest", json=_payload())

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_email_bridge_accepts_valid_swarm_token() -> None:
    app = FastAPI()
    app.include_router(email_bridge_api.router, prefix="/api/email-bridge")
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_result(None), _result(None), _result(None)])
    session.get = AsyncMock(
        return_value=SimpleNamespace(id=uuid4(), full_name="Bridge Smoke")
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    class _FakeMessage:
        def __init__(self, **kwargs):
            self.id = uuid4()
            for key, value in kwargs.items():
                setattr(self, key, value)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(security_swarm.settings, "swarm_api_key", "test-swarm-token")
        mp.setattr(email_bridge_api, "Message", _FakeMessage)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/email-bridge/ingest",
                json=_payload(),
                headers={"X-Swarm-Token": "test-swarm-token"},
            )

    assert response.status_code == 200
    assert response.json()["ok"] is True
