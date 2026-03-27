"""Strike 17 — Active Pilot: Enticer cohort gating and kill-switch behavior."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.guest import Guest
from backend.services import enticer_swarm_service as ess
from backend.services.enticer_swarm_service import (
    evaluate_concierge_strike17_eligibility,
    run_enticer_swarm_tick,
)


def _guest(*, gid: uuid.UUID | None = None, tier: str = "bronze", phone: str = "5551234567") -> Guest:
    return Guest(
        id=gid or uuid.uuid4(),
        email="pilot@guest.test",
        first_name="Pilot",
        last_name="Guest",
        phone=phone,
        verification_status="verified",
        loyalty_tier=tier,
    )


def test_evaluate_strike_no_cohort_configured() -> None:
    g = _guest()
    with patch.object(ess.settings, "concierge_strike_allowed_guest_ids", ""), patch.object(
        ess.settings, "concierge_strike_allowed_property_slugs", ""
    ), patch.object(ess.settings, "concierge_strike_allowed_loyalty_tiers", ""):
        ok, reason = evaluate_concierge_strike17_eligibility(guest=g, property_slug="any-slug")
        assert not ok
        assert reason == "no_cohort_configured"


def test_evaluate_strike_guest_allowlist() -> None:
    g = _guest()
    with patch.object(ess.settings, "concierge_strike_allowed_guest_ids", str(g.id)), patch.object(
        ess.settings, "concierge_strike_allowed_property_slugs", ""
    ), patch.object(ess.settings, "concierge_strike_allowed_loyalty_tiers", ""):
        ok, reason = evaluate_concierge_strike17_eligibility(guest=g, property_slug=None)
        assert ok
        assert reason == "ok"


def test_evaluate_strike_guest_not_in_allowlist() -> None:
    g = _guest()
    other = uuid.uuid4()
    with patch.object(ess.settings, "concierge_strike_allowed_guest_ids", str(other)), patch.object(
        ess.settings, "concierge_strike_allowed_property_slugs", ""
    ), patch.object(ess.settings, "concierge_strike_allowed_loyalty_tiers", ""):
        ok, reason = evaluate_concierge_strike17_eligibility(guest=g, property_slug=None)
        assert not ok
        assert reason == "guest_not_in_allowlist"


def test_evaluate_strike_property_slug_required() -> None:
    g = _guest()
    with patch.object(ess.settings, "concierge_strike_allowed_guest_ids", ""), patch.object(
        ess.settings, "concierge_strike_allowed_property_slugs", "alpha-cabin,beta-cabin"
    ), patch.object(ess.settings, "concierge_strike_allowed_loyalty_tiers", ""):
        ok, _ = evaluate_concierge_strike17_eligibility(guest=g, property_slug="alpha-cabin")
        assert ok
        ok2, reason2 = evaluate_concierge_strike17_eligibility(guest=g, property_slug="other")
        assert not ok2
        assert reason2 == "property_slug_not_in_allowlist"


def test_evaluate_strike_loyalty_tier_gate() -> None:
    g = _guest(tier="silver")
    with patch.object(ess.settings, "concierge_strike_allowed_guest_ids", ""), patch.object(
        ess.settings, "concierge_strike_allowed_property_slugs", ""
    ), patch.object(ess.settings, "concierge_strike_allowed_loyalty_tiers", "gold,platinum"):
        ok, reason = evaluate_concierge_strike17_eligibility(guest=g, property_slug=None)
        assert not ok
        assert reason == "loyalty_tier_not_in_allowlist"


@pytest.mark.asyncio
async def test_run_enticer_tick_skips_when_strike_disabled() -> None:
    db = AsyncMock()
    with patch.object(ess.settings, "concierge_recovery_sms_enabled", True), patch.object(
        ess.settings, "concierge_strike_enabled", False
    ):
        out = await run_enticer_swarm_tick(db)
    assert out[0].get("reason") == "CONCIERGE_STRIKE_ENABLED=false"


@pytest.mark.asyncio
async def test_run_enticer_tick_skips_when_agentic_inactive_and_required() -> None:
    db = AsyncMock()
    with patch.object(ess.settings, "concierge_recovery_sms_enabled", True), patch.object(
        ess.settings, "concierge_strike_enabled", True
    ), patch.object(ess.settings, "agentic_system_active", False), patch.object(
        ess.settings, "concierge_strike_require_agentic_system_active", True
    ):
        out = await run_enticer_swarm_tick(db)
    assert out[0].get("reason") == "AGENTIC_SYSTEM_ACTIVE=false"


@pytest.mark.asyncio
async def test_run_enticer_tick_no_agentic_early_exit_when_requirement_disabled() -> None:
    """Kill-switch bypass: ops can set CONCIERGE_STRIKE_REQUIRE_AGENTIC_SYSTEM_ACTIVE=false."""
    db = AsyncMock()
    with patch.object(ess.settings, "concierge_recovery_sms_enabled", True), patch.object(
        ess.settings, "concierge_strike_enabled", True
    ), patch.object(ess.settings, "agentic_system_active", False), patch.object(
        ess.settings, "concierge_strike_require_agentic_system_active", False
    ), patch.object(ess.settings, "twilio_account_sid", "ACtest"), patch.object(
        ess.settings, "twilio_auth_token", "tok"
    ), patch.object(ess.settings, "twilio_phone_number", "+15550001111"), patch(
        "backend.services.enticer_swarm_service.build_funnel_hq_payload",
        new_callable=AsyncMock,
    ) as funnel:
        funnel.return_value = {"recovery": []}
        out = await run_enticer_swarm_tick(db)
    assert out == []


@pytest.mark.asyncio
async def test_run_enticer_tick_sends_when_cohort_matches() -> None:
    gid = uuid.uuid4()
    guest = _guest(gid=gid, tier="gold")
    recovery_row = {
        "linked_guest_id": gid,
        "session_fp": "session-fp-strike17",
        "property_slug": "pilot-cabin",
    }
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=exec_result)
    db.get = AsyncMock(return_value=guest)
    db.add = MagicMock()
    db.commit = AsyncMock()

    with patch.object(ess.settings, "concierge_recovery_sms_enabled", True), patch.object(
        ess.settings, "concierge_strike_enabled", True
    ), patch.object(ess.settings, "agentic_system_active", True), patch.object(
        ess.settings, "concierge_strike_require_agentic_system_active", True
    ), patch.object(ess.settings, "twilio_account_sid", "ACtest"), patch.object(
        ess.settings, "twilio_auth_token", "tok"
    ), patch.object(ess.settings, "twilio_phone_number", "+15550001111"), patch.object(
        ess.settings, "concierge_strike_allowed_guest_ids", str(gid)
    ), patch.object(ess.settings, "concierge_strike_allowed_property_slugs", ""), patch.object(
        ess.settings, "concierge_strike_allowed_loyalty_tiers", ""
    ), patch(
        "backend.services.enticer_swarm_service.build_funnel_hq_payload",
        new_callable=AsyncMock,
    ) as funnel:
        funnel.return_value = {"recovery": [recovery_row]}
        with patch("backend.services.enticer_swarm_service.TwilioClient") as TC:
            TC.return_value.send_sms = AsyncMock(return_value={"sid": "SMstrike17"})
            send_sms = TC.return_value.send_sms
            with patch(
                "backend.services.enticer_swarm_service.record_audit_event",
                new_callable=AsyncMock,
            ) as audit:
                out = await run_enticer_swarm_tick(db)
    assert any(r.get("sent") for r in out)
    send_sms.assert_awaited_once()
    audit.assert_awaited()


@pytest.mark.asyncio
async def test_run_enticer_tick_skips_cohort_mismatch_with_audit() -> None:
    gid = uuid.uuid4()
    guest = _guest(gid=gid)
    recovery_row = {
        "linked_guest_id": gid,
        "session_fp": "session-fp-x",
        "property_slug": "wrong-slug",
    }
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=exec_result)
    db.get = AsyncMock(return_value=guest)

    with patch.object(ess.settings, "concierge_recovery_sms_enabled", True), patch.object(
        ess.settings, "concierge_strike_enabled", True
    ), patch.object(ess.settings, "agentic_system_active", True), patch.object(
        ess.settings, "concierge_strike_require_agentic_system_active", True
    ), patch.object(ess.settings, "twilio_account_sid", "ACtest"), patch.object(
        ess.settings, "twilio_auth_token", "tok"
    ), patch.object(ess.settings, "twilio_phone_number", "+15550001111"), patch.object(
        ess.settings, "concierge_strike_allowed_property_slugs", "right-cabin"
    ), patch.object(ess.settings, "concierge_strike_allowed_guest_ids", ""), patch.object(
        ess.settings, "concierge_strike_allowed_loyalty_tiers", ""
    ), patch(
        "backend.services.enticer_swarm_service.build_funnel_hq_payload",
        new_callable=AsyncMock,
    ) as funnel:
        funnel.return_value = {"recovery": [recovery_row]}
        with patch("backend.services.enticer_swarm_service.TwilioClient") as TC:
            TC.return_value.send_sms = AsyncMock()
            send_sms = TC.return_value.send_sms
            with patch(
                "backend.services.enticer_swarm_service.record_audit_event",
                new_callable=AsyncMock,
            ) as audit:
                out = await run_enticer_swarm_tick(db)
    assert any(r.get("reason") == "property_slug_not_in_allowlist" for r in out)
    send_sms.assert_not_awaited()
    audit.assert_awaited()
