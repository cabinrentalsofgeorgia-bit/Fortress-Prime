"""Unit-style tests for backend.api.agreements helpers and token paths."""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import agreements as api


class _FakeDB:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.commits = 0

    async def get(self, _model, key):
        return self.mapping.get(str(key))

    async def commit(self):
        self.commits += 1


def _fake_request():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "pytest"})


def test_serialize_template():
    tid = uuid4()
    tpl = SimpleNamespace(
        id=tid,
        name="Standard",
        description="desc",
        agreement_type="rental_agreement",
        content_markdown="Hello {{guest_name}}",
        required_variables=["guest_name"],
        is_active=True,
        requires_signature=True,
        requires_initials=False,
        auto_send=True,
        send_days_before_checkin=7,
        property_ids=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    data = api._serialize_template(tpl)
    assert data["id"] == str(tid)
    assert data["name"] == "Standard"
    assert data["required_variables"] == ["guest_name"]


def test_serialize_agreement():
    aid = uuid4()
    gid = uuid4()
    ag = SimpleNamespace(
        id=aid,
        guest_id=gid,
        reservation_id=None,
        property_id=None,
        template_id=None,
        agreement_type="rental_agreement",
        status="draft",
        sent_at=None,
        sent_via=None,
        agreement_url=None,
        expires_at=None,
        first_viewed_at=None,
        view_count=0,
        signed_at=None,
        signature_type=None,
        signer_name=None,
        signer_email=None,
        signer_ip_address=None,
        consent_recorded=False,
        pdf_url=None,
        reminder_count=0,
        created_at=datetime.utcnow(),
    )
    data = api._serialize_agreement(ag)
    assert data["id"] == str(aid)
    assert data["guest_id"] == str(gid)
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_public_view_invalid_token(monkeypatch):
    monkeypatch.setattr(api, "validate_signing_token", lambda _t: None)
    with pytest.raises(HTTPException) as exc:
        await api.public_view_agreement("bad-token", request=_fake_request(), db=_FakeDB())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_public_sign_invalid_token(monkeypatch):
    monkeypatch.setattr(api, "validate_signing_token", lambda _t: None)
    body = api.SignatureSubmission(
        signer_name="T",
        signer_email="t@example.com",
        signature_type="typed",
        signature_data="T",
        consent_recorded=True,
    )
    with pytest.raises(HTTPException) as exc:
        await api.public_sign_agreement("bad-token", body=body, request=_fake_request(), db=_FakeDB())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_public_sign_requires_consent(monkeypatch):
    agreement_id = uuid4()
    monkeypatch.setattr(api, "validate_signing_token", lambda _t: str(agreement_id))
    agreement = SimpleNamespace(
        id=agreement_id,
        status="viewed",
    )
    db = _FakeDB(mapping={str(agreement_id): agreement})
    body = api.SignatureSubmission(
        signer_name="No Consent",
        signer_email="n@example.com",
        signature_type="typed",
        signature_data="No Consent",
        consent_recorded=False,
    )
    with pytest.raises(HTTPException) as exc:
        await api.public_sign_agreement("ok-token", body=body, request=_fake_request(), db=db)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_template_not_found():
    missing_id = uuid4()
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc:
        await api.get_template(template_id=missing_id, db=db, _user=SimpleNamespace(id="u1"))
    assert exc.value.status_code == 404
