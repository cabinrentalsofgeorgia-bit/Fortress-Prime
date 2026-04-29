# Mailbox Routing — Production

**Last updated:** 2026-04-28 (FLOS Phase 0a-10)
**Source:** MAILBOXES_CONFIG in fortress-guest-platform/.env (production)

## Active routing

| Mailbox | Address | Routing tag | Captain | legal_mail_ingester |
|---------|---------|-------------|---------|---------------------|
| legal-cpanel | legal@cabin-rentals-of-georgia.com | legal | yes | yes |
| gary-gk | gary@garyknight.com | legal | yes | yes (added 2026-04-28) |
| gary-crog | gary@cabin-rentals-of-georgia.com | legal | yes | yes (added 2026-04-28) |
| info-crog | info@cabin-rentals-of-georgia.com | operations | yes | no |

## Why these mailboxes are tagged for legal_mail_ingester

Per FLOS Phase 0a §3.5 (LOCKED), all mailboxes likely to receive
litigation correspondence route through both Captain (general intake) and
legal_mail_ingester (legal-specific classification + watchdog matching).

- legal-cpanel — explicit legal mailbox, low traffic, formal correspondence
- gary-gk — gary@garyknight.com — operator's primary legal correspondence address
- gary-crog — gary@cabin-rentals-of-georgia.com — operator's business correspondence,
  receives Case I/II discovery requests, attorney communications, court notices
- info-crog — operations only, no legal traffic — NOT tagged

## routing_tag rationale (Phase 0a-10 expansion)

Initial Phase 0a-10 plan only added `ingester=legal_mail` to gary-gk and
gary-crog while preserving their existing `routing_tag=executive`. Pre-flight
diagnostic during execution showed this would not work:

- The worker preflight gates on `LEGAL_ROUTING_TAGS = {"legal", "litigation"}`
  in `services/legal_mail_ingester.py:81`. Adding `ingester=legal_mail`
  alongside `routing_tag=executive` causes preflight rejection of the entire
  ingester batch (`mailbox_count=0`).
- The privilege_class inheritance in `legal_mail_ingester.py:859` gates on
  the same `LEGAL_ROUTING_TAGS` set. Even if preflight were loosened to admit
  `executive`, messages from these mailboxes would land with
  `privilege_class=public` instead of `work_product` — wrong default for
  legal-track mail.

Path 3 chosen: retag executive → legal for gary-gk and gary-crog. This
reflects the FLOS Phase 0a §3.5 LOCKED design which declares both
mailboxes as legal-track. The pre-FLOS Captain-era "executive"
classification is superseded by the FLOS design. No downstream consumer
breaks per code audit (`source_module` flips from `captain_executive` to
`captain_legal` going forward, which is more semantically accurate for
these mailboxes; `privilege_filter` and `ai_router` make no distinction
between `captain_executive` and `captain_legal`; no DB query, frontend,
alert, or report filters on `routing_tag='executive'`).

## Why Captain coexists

Captain handles general triage (junk filtering, executive priority routing,
IFTTT-style follow-ups). legal_mail_ingester handles legal-specific work
(privilege classification, watchdog matching, event_log emission). Both run
on the same mailbox without contention because legal_mail_ingester uses
BODY.PEEK[] and never mutates \Seen.

## Operational notes

- Adding a new legal mailbox: edit MAILBOXES_CONFIG, set
  `routing_tag=legal` (or `litigation`) and `ingester=legal_mail`,
  restart fortress-arq-worker.service. Bootstrap path runs on first patrol.
- Removing the legal_mail tag: same edit, drop the ingester field. The
  ingester stops polling within one cycle. Existing state row remains
  in legal.mail_ingester_state (idempotent — re-tagging picks up where
  it left off via last_seen_uid).
- A mailbox cannot be tagged `ingester=legal_mail` unless its
  `routing_tag` is in `{legal, litigation}`. This is enforced in
  `services/legal_mail_ingester.py:174-182`.
