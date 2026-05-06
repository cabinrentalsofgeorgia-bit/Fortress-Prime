#!/usr/bin/env python3
"""Generate Fortress Legal counsel signoff decision workflow manifest."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_counsel_signoff_decision import (
    create_decision_workflow_manifest,
    write_decision_workflow_manifest,
)
from backend.services.legal_counsel_validation import TARGET_SLUG

ALLOW_FLAG = "FORTRESS_ALLOW_SIGNOFF_DECISION_WORKFLOW"


def _default_execution_id() -> str:
    return f"fortress-signoff-decision-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate counsel signoff decision workflow manifest.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_decision_workflow_manifest(args.case_slug, args.execution_id)
    path = write_decision_workflow_manifest(payload)
    packet = payload["packet"]
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"packet_execution_id={packet['packet_execution_id']}")
    print(f"packet_version={packet['packet_version']}")
    print(f"packet_hash={packet['packet_hash']}")
    print(f"included_verified_subset={packet['included_verified_subset']}")
    print(f"excluded_unresolved_items={packet['excluded_unresolved_items']}")
    print(f"decision_paths={len(payload['decision_paths'])}")
    print("explicit_decision_recorded=no")
    print("signoff_auto_created=no")
    print("external_submission_authorized=no")
    print("final_legal_conclusions_created=no")
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
