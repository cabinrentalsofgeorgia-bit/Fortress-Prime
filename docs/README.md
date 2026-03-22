# Documentation Directory

This directory contains project documentation and legal documents.

## Statement of Work (SOW)

**Location:** `statement-of-work.pdf` (or `sow.pdf`)

**Project:** AI-PMS & Sovereign Cloud Architecture ("Hybrid Fortress")

**Client:** Cabin Rentals of Georgia

**Date:** December 20, 2025

**Platform:** Upwork

**Value:** $33,600 (420 hours @ $80/hr)

---

To add the SOW PDF, place it in this directory with one of these names:
- `statement-of-work.pdf` (recommended)
- `sow.pdf`
- `SOW_December_2025.pdf`

## Operations Runbooks

- `SEO_OPERATOR_RUNTIME_RUNBOOK.md`: Stable runtime commands, dedicated deploy-consumer ownership, verified teardown semantics, and smoke flow for the SEO operator loop.

## Runtime Launchers

- `fortress-guest-platform/scripts/`: App-local launcher scripts for the SEO operator runtime and smoke flow.
- `fortress-guest-platform/scripts/start_seo_operator_stack.sh`: Idempotent one-command bring-up for the SEO operator stack.
- `fortress-guest-platform/scripts/stop_seo_operator_stack.sh`: Matching one-command teardown for the SEO operator stack.
