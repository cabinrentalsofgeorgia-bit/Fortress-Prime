# Fortress Legal Email Intake Foundation

Last updated: 2026-05-04
Status: PR foundation gate, manifest-only

## Purpose

This pass gives Fortress Legal a safe first step for Wilson Pruitt, Argo,
closing, and post-closing email source drops. It inventories operator-supplied
`.eml` files and Outlook `.msg` files and produces a reviewable manifest before
any evidence ingestion.

## Contract

The source-drop planner:

- Parses `.eml` files from an explicit operator source directory.
- Parses `.msg` files with `extract-msg` when the optional Outlook parser is
  installed.
- Preserves `.msg` files as hash-only native review candidates when the parser
  is unavailable or a native file cannot be parsed.
- Extracts message identity, sender/recipient metadata, dates, thread headers,
  normalized subject, body preview, and attachment metadata for `.eml` files.
- Extracts the same manifest-facing metadata from parseable `.msg` files,
  including attachment hashes.
- Preserves `.msg` source path, relative path, SHA-256, filename-derived subject,
  case/privilege guesses, and `native_review_required` decision for fallback
  candidates without parsing message bodies or attachments.
- Computes SHA-256 hashes for the raw email and each attachment.
- Makes conservative case-slug and privilege-risk guesses.
- Writes a JSON manifest.
- Performs no IMAP, Postgres, Qdrant, NAS vault, correspondence, timeline, or
  `process_vault_upload()` writes.

The planner blocks the legacy mixed 7IL dump by default:

`/mnt/fortress_nas/legal_vault/7il-v-knight-ndga/`

Use curated source-drop paths under:

`/mnt/fortress_nas/Corporate_Legal/Business_Legal/<case_slug>/`

## Operator Command

```bash
cd ~/Fortress-Prime/fortress-guest-platform
.uv-venv/bin/python -m backend.scripts.legal_email_source_drop_plan \
  --source-root /mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/email-source-drops/wilson-pruitt \
  --output /mnt/fortress_nas/audits/legal-email-source-drop-wilson-pruitt-2026-05-03.json
```

The command prints a short count summary and writes the full manifest. Review
the manifest before running any later ingest step.

## Manifest Fields

Each candidate includes:

- `source_path`, `source_relative_path`, `source_sha256`
- `message_id`, `in_reply_to`, `references`, `thread_key`
- `subject`, `normalized_subject`, `sent_at`
- `sender_email`, recipients, and participant domains
- `body_preview`
- attachment file names, content types, byte sizes, and hashes
- `case_slug_guess` and `case_guess_reason`
- `privilege_risk` and `privilege_reason`
- `intake_decision=manifest_only`
- `source_format`, `parser_status`, and `parser_reason`

For parsed `.msg` files, `source_format` is `msg`, `parser_status` is `parsed`,
and `parser_reason` identifies the `extract_msg` parser version. If the parser
is unavailable or fails for a particular native file, `intake_decision` becomes
`native_review_required`, `parser_status` is `native_inventory_only` or
`native_parse_error`, and attachment/message-body fields remain empty.

## Dependency Review

The controlled `.msg` parser is `extract-msg==0.55.0`.

- It is purpose-built for Microsoft Outlook `.msg` extraction and has recent
  releases.
- It is preferred over `msg-parser`, whose PyPI classifier is pre-alpha and
  whose latest release is from 2019.
- It is still treated as an optional parser: Fortress Legal imports and runs
  safely without it, falling back to hash-only native review.
- Installing the dependency does not authorize ingestion or evidence promotion.

## Next Gate

Only after operator review should a later PR add a controlled promotion path
from manifest candidates into `legal.email_intake_queue`, `email_archive`, or
`legal.vault_documents`.
