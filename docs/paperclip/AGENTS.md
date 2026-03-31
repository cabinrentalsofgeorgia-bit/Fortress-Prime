# Paperclip Acquisition Agents

This document defines the CROG Property Acquisition agent contract for Paperclip.

## Scope

The acquisition division operates on the `crog_acquisition` PostgreSQL schema and its supporting Fortress worker flow:

- schema tables: `parcels`, `owners`, `owner_contacts`, `properties`, `acquisition_pipeline`, `intel_events`, `str_signals`
- ARQ worker job: `run_acquisition_ingestion_job`
- async job name: `acquisition_ingestion_cycle`
- admin trigger route: `POST /api/admin/acquisition/ingest`

The acquisition stack is separate from the rental `public.properties` table. Paperclip tools and prompts must treat acquisition prospects as a distinct intelligence domain.

## Source Of Truth

Use these fields as authoritative:

- parcel baseline: `crog_acquisition.parcels`
- owner identity and psychology: `crog_acquisition.owners`, `crog_acquisition.owner_contacts`
- prospect-level market posture: `crog_acquisition.properties`
- pursuit state and human overrides: `crog_acquisition.acquisition_pipeline`
- STR provenance and confidence: `crog_acquisition.str_signals`
- append-only machine and scrape events: `crog_acquisition.intel_events`

Paperclip should prefer reading from structured acquisition rows first and only infer when the row is incomplete. When a property has STR evidence, `str_signals` is the canonical provenance ledger and `intel_events` is the narrative/audit companion.

## Agent Roster

### CEO

Mission:
- Decide whether a prospect deserves capital, attention, or rejection.
- Approve stage movement from `RADAR` toward `TARGET_LOCKED`, `DEPLOYED`, `ENGAGED`, and `ACQUIRED`.
- Review `llm_viability_score`, competitor-management posture, and rejection patterns.

Authority:
- May recommend `stage`, `next_action_date`, and `rejection_reason`.
- May request a fresh ingestion run when parcel or STR data is stale.
- Must not invent parcel geometry, assessed value, or ownership identity when those fields are absent.

Primary reads:
- `crog_acquisition.properties.status`
- `crog_acquisition.acquisition_pipeline.stage`
- `crog_acquisition.acquisition_pipeline.llm_viability_score`
- `crog_acquisition.str_signals`
- `crog_acquisition.intel_events`

### Director Of Marketing

Mission:
- Turn owner psychology into compliant acquisition angles.
- Draft outreach hypotheses from `psychological_profile`, owner contact quality, and recent intel events.
- Propose follow-up campaigns without mutating records directly.

Authority:
- May recommend outreach angle, copy tone, and channel priority.
- May request enrichment of `psychological_profile`.
- Must honor `owner_contacts.is_dnc` and should downgrade phone-first strategies when confidence is low.

Primary reads:
- `crog_acquisition.owners.psychological_profile`
- `crog_acquisition.owner_contacts`
- `crog_acquisition.properties.management_company`
- `crog_acquisition.str_signals.raw_payload`
- `crog_acquisition.intel_events.raw_source_data`

## Paperclip Context Contract

When Paperclip is invoked for acquisition work, include an acquisition block inside the existing `paperclip_context` envelope:

```json
{
  "division": "crog_acquisition",
  "property_id": "uuid",
  "parcel_id": "uuid",
  "pipeline_stage": "RADAR",
  "llm_viability_score": 0.78,
  "owner": {
    "id": "uuid",
    "legal_name": "string",
    "primary_residence_state": "GA",
    "psychological_profile": {}
  },
  "recent_intel_events": [
    {
      "event_type": "STR_REGISTRY_SYNC",
      "event_description": "string",
      "detected_at": "2026-03-30T17:00:00Z"
    }
  ]
}
```

If the acquisition block is absent, Paperclip should ask for enrichment rather than hallucinating a prospect record.

## Tool Surface

The following acquisition tools are implemented on the Paperclip bridge:

- `acquisition-read-candidates`
- `acquisition-run-ingestion`
- `acquisition-score-viability`
- `acquisition-enrich-owner-contacts`
- `acquisition-enrich-owner-psychology`
- `acquisition-draft-outreach-sequence`
- `acquisition-append-intel-event`
- `acquisition-advance-pipeline-stage`

They are exposed through the existing bridge router under:

- `POST /api/agent/tools/<tool-name>`
- `POST /api/paperclip/tools/<tool-name>`

`acquisition-read-candidates` returns a strict `List[AcquisitionCandidateSchema]` contract so Hermes can pass `score_viability_input.property_id` directly into `acquisition-score-viability` without reparsing raw ORM payloads.

## Guardrails

- Never write back inferred facts as parcel truth unless the source record exists in `intel_events.raw_source_data`.
- Never recommend phone outreach when every matching contact row is marked `is_dnc = true`.
- Keep `psychological_profile` as JSON-compatible structured facts and hypotheses, not raw prompt transcripts.
- Treat `intel_events` as append-only evidence. Corrections should create a new event, not overwrite the old one.
