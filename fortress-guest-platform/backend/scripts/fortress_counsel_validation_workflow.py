#!/usr/bin/env python3
"""Initialize the Fortress Legal counsel validation workflow manifest.

This command creates validation records for already-generated workbench output
only. It does not upload documents, ingest records, create vectors, read locked
content, change schema, or alter policies.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_counsel_validation import (
    TARGET_SLUG,
    create_validation_manifest,
    write_validation_manifest,
)

ALLOW_FLAG = "FORTRESS_ALLOW_COUNSEL_VALIDATION"


def _default_execution_id() -> str:
    return f"fortress-validation-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize counsel validation workflow records.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_validation_manifest(args.case_slug, args.execution_id)
    path = write_validation_manifest(payload)
    summary = payload["summary"]
    queues = {queue["queue_id"]: queue["item_count"] for queue in payload["queues"]}
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"validation_records={summary['total_workbench_items']}")
    print(f"issue_records={queues.get('issue-matrix-validation', 0)}")
    print(f"evidence_binder_records={queues.get('evidence-binder-validation', 0)}")
    print(f"contradiction_records={queues.get('contradiction-candidate-validation', 0)}")
    print(f"entity_dossier_records={queues.get('entity-dossier-validation', 0)}")
    print(f"counsel_question_action_records={queues.get('counsel-questions-actions-validation', 0)}")
    print(f"theory_packet_records={queues.get('theory-counter-theory-validation', 0)}")
    print(f"timeline_records={queues.get('chronology-event-validation', 0)}")
    print(f"locked_metadata_only_records={queues.get('privilege-locked-metadata-review', 0)}")
    print("raw_document_upload=no")
    print("new_ingest=no")
    print("document_rows_created=no")
    print("qdrant_vectors_created=no")
    print("schema_changes=no")
    print("rls_policy_changes=no")
    print("locked_content_analyzed=no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
