# Email Pipeline — Known Issues & Follow-Ups

Status as of 2026-04-20, PR feat/email-pipeline-parallel (commit 46245ce4b)

## Working
- IMAP → email_messages persistence (idempotent on imap_uid)
- 9-seat cold-inquiry concierge deliberation
- HITL API surface: /api/email/outbound-drafts CRUD
- SMTP dispatch path (send_quote) wired but not yet end-to-end tested with a real approve

## Known issue: generic draft text for NEUTRAL consensus
When 7+ of 9 seats return `NEUTRAL` signal, the HYDRA 120B composer
(`_compose_draft_reply`) falls back to a safe "we're on it" template. The council
*does* understand the content (recommended actions in `ai_meta.recommendations`
are correct and specific), but the draft surface is generic.

**Impact:** human reviewer will edit every cold inquiry draft. Defeats the
HITL-to-autonomous glide path.

**Fix options (pick one later, not tonight):**
1. Replace composer: use Anthropic (Seat 9 or dedicated) for the final draft
   composition step on cold inquiries — frontier-class writing quality.
2. Enrich the composer prompt with the consensus recommendations (currently
   in meta but not fed back into draft prompt).
3. Add a cold-inquiry-specific template with variable substitution pulled from
   the council output (dates, party size, amenity requests).

## Known gap: SMTP approve→send path not yet E2E tested
`execute_approval_and_dispatch` exists. Never fired against a real draft.
Next session: approve a draft via `/api/email/outbound-drafts/{id}/approve`,
verify SMTP dispatch, verify reply lands in the test inbox.

## reservations_draft_queue deprecation
Old path still creates rows. Plan to drop the table and delete the code path
in a follow-up PR once the new pipeline has ≥48h of production runtime without
issue.

## Post-nightly-run health checks
- Verify cron `ingest_reservations_imap` picks up the new code path on its
  next 10-min tick (should succeed — subprocess call to backend venv is already
  wired).
- Watch `/mnt/fortress_nas/fortress_data/ai_brain/logs/reservations_imap/cron.log`
  over next 2-3 cron cycles.
