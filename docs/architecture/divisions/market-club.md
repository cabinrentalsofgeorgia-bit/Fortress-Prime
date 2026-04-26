# Division: Market Club

Owner: TBD (requires operator input)
Status: **planned, requires operator input**
Last updated: 2026-04-26

## Purpose

Unknown to the architecture-foundation drafter. Surfaced in operator conversation but no grounded knowledge exists in the repo, runbooks, or `fortress_atlas.yaml` (the atlas has Sector 04 "BLOOM — Verses in Bloom (Digital Retail)" which may or may not relate).

## Open questions for operator

The most foundational, in roughly the order they need answering:

1. **What is being replaced?** Marriott Club / `MarriottClub.com` / something else?
2. **What is Dochia and what role does it serve?**
3. **What is the backup system?** What does it back up, and what triggers a failover?
4. **Is this guest-facing booking, internal ops, or something else?** Where does it sit relative to CROG-VRS — does it replace, complement, or run parallel?
5. **Connection to CROG-VRS** — does it consume CROG-VRS data, produce data that CROG-VRS consumes, or run independently?
6. **Status** — actively building, paused, post-MVP, retired-in-favor-of-something-else?
7. **Sector mapping** — is this what the atlas calls "BLOOM" (Sector 04), or is it a new division that needs to be added to the atlas?
8. **Data stores** — Postgres schema(s)? Qdrant collection(s)? NAS folders?
9. **Code surface** — where does it live in the repo (existing or planned)?
10. **External integrations** — booking APIs, payment, CRM?

## Stub-then-fill discipline

Per [`../README.md`](../README.md): when answers come in, fill the standard sections (Owner, Status, Key data stores, Key services consumed, Key services exposed, Recent merged PRs) and remove this open-questions block. Don't fabricate facts in the meantime.

## Cross-references

- Atlas Sector 04 (BLOOM) — possibly related; needs operator confirmation: [`../../../fortress_atlas.yaml`](../../../fortress_atlas.yaml)

Last updated: 2026-04-26
