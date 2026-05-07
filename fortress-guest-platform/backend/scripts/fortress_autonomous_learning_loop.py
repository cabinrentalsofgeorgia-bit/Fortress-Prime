#!/usr/bin/env python3
"""Generate Fortress Legal autonomous learning loop manifest."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_autonomous_learning_loop import (
    create_learning_loop_manifest,
    write_learning_loop_manifest,
)
from backend.services.legal_counsel_validation import TARGET_SLUG

ALLOW_FLAG = "FORTRESS_ALLOW_AUTONOMOUS_LEARNING_LOOP"


def _default_execution_id() -> str:
    return f"fortress-learning-loop-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate bounded autonomous learning loop manifest.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    parser.add_argument("--cycles", type=int, default=3)
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_learning_loop_manifest(args.case_slug, args.execution_id, cycles=args.cycles)
    path = write_learning_loop_manifest(payload)
    proposals = payload["improvement_proposals"]
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"signals={payload['learning_registry']['signal_count']}")
    print(f"evals={payload['evaluation_suite']['eval_count']}")
    print(f"proposals={proposals['proposal_count']}")
    print(f"safe_auto_apply={proposals['safe_auto_apply_count']}")
    print(f"human_approval_required={proposals['human_approval_required_count']}")
    print(f"cycles_completed={payload['cycles_completed']}")
    print("external_model_training=no")
    print("signoff_auto_created=no")
    print("explicit_signoff_recorded=no")
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
