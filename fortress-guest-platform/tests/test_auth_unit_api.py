"""Unit tests for backend.api.auth with strict mock isolation."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from backend.api import auth as api


class _FakeScalars:
    """Minimal scalar adapter for SQLAlchemy-style results."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeResult:
    """Fake SQL execute result supporting scalar/scalars access patterns."""

    def __init__(self, scalar_value=None, rows=None):
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar_value

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeDB:
    """Async DB double that returns queued execute results deterministically."""

    def __init__(self):
        self._results = []
        self.commits = 0
        self.refreshed = 0
        self.added = []

    def queue_result(self, result):
        self._results.append(result)

    async def execute(self, *_args, **_kwargs):
        if not self._results:
            return _FakeResult()
        return self._results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        self.refreshed += 1


def _staff_user(**overrides):
    """Create a fake staff user object for auth flow tests."""
    base = {
        "id": uuid4(),
        "email": "user@example.com",
        "first_name": "Test",
        "last_name": "User",
        "role": "staff",
        "is_active": True,
        "last_login_at": None,
        "notification_phone": None,
        "notification_email": None,
        "password_hash": "hash",
        "updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_login_success_uses_mocked_password_and_token(monkeypatch):
    """Validates login success path with fully mocked password verification and token issuance."""
    db = _FakeDB()
    user = _staff_user(email="alpha@example.com", role="admin")
    db.queue_result(_FakeResult(scalar_value=user))

    monkeypatch.setattr(api, "verify_password", lambda plain, hashed: plain == "ok" and hashed == "hash")
    monkeypatch.setattr(api, "create_access_token", lambda **claims: f"token-for-{claims['email']}")

    out = await api.login(api.LoginRequest(email="alpha@example.com", password="ok"), db=db)
    assert out.access_token == "token-for-alpha@example.com"
    assert out.user["email"] == "alpha@example.com"
    assert isinstance(user.last_login_at, datetime)


@pytest.mark.asyncio
async def test_login_rejects_bad_password(monkeypatch):
    """Validates login denies invalid credentials without real hash or identity checks."""
    db = _FakeDB()
    db.queue_result(_FakeResult(scalar_value=_staff_user()))
    monkeypatch.setattr(api, "verify_password", lambda *_: False)
    with pytest.raises(HTTPException) as exc:
        await api.login(api.LoginRequest(email="bad@example.com", password="wrong"), db=db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_inactive_user(monkeypatch):
    """Validates login blocks deactivated users even when password check passes."""
    db = _FakeDB()
    db.queue_result(_FakeResult(scalar_value=_staff_user(is_active=False)))
    monkeypatch.setattr(api, "verify_password", lambda *_: True)
    with pytest.raises(HTTPException) as exc:
        await api.login(api.LoginRequest(email="disabled@example.com", password="ok"), db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_register_conflict_and_role_validation():
    """Validates registration conflict and invalid role handling with mocked DB lookups."""
    db_conflict = _FakeDB()
    db_conflict.queue_result(_FakeResult(scalar_value=_staff_user()))
    with pytest.raises(HTTPException) as conflict_exc:
        await api.register(
            api.RegisterRequest(
                email="dup@example.com",
                password="Password123",
                first_name="Dup",
                last_name="User",
                role="staff",
            ),
            db=db_conflict,
            admin=_staff_user(role="admin"),
        )
    assert conflict_exc.value.status_code == 409

    db_role = _FakeDB()
    db_role.queue_result(_FakeResult(scalar_value=None))
    with pytest.raises(HTTPException) as role_exc:
        await api.register(
            api.RegisterRequest(
                email="ok@example.com",
                password="Password123",
                first_name="Ok",
                last_name="User",
                role="superuser",
            ),
            db=db_role,
            admin=_staff_user(role="admin"),
        )
    assert role_exc.value.status_code == 422


@pytest.mark.asyncio
async def test_register_success_hashes_password(monkeypatch):
    """Validates register path uses mocked hashing and persists via mocked DB calls only."""
    db = _FakeDB()
    db.queue_result(_FakeResult(scalar_value=None))
    monkeypatch.setattr(api, "hash_password", lambda pw: f"hashed::{pw}")

    out = await api.register(
        api.RegisterRequest(
            email="new@example.com",
            password="Password123",
            first_name="New",
            last_name="User",
            role="manager",
        ),
        db=db,
        admin=_staff_user(role="admin"),
    )
    assert out.email == "new@example.com"
    assert db.commits == 1
    assert db.refreshed == 1
    assert len(db.added) == 1
    assert db.added[0].password_hash.startswith("hashed::")


@pytest.mark.asyncio
async def test_update_profile_and_change_password(monkeypatch):
    """Validates profile update and password change flows with no real credential checks."""
    db = _FakeDB()
    user = _staff_user()
    profile = await api.update_profile(
        api.UpdateProfileRequest(first_name="Renamed", notification_email="renamed@example.com"),
        db=db,
        user=user,
    )
    assert profile.first_name == "Renamed"
    assert profile.notification_email == "renamed@example.com"

    monkeypatch.setattr(api, "verify_password", lambda *_: False)
    with pytest.raises(HTTPException) as bad_current:
        await api.change_password(
            api.ChangePasswordRequest(current_password="bad", new_password="NewPassword123"),
            db=db,
            user=user,
        )
    assert bad_current.value.status_code == 400

    monkeypatch.setattr(api, "verify_password", lambda *_: True)
    monkeypatch.setattr(api, "hash_password", lambda pw: f"h::{pw}")
    ok = await api.change_password(
        api.ChangePasswordRequest(current_password="ok", new_password="NewPassword123"),
        db=db,
        user=user,
    )
    assert ok["status"] == "password_updated"
    assert user.password_hash == "h::NewPassword123"


@pytest.mark.asyncio
async def test_admin_reset_and_deactivate_edge_cases(monkeypatch):
    """Validates admin reset/deactivate failure and self-protection branches."""
    db_reset_nf = _FakeDB()
    db_reset_nf.queue_result(_FakeResult(scalar_value=None))
    with pytest.raises(HTTPException) as reset_nf:
        await api.admin_reset_password(
            str(uuid4()),
            api.AdminResetPasswordRequest(new_password="Password123"),
            db=db_reset_nf,
            admin=_staff_user(role="admin"),
        )
    assert reset_nf.value.status_code == 404

    target = _staff_user()
    db_reset_ok = _FakeDB()
    db_reset_ok.queue_result(_FakeResult(scalar_value=target))
    monkeypatch.setattr(api, "hash_password", lambda pw: f"hashed::{pw}")
    out = await api.admin_reset_password(
        str(target.id),
        api.AdminResetPasswordRequest(new_password="Password123"),
        db=db_reset_ok,
        admin=_staff_user(role="admin"),
    )
    assert out["status"] == "password_reset"
    assert target.password_hash == "hashed::Password123"
    assert db_reset_ok.commits == 1

    admin = _staff_user(role="admin")
    self_target = _staff_user(id=admin.id)
    db_self = _FakeDB()
    db_self.queue_result(_FakeResult(scalar_value=self_target))
    with pytest.raises(HTTPException) as self_exc:
        await api.deactivate_user(str(admin.id), db=db_self, admin=admin)
    assert self_exc.value.status_code == 400


@pytest.mark.asyncio
async def test_sso_rate_limit_and_token_validation_errors(monkeypatch):
    """Validates SSO rate limiting plus malformed/expired gateway token rejection logic."""
    api._sso_rate_buckets.clear()
    client_ip = "10.0.0.1"
    monkeypatch.setattr(api.time, "monotonic", lambda: 1000.0)
    for _ in range(api.SSO_RATE_LIMIT):
        api._check_sso_rate_limit(client_ip)
    with pytest.raises(HTTPException) as rate_exc:
        api._check_sso_rate_limit(client_ip)
    assert rate_exc.value.status_code == 429

    class _Resp:
        def __init__(self, status_code=401, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    class _ClientReject:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_a, **_k):
            return _Resp(status_code=401)

    monkeypatch.setattr(api.httpx, "AsyncClient", lambda *a, **k: _ClientReject())
    with pytest.raises(HTTPException) as invalid_exc:
        await api._validate_gateway_token("malformed")
    assert invalid_exc.value.status_code == 401

    class _ClientTimeout:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_a, **_k):
            raise httpx.RequestError("timeout", request=httpx.Request("GET", "http://gateway"))

    monkeypatch.setattr(api.httpx, "AsyncClient", lambda *a, **k: _ClientTimeout())
    with pytest.raises(HTTPException) as timeout_exc:
        await api._validate_gateway_token("expired")
    assert timeout_exc.value.status_code == 502


@pytest.mark.asyncio
async def test_sso_provision_and_existing_inactive_user(monkeypatch):
    """Validates SSO user auto-provisioning and inactive account denial without real gateway/db IO."""
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    monkeypatch.setattr(api, "_check_sso_rate_limit", lambda *_: None)
    async def _gw_user(_token):
        return {
            "username": "gateway-user",
            "role": "operator",
            "full_name": "Gateway User",
            # No email: exercise fallback email path.
        }

    monkeypatch.setattr(api, "_validate_gateway_token", _gw_user)
    monkeypatch.setattr(api, "hash_password", lambda _: "generated-hash")
    monkeypatch.setattr(api, "create_access_token", lambda **claims: f"token::{claims['role']}")

    db_new = _FakeDB()
    db_new.queue_result(_FakeResult(scalar_value=None))
    out = await api.sso_login(api.SSORequest(gateway_token="valid"), request=request, db=db_new)
    assert out.access_token == "token::manager"
    assert out.user["email"] == "gateway-user@fortress.local"
    assert db_new.commits == 1
    assert db_new.refreshed == 1

    inactive = _staff_user(email="inactive@example.com", is_active=False)
    db_inactive = _FakeDB()
    db_inactive.queue_result(_FakeResult(scalar_value=inactive))
    async def _gw_inactive(_token):
        return {"email": "inactive@example.com", "username": "inactive", "role": "viewer"}

    monkeypatch.setattr(api, "_validate_gateway_token", _gw_inactive)
    with pytest.raises(HTTPException) as inactive_exc:
        await api.sso_login(api.SSORequest(gateway_token="valid"), request=request, db=db_inactive)
    assert inactive_exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_users_and_command_center_url():
    """Validates admin listing and command-center URL exposure are deterministic and side-effect free."""
    db = _FakeDB()
    db.queue_result(_FakeResult(rows=[_staff_user(first_name="A"), _staff_user(first_name="B")]))
    users = await api.list_users(db=db, _admin=_staff_user(role="admin"))
    assert len(users) == 2
    assert users[0].email.endswith("@example.com")

    out = await api.get_command_center_url()
    assert out["url"] == api.settings.command_center_url
