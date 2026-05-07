#!/usr/bin/env python3
"""Generate Fortress Legal draft work product manifest."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_draft_work_product import (
    create_draft_work_product_manifest,
    write_draft_work_product_manifest,
)

ALLOW_FLAG = "FORTRESS_ALLOW_DRAFT_WORK_PRODUCT"


def _default_execution_id() -> str:
    return f"fortress-draft-work-product-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate source-limited draft work product packet.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    args = parser.parse_args()
    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")
    payload = create_draft_work_product_manifest(args.case_slug, args.execution_id)
    path = write_draft_work_product_manifest(payload)
    basis = payload["source_basis"]
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"included_verified_items={basis['included_verified_item_count']}")
    print(f"excluded_unresolved_items={basis['excluded_unresolved_item_count']}")
    print(f"sections_generated={payload['draft_packet']['sections_generated']}")
    print(f"source_refs_total={basis['source_refs_total']}")
    print("raw_document_upload=no")
    print("new_ingest=no")
    print("document_rows_created=no")
    print("qdrant_vectors_created=no")
    print("schema_changes=no")
    print("rls_policy_changes=no")
    print("signoff_auto_created=no")
    print("explicit_signoff_recorded=no")
    print("final_legal_conclusions_created=no")
    print("external_submission_authorized=no")
    print("locked_content_analyzed=no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
