"""Strike 16.4 — Concierge recovery draft parity helpers."""

from __future__ import annotations

from uuid import UUID

import pytest

from backend.models.rue_bar_rue_legacy_recovery_template import RueBaRueLegacyRecoveryTemplate
from backend.services.concierge_recovery_parity import (
    _pick_legacy_template,
    compute_recovery_dedupe_hash,
)


def test_compute_recovery_dedupe_hash_changes_with_intent() -> None:
    base_kw = dict(
        session_fp="fp-test",
        drop_off_point="checkout_step",
        property_slug="cabin-slug",
        guest_id=None,
    )
    a = compute_recovery_dedupe_hash(**base_kw, intent_score_estimate=1.0)
    b = compute_recovery_dedupe_hash(**base_kw, intent_score_estimate=2.0)
    assert a != b


def test_compute_recovery_dedupe_hash_includes_guest() -> None:
    gid = UUID("12345678-1234-5678-1234-567812345678")
    a = compute_recovery_dedupe_hash(
        session_fp="fp",
        drop_off_point="quote_open",
        property_slug=None,
        guest_id=None,
        intent_score_estimate=1.0,
    )
    b = compute_recovery_dedupe_hash(
        session_fp="fp",
        drop_off_point="quote_open",
        property_slug=None,
        guest_id=gid,
        intent_score_estimate=1.0,
    )
    assert a != b


def test_pick_legacy_template_prefers_exact_audience_rule() -> None:
    rows = [
        RueBaRueLegacyRecoveryTemplate(
            template_key="wild",
            channel="sms",
            audience_rule="*",
            body_template="wildcard",
            is_active=True,
            source_system="rue_ba_rue",
        ),
        RueBaRueLegacyRecoveryTemplate(
            template_key="checkout",
            channel="sms",
            audience_rule="checkout_step",
            body_template="checkout copy",
            is_active=True,
            source_system="rue_ba_rue",
        ),
    ]
    picked = _pick_legacy_template(rows, drop_off_point="checkout_step")
    assert picked is not None
    assert picked.template_key == "checkout"


def test_pick_legacy_template_falls_back_to_wildcard() -> None:
    rows = [
        RueBaRueLegacyRecoveryTemplate(
            template_key="wild",
            channel="sms",
            audience_rule="*",
            body_template="wildcard",
            is_active=True,
            source_system="rue_ba_rue",
        ),
    ]
    picked = _pick_legacy_template(rows, drop_off_point="property_view")
    assert picked is not None
    assert picked.template_key == "wild"


@pytest.mark.asyncio
async def test_run_concierge_shadow_draft_cycle_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import settings
    from backend.services.concierge_recovery_parity import run_concierge_shadow_draft_cycle

    monkeypatch.setattr(settings, "concierge_shadow_draft_enabled", False, raising=False)

    class _NoDb:
        async def commit(self) -> None:  # noqa: D401
            raise AssertionError("DB should not commit when disabled")

    out = await run_concierge_shadow_draft_cycle(_NoDb())  # type: ignore[arg-type]
    assert out["disabled"] is True
    assert out["inserted_count"] == 0
