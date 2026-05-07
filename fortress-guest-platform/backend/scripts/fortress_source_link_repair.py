#!/usr/bin/env python3
"""Generate Fortress Legal source link repair manifest."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_source_link_repair import (
    apply_source_link_repair_addendum,
    create_source_link_repair_manifest,
    write_source_link_repair_manifest,
)

ALLOW_FLAG = "FORTRESS_ALLOW_SOURCE_LINK_REPAIR"


def _default_execution_id() -> str:
    return f"fortress-source-link-repair-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate source link repair manifest.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    parser.add_argument("--attach-addendum", action="store_true")
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_source_link_repair_manifest(args.case_slug, args.execution_id)
    path = write_source_link_repair_manifest(payload)
    if args.attach_addendum:
        apply_source_link_repair_addendum(payload)
    summary = payload["repair_summary"]
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"blockers_processed={summary['total_blockers_processed']}")
    print(f"verified_for_review_use={summary['verified_for_review_use']}")
    print(f"corrected_verified_for_review_use={summary['corrected_verified_for_review_use']}")
    print(f"partially_supported={summary['partially_supported']}")
    print(f"unsupported={summary['unsupported']}")
    print(f"conflicting_sources={summary['conflicting_sources']}")
    print(f"needs_page_or_chunk_review={summary['needs_page_or_chunk_review']}")
    print(f"locked_or_privilege_limited={summary['locked_or_privilege_limited']}")
    print(f"remaining_unresolved={summary['remaining_unresolved']}")
    print(f"verified_subset_count={summary['verified_subset_count']}")
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
