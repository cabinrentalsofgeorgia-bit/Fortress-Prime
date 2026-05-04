# Packet 34 Review Console

Status: operator-in-the-loop evidence review tool.

The Packet 34 Review Console reviews Wilson Pruitt / Argo email threads without promoting, ingesting, or writing to runtime stores.

## What It Reads

- Packet 34 thread-first worksheet.
- Packet 33 source locator / preview worksheet.
- Optional operator responses JSON for non-interactive runs.

## What It Shows

For each thread, the console displays:

- thread id and group id
- subject
- participants
- source paths
- attachment list
- preview text
- review questions
- per-source sender/date/recipient details from Packet 33
- source and attachment hashes
- privilege warnings
- source-separation warning

## What The Operator Decides

The operator must decide:

- opened thread: `YES` / `NO`
- issue confirmed: `YES` / `NO`
- privilege cleared: `YES` / `NO`
- source documents identified: `YES` / `NO`
- promote any: `YES` / `NO`
- promotion count
- specific source row ids to promote, if any
- next action
- notes

## What It Writes

- completed Packet 34 worksheet
- Packet 36 gate report
- promotion-candidate packet
- JSON summary

Promotion candidates are emitted only when the thread is complete, non-contradictory, privilege-cleared, source-doc-cleared, issue-confirmed, and the operator names the exact source row ids.

## Guardrails

- No DB writes.
- No Qdrant writes.
- No ingest.
- No source-file movement.
- No silent promotion.
- Candidate rows still require second explicit authorization before dry-run ingest.
- Real ingest still requires final explicit authorization.

## Example

```bash
python backend/scripts/packet34_review_console.py \
  --packet34 /mnt/fortress_nas/.../34_thread_first_operator_review_worksheet.tsv \
  --packet33 /mnt/fortress_nas/.../33_first15_source_locator_and_preview.tsv \
  --output-dir /mnt/fortress_nas/.../operator-review-packets/completed-packet34-review \
  --interactive
```
