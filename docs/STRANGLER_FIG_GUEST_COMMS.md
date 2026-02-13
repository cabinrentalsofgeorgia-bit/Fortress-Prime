# Strangler Fig Audit: Guest Communications

**Auditor:** The Architect (Gemini 3 Pro)
**Date:** 2026-02-13
**Governing Document:** CONSTITUTION.md, Articles I & III
**Sector:** S01 (CROG) — Cabin Rentals of Georgia
**Target:** Wrap existing local guest reply pipeline in OODA, expose via API, strangle Streamline out of guest comms

---

## 1. Current State Assessment

### What Already Exists (100% Local)

The guest communications pipeline is the most mature local-first system in the Fortress.
No Streamline VRS dependency exists for guest messaging.

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Reply Engine | `src/guest_reply_engine.py` | 715 | Production-ready |
| Gmail Watcher | `src/gmail_watcher.py` | 1071 | Production-ready |
| Topic Classifier | `prompts/topic_classifier.py` | — | Active |
| Tone Detector | `prompts/tone_detector.py` | — | Active |
| Context Slicer | `prompts/context_slicer.py` | — | Active |
| Dynamic Examples | `prompts/starred_db.py` | — | Active |
| Cabin Knowledge | `cabins/*.yaml` | — | 36+ properties |
| Gmail Auth | `src/gmail_auth.py` | — | Active |

### Pipeline Flow (Already Sovereign)

```
Gmail Inbox (unread) ──► gmail_watcher.py
                              │
                              ▼
                        Sender Filter (allowlist)
                              │
                              ▼
                        guest_reply_engine.process_email()
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                  ▼
      1. Classify Topic  2. Detect Tone  3. Slice Context
            │                 │                  │
            └────────┬────────┘                  │
                     ▼                           ▼
              4. Load Examples          5. Render Prompt
                     │                           │
                     └───────────┬───────────────┘
                                 ▼
                          6. LLM Call (local Ollama)
                                 │
                                 ▼
                          7. Log Execution
                                 │
                    ┌────────────┴─────────────┐
                    ▼                          ▼
            Draft → Gmail Drafts      Escalation → AI-Human-Help label
            (human reviews + sends)   (Gary reviews immediately)
```

### What's Missing (Pre-Strangler Gaps)

| Gap | Severity | Description |
|-----|----------|-------------|
| No API surface | HIGH | No `/v1/crog/guests/reply` endpoint — only CLI and gmail_watcher |
| No OODA audit trail | HIGH | Pipeline logs to JSONL files, not `system_post_mortems` (Article III violation) |
| `FF_GUEST_COMMS` unused | MEDIUM | Feature flag exists in `config.py` but never referenced |
| No guest_leads integration | MEDIUM | Reply engine doesn't know guest history (VIP, prior stays) |
| No R1 quality review | LOW | VIP responses not reviewed by deep reasoning (TITAN mode) |

---

## 2. Constitutional Compliance

### Article I — Data Sovereignty

**Verdict: COMPLIANT.** Guest comms pipeline is already 100% local.

| Data Element | Classification | Storage | Cloud Exposure | Status |
|-------------|---------------|---------|----------------|--------|
| Guest email text | RESTRICTED (PII) | Gmail API + local processing | Gmail (Google) — unavoidable | Acceptable |
| AI draft response | RESTRICTED | Gmail Drafts | Gmail (Google) — drafts only | Acceptable |
| Topic/tone classification | INTERNAL | JSONL logs | None | Compliant |
| Cabin context | INTERNAL | `cabins/*.yaml` | None | Compliant |
| Guest contact info | RESTRICTED (PII) | `guest_leads` | None | Compliant |
| LLM inference | INTERNAL | Local Ollama (SWARM) | None | Compliant |

**Note:** Gmail API access is unavoidable for email processing but complies with
Article I because: (a) the email data originates in Gmail, (b) we only CREATE drafts
(never auto-send), and (c) no Fortress-internal data is uploaded to Google.

### Article III — Self-Healing

**Verdict: NON-COMPLIANT (pre-fix).** The existing pipeline logs to JSONL files
but does not write to `system_post_mortems`. The OODA agent wrapper fixes this.

---

## 3. Strangler Implementation

### What Was Built

| Component | Path | Purpose |
|-----------|------|---------|
| Guest Comms OODA Agent | `src/agents/guest_comms.py` | Wraps `guest_reply_engine` in OODA pattern |
| API Endpoint | `gateway/crog_api.py` | `POST /v1/crog/guests/reply` |
| Feature Flag | `config.py` → `FF_GUEST_COMMS` | Routes between OODA agent and legacy CLI |
| Audit Document | This file | Migration plan and compliance analysis |

### OODA Cycle Implementation

```
OBSERVE ──────────────────────────────────────────────────────────
│  Receive guest email
│  Identify cabin from slug
│  Enrich with guest_leads (prior stays, VIP flag, history)
▼
ORIENT ───────────────────────────────────────────────────────────
│  Run topic_classifier → primary + secondary topics
│  Run tone_detector → tone + modifier + escalation flag
│  Run context_slicer → relevant cabin YAML sections only
│  Load dynamic few-shot examples from starred_db
│  Calculate confidence score (topic_conf * tone_adjustment * VIP_boost)
▼
DECIDE ───────────────────────────────────────────────────────────
│  IF escalation_required OR emergency_tone:
│      → ESCALATE to human (AI-Human-Help label)
│  ELIF TITAN mode AND VIP guest:
│      → GENERATE with R1 quality review
│  ELSE:
│      → GENERATE via SWARM inference
▼
ACT ──────────────────────────────────────────────────────────────
│  Call guest_reply_engine.process_email()
│  Generate AI draft (NEVER auto-send)
│  Optional: R1 reviews VIP drafts for accuracy/tone
│  Return GuestReplyResponse (Pydantic validated)
▼
POST-MORTEM ──────────────────────────────────────────────────────
   Write to system_post_mortems (sector=crog, component=ooda:crog)
   Full audit trail: every step timestamped with decisions
```

### API Contract

```
POST /v1/crog/guests/reply
Authorization: Bearer <jwt>  (requires operator role)

Request:
{
    "cabin_slug": "rolling_river",
    "guest_email": "Can I charge my Tesla at the cabin?",
    "guest_email_address": "guest@example.com",
    "dry_run": false
}

Response:
{
    "draft": "Thank you for your inquiry! Rolling River has a standard 120V...",
    "success": true,
    "classification": {
        "topic": "ev_charging",
        "secondary_topics": [],
        "topic_confidence": 0.92,
        "tone": "standard",
        "tone_modifier": "curious",
        "escalation_required": false
    },
    "cabin_slug": "rolling_river",
    "cabin_name": "Rolling River",
    "guest_context": {
        "guest_name": "Jane Smith",
        "prior_stays": 2,
        "vip_flag": false,
        "prior_topics": ["hot_tub", "pets"]
    },
    "context_tokens": 1200,
    "tokens_saved": 3400,
    "examples_loaded": 3,
    "duration_ms": 2340,
    "model_used": "qwen2.5:7b",
    "ooda_confidence": 0.88,
    "ooda_decision": "GENERATE draft via SWARM inference. Confidence=0.88.",
    "audit_trail": ["[2026-02-13T12:00:00Z] OBSERVE: ...", "..."],
    "source": "fortress_local",
    "classification_level": "RESTRICTED"
}
```

---

## 4. Migration Phases

### Phase 1 — Build (COMPLETE)

- [x] `src/agents/guest_comms.py` — OODA agent with guest enrichment
- [x] `POST /v1/crog/guests/reply` — API endpoint with feature flag
- [x] `FF_GUEST_COMMS` — Feature flag in `config.py`
- [x] Guest lead enrichment — query `guest_leads` for prior stay context
- [x] R1 quality review — TITAN mode VIP draft review
- [x] Pydantic models — `GuestReplyRequest`, `GuestReplyResponse`
- [x] This audit document

### Phase 2 — Parallel Validation (Weeks 1-2)

- [ ] Set `FF_GUEST_COMMS=true` in staging
- [ ] Run both `gmail_watcher.py` (existing) and API endpoint in parallel
- [ ] Compare: topic classification, tone detection, draft quality, escalation decisions
- [ ] Log discrepancies to `system_post_mortems`
- [ ] Validate guest_leads enrichment adds value to response quality

### Phase 3 — Production Cutover (Week 3)

- [ ] Set `FF_GUEST_COMMS=true` in production `config.py`
- [ ] Migrate `gmail_watcher.py` to call `generate_guest_reply()` instead of
      `process_email()` directly (uses OODA audit trail)
- [ ] Human (Gary) reviews comparison report and approves

### Phase 4 — Decommission Legacy Path (Week 4+)

- [ ] `gmail_watcher.py` fully delegates to `src/agents/guest_comms.py`
- [ ] Direct `process_email()` calls remain available for CLI testing
- [ ] No Streamline code to remove — guest comms was never on Streamline

---

## 5. What This Does NOT Strangle

Guest communications were never on Streamline VRS. The "strangling" here is:

1. **CLI-only → API:** Moving from `python -m src.gmail_watcher` to `POST /v1/crog/guests/reply`.
2. **No audit → Full OODA audit:** Every guest reply now writes to `system_post_mortems`.
3. **No enrichment → Guest history:** Replies now incorporate prior stay data from `guest_leads`.
4. **No quality gate → R1 review:** VIP guest drafts are reviewed by R1 in TITAN mode.

The remaining Streamline dependencies for CROG are:
- **Calendar/availability** (`GetPropertyRates` via `groundskeeper_shadow.py`) — next strangler target
- **Reservation data** (`GetReservationList`) — supplements shadow calendar
- **Property sync** (`GetPropertyList`) — initial property import

---

*Audit complete. Filed to `docs/STRANGLER_FIG_GUEST_COMMS.md`.*
*Status: Phase 1 COMPLETE. Ready for parallel validation.*
