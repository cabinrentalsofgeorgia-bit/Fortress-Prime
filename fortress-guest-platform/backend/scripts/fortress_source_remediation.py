#!/usr/bin/env python3
"""Generate Fortress Legal source blocker remediation manifest."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_source_remediation import (
    apply_source_remediation_addendum,
    create_source_remediation_manifest,
    write_source_remediation_manifest,
)

ALLOW_FLAG = "FORTRESS_ALLOW_SOURCE_REMEDIATION"


def _default_execution_id() -> str:
    return f"fortress-source-remediation-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate source blocker remediation manifest.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    parser.add_argument("--attach-addendum", action="store_true")
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_source_remediation_manifest(args.case_slug, args.execution_id)
    path = write_source_remediation_manifest(payload)
    if args.attach_addendum:
        apply_source_remediation_addendum(payload)
    summary = payload["remediation_summary"]
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"blockers_processed={summary['total_blockers_processed']}")
    print(f"resolved_source_verified={summary['resolved_source_verified']}")
    print(f"resolved_corrected_for_review_use={summary['resolved_corrected_for_review_use']}")
    print(f"unresolved_unsupported={summary['unresolved_unsupported']}")
    print(f"unresolved_needs_page_or_chunk_review={summary['unresolved_needs_page_or_chunk_review']}")
    print(f"unresolved_locked_or_privilege_limited={summary['unresolved_locked_or_privilege_limited']}")
    print(f"remaining_blockers={summary['remaining_blockers']}")
    print(f"verified_subset_count={summary['verified_subset_count']}")
    print(f"limited_signoff_subset_available={'yes' if summary['limited_signoff_subset_available'] else 'no'}")
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
