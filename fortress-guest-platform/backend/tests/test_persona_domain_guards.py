from __future__ import annotations

import json

import pytest

import run  # noqa: F401
from backend.services import crog_concierge_engine, legal_council


def _write_persona(path, *, slug: str, vector_collection: str, domain: str) -> None:
    path.write_text(
        json.dumps(
            {
                "name": slug.replace("-", " ").title(),
                "slug": slug,
                "seat": 1,
                "archetype": "tester",
                "domain": domain,
                "god_head_domain": domain,
                "worldview": "test",
                "bias": [],
                "focus_areas": [],
                "trigger_events": [],
                "godhead_prompt": "test",
                "vector_collection": vector_collection,
            }
        ),
        encoding="utf-8",
    )


def test_concierge_persona_guard_rejects_legal_collection(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_persona(
        tmp_path / "01-invalid.json",
        slug="guest-experience-lead",
        vector_collection="legal_library",
        domain="hospitality",
    )
    monkeypatch.setattr(crog_concierge_engine, "CONCIERGE_PERSONAS_DIR", str(tmp_path))

    with pytest.raises(crog_concierge_engine.ConciergePersonaBoundaryError):
        crog_concierge_engine.ConciergePersona.load_all()


def test_legal_persona_guard_rejects_hospitality_collection(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_persona(
        tmp_path / "01-invalid.json",
        slug="chief-justice",
        vector_collection="fgp_knowledge",
        domain="legal",
    )
    monkeypatch.setattr(legal_council, "PERSONAS_DIR", str(tmp_path))

    with pytest.raises(legal_council.LegalPersonaBoundaryError):
        legal_council.LegalPersona.load_all()
