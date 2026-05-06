#!/usr/bin/env python3
"""Generate Fortress Legal limited signoff candidate packet manifest."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_limited_signoff_candidate_packet import (
    apply_limited_signoff_candidate_addendum,
    create_limited_signoff_candidate_manifest,
    write_limited_signoff_candidate_manifest,
)

ALLOW_FLAG = "FORTRESS_ALLOW_LIMITED_SIGNOFF_CANDIDATE"


def _default_execution_id() -> str:
    return f"fortress-limited-signoff-candidate-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate limited signoff candidate packet manifest.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    parser.add_argument("--attach-addendum", action="store_true")
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_limited_signoff_candidate_manifest(args.case_slug, args.execution_id)
    path = write_limited_signoff_candidate_manifest(payload)
    if args.attach_addendum:
        apply_limited_signoff_candidate_addendum(payload)
    tiers = payload["tier_summary"]
    packet = payload["limited_signoff_candidate_packet"]
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"starting_unresolved={len(payload['unresolved_blocker_register_v2'])}")
    print(f"tier_1_count={tiers['tier_1_count']}")
    print(f"tier_2_count={tiers['tier_2_count']}")
    print(f"tier_3_count={tiers['tier_3_count']}")
    print(f"included_in_candidate={packet['included_item_count']}")
    print(f"excluded_from_candidate={packet['excluded_item_count']}")
    print(f"requires_counsel_interpretation={tiers['requires_counsel_interpretation']}")
    print(f"requires_more_evidence={tiers['requires_more_evidence']}")
    print(f"locked_privilege_limited={tiers['locked_privilege_limited']}")
    print(f"unsupported={tiers['unsupported']}")
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
