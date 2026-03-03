# Canonical Module Registry

This registry defines the canonical implementation file per duplicated domain. New work must extend canonical modules, not reintroduce parallel variants.

## Governance

| Domain | Canonical File(s) | Status |
|---|---|---|
| Enterprise rule index | `.cursor/rules/000-enterprise-constitution.mdc` | Active |
| Infra/NIM policy | `.cursor/rules/001-titan-protocol.mdc` | Active |
| Governance ownership/workflow | `.cursor/rules/002-sovereign-constitution.mdc` | Active |
| DGX/NIM operations | `.cursor/rules/010-nvidia-dgx-nim-operations.mdc` | Active |

## Script Consolidations

| Domain | Canonical File(s) | Replaced Files |
|---|---|---|
| RueBaRue extraction pipeline | `src/extract_ruebarue_all.py` | `extract_ruebarue_data.py`, `extract_ruebarue_guides.py`, `extract_ruebarue_messages.py`, `extract_ruebarue_messages_v2.py`, `extract_ruebarue_phase1.py`, `extract_ruebarue_phase2_admin.py`, `extract_ruebarue_phase2_guides.py`, `extract_ruebarue_phase2_guides_v2.py`, `extract_ruebarue_taylor.py`, `extract_all_ruebarue_data.py`, `extract_guides_complete.py` |
| Market signal simulation | `src/fleet_commander.py` | `src/market_agent.py`, `src/market_feeder.py` |
| Forensic scrap runner | `src/phase2_forensic_scrap.py` | `src/phase2_forensic_scrap_uncapped.py`, `src/phase2_scrap_infinity.py` |
| Telemetry ingestion | `src/pulse_agent.py` | `src/telemetry_agent.py` |

## Change Control

1. If a new module is proposed in a mapped domain, the PR/change must explain why canonical extension is insufficient.
2. Duplicate module introductions require explicit operator approval.
3. Canonical changes must update this registry in the same change set.
