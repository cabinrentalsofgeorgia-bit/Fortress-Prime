#!/usr/bin/env python3
"""Generate a signoff-ready reviewed strategy packet manifest.

This command writes packet/signoff readiness artifacts only. It does not
upload documents, ingest records, create vectors, create schema, change RLS,
or auto-create signoff.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from backend.services.legal_counsel_signoff_packet import (
    TARGET_SLUG,
    create_signoff_packet_manifest,
    write_signoff_packet_manifest,
)

ALLOW_FLAG = "FORTRESS_ALLOW_COUNSEL_SIGNOFF_PACKET"


def _default_execution_id() -> str:
    return f"fortress-signoff-packet-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate reviewed strategy packet/signoff readiness manifest.")
    parser.add_argument("--case-slug", default=TARGET_SLUG)
    parser.add_argument("--execution-id", default=_default_execution_id())
    args = parser.parse_args()

    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if args.case_slug != TARGET_SLUG:
        raise SystemExit("target_case_refused")

    payload = create_signoff_packet_manifest(args.case_slug, args.execution_id)
    path = write_signoff_packet_manifest(payload)
    print(f"execution_id={payload['execution_id']}")
    print(f"case_slug={payload['case_slug']}")
    print(f"manifest_path={path}")
    print(f"packet_version={payload['packet_version']}")
    print(f"packet_sections={len(payload['sections'])}")
    print(f"packet_checksum={payload['packet_checksum']}")
    print(f"readiness_status={payload['readiness_status']}")
    print(f"signoff_status={payload['signoff_status']}")
    print(f"unresolved_items={len(payload['unresolved_items_register'])}")
    print(f"source_items_needing_check={payload['source_integrity_matrix']['items_needing_source_check']}")
    print("signoff_auto_created=no")
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
