# Phase 3 — Flywheel Activation Sequence

Prerequisites: Phase 2 (privilege filter) complete and deployed.

## Activation steps

Step 1 — Verify Phase 2 filter is live:
  curl http://localhost:8000/api/v1/system-health | jq '.privilege_filter'
  Expect: status=active with restricted_count

Step 2 — Bootstrap llm_training_captures table:
  cd ~/Fortress-Prime
  python -m backend.workers.nightly_distillation_exporter --dry-run
  Expect: "Created table" or "Table exists"

Step 3 — Verify zero privileged content (sampled audit):
  psql -d fortress_shadow -c "SELECT COUNT(*) FROM llm_training_captures WHERE source_persona IN ('senior_litigator','contract_auditor','statutory_scholar','ediscovery_forensic','devils_advocate','compliance_officer','local_counsel','risk_assessor','chief_justice');"
  Expect: 0

Step 4 — Run exporter for real:
  python -m backend.workers.nightly_distillation_exporter
  Expect: JSONL file written

Step 5 — Spot check JSONL:
  tail -5 /path/to/latest.jsonl | head -c 500
  Confirm no privileged markers

Step 6 — Enable nightly timer:
  sudo systemctl enable fortress-nightly-finetune.timer
  sudo systemctl start fortress-nightly-finetune.timer
  sudo systemctl list-timers | grep fortress

## Exit criteria

- Step 3 returns 0
- Step 4 produces JSONL with at least one real training pair
- Step 6 timer active and scheduled
- Next morning: new JSONL file in output path

## Rollback

sudo systemctl stop fortress-nightly-finetune.timer
sudo systemctl disable fortress-nightly-finetune.timer

No destructive operations in Phase 3 — rollback is just turning the timer off. Capture data remains for audit.
