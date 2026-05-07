#!/usr/bin/env python3
"""Generate Fortress Legal targeted source completion manifest."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_targeted_source_completion import (
    apply_targeted_source_completion_addendum,
    create_targeted_source_completion_manifest,
    write_targeted_source_completion_manifest,
)

ALLOW_FLAG = "FORTRESS_ALLOW_TARGETED_SOURCE_COMPLETION"


def _default_execution_id() -> str:
    return f"fortress-targeted-source-completion-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate targeted source completion manifest.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    parser.add_argument("--attach-addendum", action="store_true")
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_targeted_source_completion_manifest(args.case_slug, args.execution_id)
    path = write_targeted_source_completion_manifest(payload)
    if args.attach_addendum:
        apply_targeted_source_completion_addendum(payload)
    summary = payload["completion_summary"]
    track_a = summary["track_results"]["track_a_page_chunk_review"]
    track_b = summary["track_results"]["track_b_unsupported_recheck"]
    track_c = summary["track_results"]["track_c_locked_privilege_limited"]
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"starting_unresolved={summary['starting_unresolved']}")
    print(f"items_processed={summary['items_processed']}")
    print(f"prior_verified_subset_count={summary['prior_verified_subset_count']}")
    print(f"new_verified_subset_count={summary['new_verified_subset_count']}")
    print(f"verified_subset_delta={summary['verified_subset_delta']}")
    print(f"remaining_unresolved={summary['remaining_unresolved']}")
    print(f"track_a_items={track_a['items']}")
    print(f"track_a_corrected={track_a['corrected']}")
    print(f"track_a_unresolved={track_a['unresolved']}")
    print(f"track_b_items={track_b['items']}")
    print(f"track_b_still_unsupported={track_b['still_unsupported']}")
    print(f"track_c_items={track_c['items']}")
    print(f"track_c_metadata_only={track_c['preserved_metadata_only']}")
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
