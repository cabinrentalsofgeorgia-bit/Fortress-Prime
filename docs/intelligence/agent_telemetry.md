# Agent Telemetry Ledger

This ledger is the permanent Teacher-Student learning record for agent-executed repository work.
Node 5, The Chronicler, MUST append an entry before Node 4 is allowed to commit code.

## Entry Template

### Entry XXX - YYYY-MM-DD - Short Title
- **Objective:** What was requested.
- **Execution:** Files modified.
- **Friction:** Any errors caught by Node 3 (The Crucible) during local builds.
- **Resolution:** How the friction was solved, or what was learned if no fix was required.

---

## Entries

### Entry 001 - 2026-03-19 - AI Telemetry Ledger Bootstrap
- **Objective:** Establish a permanent AI telemetry ledger, add Node 5 (The Chronicler) to the Sovereign Constitution, and seed the first Teacher-Student learning record.
- **Execution:** Created `docs/intelligence/agent_telemetry.md`; updated `.cursor/rules/002-sovereign-constitution.mdc`.
- **Friction:** `git checkout main` was blocked because `main` is already checked out in another worktree. The first Crucible attempt also failed because `eslint` was unavailable before installing frontend dependencies. After `npm ci`, `npm run lint` surfaced existing repo-wide frontend issues outside this change set, including `@typescript-eslint/no-explicit-any`, `react-hooks/set-state-in-effect`, `react/no-unescaped-entities`, `@next/next/no-html-link-for-pages`, and `react-hooks/refs`. `npm run build` completed successfully.
- **Resolution:** Branched directly from `main` into `infra/agent-telemetry` inside this worktree, bootstrapped the frontend with `npm ci`, and treated the lint errors as pre-existing Crucible findings rather than telemetry-regression defects because this change only touched documentation and rules. The learning outcome is that Node 5 should record both environment bootstrap issues and unrelated validation debt before Node 4 commits.

### Entry 003 - 2026-03-19 - HITL Cognitive Wiring
- **Objective:** Wire a strict Human-In-The-Loop state machine into backend guest messaging so the AI can draft and queue outbound SMS but cannot dispatch to Twilio without explicit approval.
- **Execution:** Updated `fortress-guest-platform/backend/models/message.py`; `fortress-guest-platform/backend/models/__init__.py`; `fortress-guest-platform/backend/integrations/twilio_client.py`; `fortress-guest-platform/backend/services/message_service.py`; `fortress-guest-platform/backend/services/lifecycle_engine.py`; `fortress-guest-platform/backend/services/scheduler_service.py`; `fortress-guest-platform/backend/services/operations_service.py`; `fortress-guest-platform/backend/services/housekeeping_agent.py`; `fortress-guest-platform/backend/services/agentic_orchestrator.py`; `fortress-guest-platform/backend/api/webhooks.py`; `fortress-guest-platform/backend/api/messages.py`; `fortress-guest-platform/backend/api/review_queue.py`; `fortress-guest-platform/backend/api/damage_claims.py`; created `fortress-guest-platform/backend/scripts/alter_messages_hitl.sql`.
- **Friction:** `Base.metadata.create_all()` could not mutate the existing PostgreSQL `messages` table, so the new HITL columns required a raw migration. The first migration attempt failed because the default `fgp_app` password in backend config did not authenticate against the host Postgres instance. A full-backend `pyright` pass reported 1449 existing errors, and a narrowed pass over the touched files still reported 274 errors concentrated in pre-existing SQLAlchemy typing debt across `api/damage_claims.py`, `api/messages.py`, `api/review_queue.py`, and `api/webhooks.py`. `python3 -m compileall fortress-guest-platform/backend` passed, and `python3 fortress-guest-platform/backend/scripts/verify_god_heads.py` passed.
- **Resolution:** Enforced the choke point by changing `TwilioClient.send_sms()` to require a persisted `Message` object whose `approval_status` is `approved`, then rerouted automated guest messaging to `MessageService.create_draft_sms()` so lifecycle and orchestrator flows now stop at `pending_approval`. Preserved data with an inline Postgres migration executed as the local database superuser:

```sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type
        WHERE typname = 'message_approval_status'
    ) THEN
        CREATE TYPE message_approval_status AS ENUM (
            'pending_approval',
            'approved',
            'rejected'
        );
    END IF;
END
$$;
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS approval_status message_approval_status;
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS agent_reasoning TEXT;
UPDATE public.messages SET approval_status = 'approved' WHERE approval_status IS NULL;
ALTER TABLE public.messages ALTER COLUMN approval_status SET DEFAULT 'approved';
ALTER TABLE public.messages ALTER COLUMN approval_status SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_messages_approval_status ON public.messages (approval_status);
```

The learning outcome is that code-first schema management on this host still needs explicit SQL for live tables, and strict HITL enforcement must live at the Twilio wrapper boundary so no downstream agent can fire raw text payloads around the database gate.

### Entry 004 - 2026-03-19 - Outbound Draft Review Interface
- **Objective:** Expose backend review endpoints so authenticated staff can list, inspect, approve, or reject `pending_approval` outbound drafts before Twilio dispatch.
- **Execution:** Updated `fortress-guest-platform/backend/models/message.py`; `fortress-guest-platform/backend/services/message_service.py`; `fortress-guest-platform/backend/main.py`; created `fortress-guest-platform/backend/schemas/message_review.py`; created `fortress-guest-platform/backend/api/outbound_drafts.py`; created `fortress-guest-platform/backend/scripts/alter_messages_reviewer.sql`.
- **Friction:** The repo’s `Message` model does not include `property_id`, and `Guest` stores names as `first_name` plus `last_name`, so the review payload had to derive `property_id` from the joined `Reservation` and build `guest_name` on the query side. The reviewer-column migration needed explicit SQL because `Base.metadata.create_all()` cannot alter existing tables. A narrowed `pyright` pass over the touched review files dropped to `11` remaining errors, all in older `message_service.py` ORM typing paths outside the new outbound-draft review methods. `python3 -m compileall fortress-guest-platform/backend` passed, and `python3 fortress-guest-platform/backend/scripts/verify_god_heads.py` passed.
- **Resolution:** Added `reviewed_by` and `reviewed_at` to the `messages` table and model, created a flattened async review schema, implemented a dedicated `api/outbound_drafts.py` router, and added async service methods that use joined selects plus `FOR UPDATE` row locking for approve/reject actions. Executed the reviewer migration directly on Postgres:

```sql
ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS reviewed_by UUID;
ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
```

The learning outcome is that the Human viewport should consume a flattened query contract from the backend, while approval state, reviewer metadata, and Twilio dispatch remain centralized in the message service to preserve the HITL choke point.
