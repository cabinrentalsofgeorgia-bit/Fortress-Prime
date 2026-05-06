#!/usr/bin/env python3
"""Generate Fortress Legal source-integrity validation records.

This command classifies already-derived material packet items using existing
source-reference metadata. It never reads locked content, uploads documents,
creates vectors, changes schema/RLS, or records signoff.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_source_integrity_validation import (
    TARGET_SLUG,
    apply_source_integrity_addendum,
    create_source_integrity_manifest,
    write_source_integrity_manifest,
)

ALLOW_FLAG = "FORTRESS_ALLOW_SOURCE_INTEGRITY_VALIDATION"


def _default_execution_id() -> str:
    return f"fortress-source-integrity-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate source-integrity validation manifest.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    parser.add_argument("--attach-addendum", action="store_true")
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_source_integrity_manifest(args.case_slug, args.execution_id)
    path = write_source_integrity_manifest(payload)
    if args.attach_addendum:
        apply_source_integrity_addendum(payload)
    summary = payload["source_integrity_summary"]
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"records={summary['total_material_items']}")
    print(f"checked={summary['checked']}")
    print(f"source_verified_for_review_use={summary['source_verified_for_review_use']}")
    print(f"partially_supported={summary['partially_supported']}")
    print(f"unsupported={summary['unsupported']}")
    print(f"source_missing={summary['source_missing']}")
    print(f"needs_page_or_chunk_review={summary['needs_page_or_chunk_review']}")
    print(f"locked_or_privilege_limited={summary['locked_or_privilege_limited']}")
    print(f"signoff_blockers={summary['signoff_blockers']}")
    print(f"correction_queue_items={len(payload['correction_queue'])}")
    print(f"readiness={summary['signoff_readiness_recommendation']}")
    print("signoff_auto_created=no")
    print("explicit_signoff_recorded=no")
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
