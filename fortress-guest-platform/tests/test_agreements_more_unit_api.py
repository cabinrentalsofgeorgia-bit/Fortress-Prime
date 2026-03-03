"""Additional unit coverage for backend.api.agreements."""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import agreements as api


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def scalars(self):
        return _FakeScalars(self._rows)

    def scalar(self):
        return self._scalar_value

    def scalar_one_or_none(self):
        return self._scalar_value


class _FakeDB:
    def __init__(self):
        self._objects = {}
        self._results = []
        self._added = []
        self.commits = 0

    def put(self, model, key, value):
        self._objects[(id(model), str(key))] = value

    def queue_result(self, result):
        self._results.append(result)

    def add(self, obj):
        self._added.append(obj)

    async def get(self, model, key):
        return self._objects.get((id(model), str(key)))

    async def execute(self, *_args, **_kwargs):
        if self._results:
            return self._results.pop(0)
        return _FakeResult()

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None

    async def flush(self):
        return None


def _request():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "pytest"})


@pytest.mark.asyncio
async def test_list_templates_and_dashboard():
    db = _FakeDB()
    tpl = SimpleNamespace(
        id=uuid4(),
        name="T",
        description="d",
        agreement_type="rental_agreement",
        content_markdown="{{x}}",
        required_variables=["x"],
        is_active=True,
        requires_signature=True,
        requires_initials=False,
        auto_send=True,
        send_days_before_checkin=7,
        property_ids=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.queue_result(_FakeResult(rows=[tpl]))
    templates = await api.list_templates(db=db, _user=SimpleNamespace(id="u"))
    assert len(templates) == 1
    assert templates[0]["name"] == "T"

    db.queue_result(_FakeResult(scalar_value=5))
    for _ in range(6):
        db.queue_result(_FakeResult(scalar_value=1))
    dash = await api.agreement_dashboard(db=db, _user=SimpleNamespace(id="u"))
    assert dash["total"] == 5
    assert dash["by_status"]["signed"] == 1


@pytest.mark.asyncio
async def test_template_create_update_delete():
    db = _FakeDB()
    body = api.TemplateCreate(name="Standard", content_markdown="Hello {{guest_name}}")
    created = await api.create_template(body=body, db=db, user=SimpleNamespace(id="admin"))
    assert created["name"] == "Standard"
    assert db.commits >= 1

    template_id = uuid4()
    existing = SimpleNamespace(
        id=template_id,
        name="Old",
        description=None,
        agreement_type="rental_agreement",
        content_markdown="old",
        required_variables=[],
        requires_signature=True,
        requires_initials=False,
        auto_send=True,
        send_days_before_checkin=7,
        property_ids=None,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=None,
    )
    db.put(api.AgreementTemplate, template_id, existing)
    updated = await api.update_template(
        template_id=template_id,
        body=api.TemplateUpdate(content_markdown="Hi {{guest_name}}"),
        db=db,
        user=SimpleNamespace(id="admin"),
    )
    assert "guest_name" in updated["required_variables"]

    deleted = await api.delete_template(template_id=template_id, db=db, user=SimpleNamespace(id="admin"))
    assert deleted["status"] == "deactivated"


@pytest.mark.asyncio
async def test_send_and_remind_agreement(monkeypatch):
    db = _FakeDB()
    agreement_id = uuid4()
    guest_id = uuid4()
    property_id = uuid4()
    agreement = SimpleNamespace(
        id=agreement_id,
        guest_id=guest_id,
        property_id=property_id,
        status="draft",
        agreement_url=None,
        expires_at=datetime.utcnow(),
        sent_at=None,
        sent_via=None,
        reminder_count=0,
    )
    guest = SimpleNamespace(id=guest_id, first_name="Taylor", email="t@example.com")
    prop = SimpleNamespace(id=property_id, name="Cabin One")
    db.put(api.RentalAgreement, agreement_id, agreement)
    db.put(api.Guest, guest_id, guest)
    db.put(api.Property, property_id, prop)

    monkeypatch.setattr(api, "send_email", lambda **_kwargs: True)
    monkeypatch.setattr(api, "generate_signing_token", lambda _aid, _exp: "tok")

    sent = await api.send_agreement(agreement_id=agreement_id, db=db, user=SimpleNamespace(id="mgr"))
    assert sent["status"] == "sent"
    assert sent["email_sent"] is True

    agreement.status = "sent"
    reminded = await api.remind_agreement(agreement_id=agreement_id, db=db, user=SimpleNamespace(id="mgr"))
    assert reminded["status"] == "reminded"
    assert reminded["reminder_count"] == 1


@pytest.mark.asyncio
async def test_public_view_and_sign_success(monkeypatch):
    db = _FakeDB()
    agreement_id = uuid4()
    guest_id = uuid4()
    property_id = uuid4()
    template_id = uuid4()
    reservation_id = uuid4()
    agreement = SimpleNamespace(
        id=agreement_id,
        template_id=template_id,
        reservation_id=reservation_id,
        guest_id=guest_id,
        property_id=property_id,
        agreement_type="rental_agreement",
        rendered_content="Hello",
        status="sent",
        first_viewed_at=None,
        view_count=0,
        expires_at=datetime.utcnow(),
        signed_at=None,
        signature_type=None,
        signature_data=None,
        signer_name=None,
        signer_email=None,
        initials_data=None,
        initials_pages=None,
        signer_ip_address=None,
        signer_user_agent=None,
        consent_recorded=False,
        pdf_url=None,
        pdf_generated_at=None,
    )
    db.put(api.RentalAgreement, agreement_id, agreement)
    db.put(api.Guest, guest_id, SimpleNamespace(first_name="G", last_name="H", email="g@example.com"))
    db.put(api.Property, property_id, SimpleNamespace(name="Cabin"))
    db.put(api.Reservation, reservation_id, SimpleNamespace(confirmation_code="ABC123"))
    db.put(api.AgreementTemplate, template_id, SimpleNamespace(requires_signature=True, requires_initials=False))

    monkeypatch.setattr(api, "validate_signing_token", lambda _t: str(agreement_id))
    monkeypatch.setattr(api, "generate_agreement_pdf", lambda **_kwargs: "/tmp/a.pdf")
    monkeypatch.setattr(api, "send_email", lambda **_kwargs: True)

    viewed = await api.public_view_agreement("ok", request=_request(), db=db)
    assert viewed["status"] == "viewed"
    assert agreement.view_count == 1

    body = api.SignatureSubmission(
        signer_name="Signer",
        signer_email="signer@example.com",
        signature_type="typed",
        signature_data="Signer",
        consent_recorded=True,
    )
    signed = await api.public_sign_agreement("ok", body=body, request=_request(), db=db)
    assert signed["status"] == "signed"
    assert signed["pdf_generated"] is True


@pytest.mark.asyncio
async def test_create_agreement_missing_dependencies():
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc:
        await api.create_agreement(
            body=api.AgreementCreate(template_id=uuid4(), reservation_id=uuid4()),
            db=db,
            user=SimpleNamespace(id="mgr"),
        )
    assert exc.value.status_code == 404
