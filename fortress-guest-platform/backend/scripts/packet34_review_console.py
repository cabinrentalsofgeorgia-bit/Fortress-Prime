#!/usr/bin/env python3
"""Packet 34 operator review console.

This tool is intentionally file-only. It reads Packet 34 and Packet 33 TSVs,
helps the operator review one thread at a time, then emits:

- a completed Packet 34 worksheet,
- a Packet 36 gate report, and
- a promotion-candidate packet containing only explicitly selected, fully
  cleared source rows.

It never writes to Postgres, Qdrant, NAS evidence vaults, or ingest runners.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten
from typing import Iterable


YES_NO_FIELDS = (
    "operator_opened_thread_yes_no",
    "operator_issue_confirmed_yes_no",
    "operator_privilege_cleared_yes_no",
    "operator_source_documents_identified_yes_no",
    "operator_promote_any_yes_no",
)

REQUIRED_FIELDS = YES_NO_FIELDS + (
    "operator_promotion_candidate_count",
    "operator_next_action",
)

OPERATOR_FIELDS = REQUIRED_FIELDS + ("operator_notes",)

PACKET34_DEFAULT_NAME = "34_thread_first_operator_review_worksheet.completed.tsv"
PACKET36_DEFAULT_NAME = "36_candidate_extraction_gate_report.tsv"
PROMOTION_DEFAULT_NAME = "promotion_candidate_packet_from_packet34.tsv"
SUMMARY_DEFAULT_NAME = "packet34_review_console_summary.json"


@dataclass
class ThreadValidation:
    thread_worksheet_id: str
    missing_fields: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    promotion_worksheet_ids: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields and not self.errors

    @property
    def is_fully_cleared(self) -> bool:
        return self.is_complete and not self.warnings


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _norm(value: object) -> str:
    return str(value or "").strip()


def _upper(value: object) -> str:
    return _norm(value).upper()


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace(",", ";").split(";") if part.strip()]


def _load_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header row")
        return list(reader.fieldnames), [dict(row) for row in reader]


def _write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _load_responses(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text())
    if isinstance(raw, dict) and isinstance(raw.get("threads"), list):
        return {str(item["thread_worksheet_id"]): dict(item) for item in raw["threads"]}
    if isinstance(raw, dict):
        return {str(key): dict(value) for key, value in raw.items()}
    raise ValueError("responses JSON must be an object keyed by thread id or {'threads': [...]}")


def _index_locator_rows(locator_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in locator_rows:
        worksheet_id = _norm(row.get("worksheet_id"))
        if worksheet_id:
            indexed[worksheet_id] = row
    return indexed


def _locator_rows_for_thread(
    thread_row: dict[str, str],
    locator_rows: list[dict[str, str]],
    locator_by_worksheet: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    worksheet_ids = _split_list(thread_row.get("worksheet_ids", ""))
    selected = [locator_by_worksheet[item] for item in worksheet_ids if item in locator_by_worksheet]
    if selected:
        return selected

    review_ids = set(_split_list(thread_row.get("source_review_ids", "")))
    thread_key = _norm(thread_row.get("thread_key"))
    fallback = [
        row for row in locator_rows
        if _norm(row.get("source_review_id")) in review_ids
        or (_norm(row.get("thread_key")) == thread_key and thread_key)
    ]
    return fallback


def _coerce_count(row: dict[str, object]) -> int | None:
    value = _norm(row.get("operator_promotion_candidate_count"))
    if value == "":
        return None
    try:
        count = int(value)
    except ValueError:
        return None
    return count if count >= 0 else None


def _apply_response(thread_row: dict[str, str], response: dict[str, object]) -> dict[str, str]:
    merged = dict(thread_row)
    for field_name in OPERATOR_FIELDS:
        if field_name in response:
            merged[field_name] = _norm(response[field_name])
    if "promotion_worksheet_ids" in response:
        merged["_promotion_worksheet_ids"] = "; ".join(str(item).strip() for item in response["promotion_worksheet_ids"])
    return merged


def _validate_thread(
    thread_row: dict[str, str],
    locator_rows: list[dict[str, str]],
) -> ThreadValidation:
    validation = ThreadValidation(thread_worksheet_id=_norm(thread_row.get("thread_worksheet_id")))

    for field_name in YES_NO_FIELDS:
        value = _upper(thread_row.get(field_name))
        if value not in {"YES", "NO"}:
            validation.missing_fields.append(field_name)

    count = _coerce_count(thread_row)
    if count is None:
        validation.missing_fields.append("operator_promotion_candidate_count")

    if not _norm(thread_row.get("operator_next_action")):
        validation.missing_fields.append("operator_next_action")

    opened = _upper(thread_row.get("operator_opened_thread_yes_no"))
    issue = _upper(thread_row.get("operator_issue_confirmed_yes_no"))
    privilege = _upper(thread_row.get("operator_privilege_cleared_yes_no"))
    source_docs = _upper(thread_row.get("operator_source_documents_identified_yes_no"))
    promote = _upper(thread_row.get("operator_promote_any_yes_no"))
    count_value = count if count is not None else -1
    promotion_ids = _split_list(_norm(thread_row.get("_promotion_worksheet_ids")))
    validation.promotion_worksheet_ids = promotion_ids

    if opened == "NO" and any(value == "YES" for value in (issue, privilege, source_docs, promote)):
        validation.errors.append("thread_not_opened_but_yes_decision_present")

    if promote == "YES":
        for field_name, value in (
            ("operator_issue_confirmed_yes_no", issue),
            ("operator_privilege_cleared_yes_no", privilege),
            ("operator_source_documents_identified_yes_no", source_docs),
        ):
            if value != "YES":
                validation.errors.append(f"promote_yes_requires_{field_name}_yes")
        if count_value <= 0:
            validation.errors.append("promote_yes_requires_positive_promotion_count")
        if not promotion_ids:
            validation.errors.append("promote_yes_requires_promotion_worksheet_ids")
        if count_value >= 0 and promotion_ids and count_value != len(promotion_ids):
            validation.errors.append("promotion_count_must_match_selected_worksheet_ids")

    if promote == "NO" and count_value not in {-1, 0}:
        validation.errors.append("promote_no_requires_zero_promotion_count")

    available_ids = {_norm(row.get("worksheet_id")) for row in locator_rows}
    unknown_ids = [item for item in promotion_ids if item not in available_ids]
    if unknown_ids:
        validation.errors.append("unknown_promotion_worksheet_ids:" + ",".join(unknown_ids))

    if _upper(thread_row.get("privilege_risks")) not in {"", "UNKNOWN"} and privilege != "YES":
        validation.warnings.append("privilege_risk_not_cleared")

    if promote == "YES" and not validation.errors and not validation.missing_fields:
        # Fully cleared rows are allowed into the candidate packet. The second
        # authorization gate still remains closed downstream.
        validation.warnings = [warning for warning in validation.warnings if warning != "privilege_risk_not_cleared"]

    return validation


def _gate_row(thread_row: dict[str, str], validation: ThreadValidation) -> dict[str, object]:
    promote = _upper(thread_row.get("operator_promote_any_yes_no"))
    fully_cleared = (
        validation.is_complete
        and promote == "YES"
        and _upper(thread_row.get("operator_issue_confirmed_yes_no")) == "YES"
        and _upper(thread_row.get("operator_privilege_cleared_yes_no")) == "YES"
        and _upper(thread_row.get("operator_source_documents_identified_yes_no")) == "YES"
    )

    if validation.missing_fields or validation.errors:
        status = "BLOCKED_INCOMPLETE_OR_CONTRADICTORY"
        allowed = "NO"
    elif fully_cleared:
        status = "CLEARED_FOR_PROMOTION_CANDIDATE_REQUIRES_SECOND_AUTHORIZATION"
        allowed = "YES"
    else:
        status = "OPERATOR_REVIEWED_NO_PROMOTION" if promote == "NO" else "BLOCKED_OPERATOR_REVIEW_NOT_CLEARED"
        allowed = "NO"

    triage_lane = "privilege_first_argo_easement_review"
    if "likely_privileged" not in _norm(thread_row.get("privilege_risks")).lower():
        triage_lane = "operator_review"

    return {
        "thread_worksheet_id": thread_row.get("thread_worksheet_id", ""),
        "thread_group_id": thread_row.get("thread_group_id", ""),
        "triage_lane": triage_lane,
        "candidate_extraction_gate_status": status,
        "missing_or_not_yes_fields": "; ".join(validation.missing_fields),
        "validation_errors": "; ".join(validation.errors),
        "validation_warnings": "; ".join(validation.warnings),
        "operator_promote_any_yes_no": thread_row.get("operator_promote_any_yes_no", ""),
        "operator_issue_confirmed_yes_no": thread_row.get("operator_issue_confirmed_yes_no", ""),
        "operator_privilege_cleared_yes_no": thread_row.get("operator_privilege_cleared_yes_no", ""),
        "operator_source_documents_identified_yes_no": thread_row.get("operator_source_documents_identified_yes_no", ""),
        "candidate_extraction_allowed": allowed,
        "second_authorization_required_before_dry_run": "YES" if allowed == "YES" else "NO",
        "dry_run_ingest_allowed": "NO",
        "real_ingest_allowed": "NO",
    }


def _candidate_rows(
    thread_row: dict[str, str],
    validation: ThreadValidation,
    locator_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    gate = _gate_row(thread_row, validation)
    if gate["candidate_extraction_allowed"] != "YES":
        return []

    selected = set(validation.promotion_worksheet_ids)
    output: list[dict[str, object]] = []
    for row in locator_rows:
        worksheet_id = _norm(row.get("worksheet_id"))
        if worksheet_id not in selected:
            continue
        output.append({
            "promotion_candidate_id": f"PC34-{thread_row.get('thread_worksheet_id', '')}-{worksheet_id}",
            "thread_worksheet_id": thread_row.get("thread_worksheet_id", ""),
            "thread_group_id": thread_row.get("thread_group_id", ""),
            "worksheet_id": worksheet_id,
            "source_review_id": row.get("source_review_id", ""),
            "source_type": row.get("source_type", ""),
            "review_item": row.get("review_item", ""),
            "source_absolute_path": row.get("source_absolute_path", ""),
            "source_sha256": row.get("source_sha256", ""),
            "selected_attachment_file_name": row.get("selected_attachment_file_name", ""),
            "selected_attachment_sha256": row.get("selected_attachment_sha256", ""),
            "selected_attachment_content_type": row.get("selected_attachment_content_type", ""),
            "selected_attachment_size_bytes": row.get("selected_attachment_size_bytes", ""),
            "case_slug_guess": row.get("case_slug_guess", ""),
            "privilege_risk": row.get("privilege_risk", ""),
            "privilege_reason": row.get("privilege_reason", ""),
            "matched_groups": row.get("matched_groups", ""),
            "operator_issue_confirmed_yes_no": thread_row.get("operator_issue_confirmed_yes_no", ""),
            "operator_privilege_cleared_yes_no": thread_row.get("operator_privilege_cleared_yes_no", ""),
            "operator_source_documents_identified_yes_no": thread_row.get("operator_source_documents_identified_yes_no", ""),
            "operator_notes": thread_row.get("operator_notes", ""),
            "second_authorization_required_before_dry_run": "YES",
            "second_authorization_status": "REQUIRED",
            "dry_run_ingest_authorized": "NO",
            "real_ingest_authorized": "NO",
        })
    return output


def _print_thread(thread_row: dict[str, str], locator_rows: list[dict[str, str]]) -> None:
    print("\n" + "=" * 90)
    print(f"Thread: {thread_row.get('thread_worksheet_id')} / {thread_row.get('thread_group_id')}")
    print(f"Subject: {thread_row.get('subjects')}")
    print(f"Participants: {thread_row.get('participants')}")
    print(f"Privilege warnings: {thread_row.get('privilege_risks') or 'none'}")
    print(f"Matched warnings: {thread_row.get('matched_groups') or 'none'}")
    print(f"Attachments: {thread_row.get('selected_attachment_file_names') or 'none'}")
    print(f"Source paths: {thread_row.get('source_absolute_paths')}")
    print("\nPreview:")
    print(shorten(thread_row.get("body_preview_digest", ""), width=1800, placeholder=" ..."))
    print("\nReview questions:")
    print(thread_row.get("review_questions", ""))
    print("\nSource rows:")
    for row in locator_rows:
        print(
            f"- {row.get('worksheet_id')} | {row.get('source_type')} | "
            f"{row.get('review_item')} | {row.get('source_absolute_path')}"
        )
        if row.get("sent_at") or row.get("sender_email") or row.get("to_addresses"):
            print(
                f"  date/sender/recipients: {row.get('sent_at', '')} | "
                f"{row.get('sender_email', '')} -> {row.get('to_addresses', '')}"
            )
        if row.get("attachment_summary") or row.get("selected_attachment_file_name"):
            print(
                f"  attachments: {row.get('attachment_summary') or row.get('selected_attachment_file_name')}"
            )
        print(
            f"  hash: source={row.get('source_sha256', '')} "
            f"attachment={row.get('selected_attachment_sha256', '')}"
        )
        print(
            f"  warnings: privilege={row.get('privilege_risk', '')} "
            f"reason={row.get('privilege_reason', '')}; "
            "source separation requires operator YES before promotion"
        )


def _prompt_yes_no(label: str) -> str:
    while True:
        answer = input(f"{label} [YES/NO]: ").strip().upper()
        if answer in {"Y", "YES"}:
            return "YES"
        if answer in {"N", "NO"}:
            return "NO"
        print("Please enter YES or NO.")


def _prompt_thread_decision(thread_row: dict[str, str], locator_rows: list[dict[str, str]]) -> dict[str, object]:
    _print_thread(thread_row, locator_rows)
    decision: dict[str, object] = {}
    decision["operator_opened_thread_yes_no"] = _prompt_yes_no("Opened thread")
    decision["operator_issue_confirmed_yes_no"] = _prompt_yes_no("Issue confirmed")
    decision["operator_privilege_cleared_yes_no"] = _prompt_yes_no("Privilege cleared")
    decision["operator_source_documents_identified_yes_no"] = _prompt_yes_no("Source documents identified")
    decision["operator_promote_any_yes_no"] = _prompt_yes_no("Promote any")
    if decision["operator_promote_any_yes_no"] == "YES":
        available = [row.get("worksheet_id", "") for row in locator_rows if row.get("worksheet_id")]
        print(f"Available source row ids: {', '.join(available)}")
        selected = _split_list(input("Promotion worksheet ids, separated by commas: "))
        decision["promotion_worksheet_ids"] = selected
        decision["operator_promotion_candidate_count"] = str(len(selected))
    else:
        decision["promotion_worksheet_ids"] = []
        decision["operator_promotion_candidate_count"] = "0"
    decision["operator_next_action"] = input("Next action: ").strip()
    decision["operator_notes"] = input("Notes: ").strip()
    return decision


def run_console(
    *,
    packet34: Path,
    packet33: Path,
    output_dir: Path,
    responses_json: Path | None = None,
    interactive: bool = False,
    overwrite: bool = False,
) -> dict[str, object]:
    packet34_fields, packet34_rows = _load_tsv(packet34)
    _, locator_rows = _load_tsv(packet33)
    locator_by_worksheet = _index_locator_rows(locator_rows)
    responses = _load_responses(responses_json)

    stamp = _now_stamp()
    if overwrite:
        completed_path = output_dir / PACKET34_DEFAULT_NAME
        gate_path = output_dir / PACKET36_DEFAULT_NAME
        promotion_path = output_dir / PROMOTION_DEFAULT_NAME
        summary_path = output_dir / SUMMARY_DEFAULT_NAME
    else:
        completed_path = output_dir / f"34_thread_first_operator_review_worksheet.completed.{stamp}.tsv"
        gate_path = output_dir / f"36_candidate_extraction_gate_report.{stamp}.tsv"
        promotion_path = output_dir / f"promotion_candidate_packet_from_packet34.{stamp}.tsv"
        summary_path = output_dir / f"packet34_review_console_summary.{stamp}.json"

    completed_rows: list[dict[str, str]] = []
    gate_rows: list[dict[str, object]] = []
    promotion_rows: list[dict[str, object]] = []

    for row in packet34_rows:
        thread_id = _norm(row.get("thread_worksheet_id"))
        source_rows = _locator_rows_for_thread(row, locator_rows, locator_by_worksheet)
        response = responses.get(thread_id)
        if response is None and interactive:
            response = _prompt_thread_decision(row, source_rows)
        completed = _apply_response(row, response or {})
        validation = _validate_thread(completed, source_rows)
        completed_rows.append(completed)
        gate_rows.append(_gate_row(completed, validation))
        promotion_rows.extend(_candidate_rows(completed, validation, source_rows))

    completed_fields = list(packet34_fields)
    if "_promotion_worksheet_ids" not in completed_fields:
        completed_fields.append("_promotion_worksheet_ids")
    _write_tsv(completed_path, completed_fields, completed_rows)

    gate_fields = [
        "thread_worksheet_id",
        "thread_group_id",
        "triage_lane",
        "candidate_extraction_gate_status",
        "missing_or_not_yes_fields",
        "validation_errors",
        "validation_warnings",
        "operator_promote_any_yes_no",
        "operator_issue_confirmed_yes_no",
        "operator_privilege_cleared_yes_no",
        "operator_source_documents_identified_yes_no",
        "candidate_extraction_allowed",
        "second_authorization_required_before_dry_run",
        "dry_run_ingest_allowed",
        "real_ingest_allowed",
    ]
    _write_tsv(gate_path, gate_fields, gate_rows)

    promotion_fields = [
        "promotion_candidate_id",
        "thread_worksheet_id",
        "thread_group_id",
        "worksheet_id",
        "source_review_id",
        "source_type",
        "review_item",
        "source_absolute_path",
        "source_sha256",
        "selected_attachment_file_name",
        "selected_attachment_sha256",
        "selected_attachment_content_type",
        "selected_attachment_size_bytes",
        "case_slug_guess",
        "privilege_risk",
        "privilege_reason",
        "matched_groups",
        "operator_issue_confirmed_yes_no",
        "operator_privilege_cleared_yes_no",
        "operator_source_documents_identified_yes_no",
        "operator_notes",
        "second_authorization_required_before_dry_run",
        "second_authorization_status",
        "dry_run_ingest_authorized",
        "real_ingest_authorized",
    ]
    _write_tsv(promotion_path, promotion_fields, promotion_rows)

    summary = {
        "packet34": str(packet34),
        "packet33": str(packet33),
        "completed_packet34": str(completed_path),
        "packet36_gate_report": str(gate_path),
        "promotion_candidate_packet": str(promotion_path),
        "threads_seen": len(completed_rows),
        "threads_gate_cleared": sum(1 for row in gate_rows if row["candidate_extraction_allowed"] == "YES"),
        "promotion_candidates": len(promotion_rows),
        "db_writes": "NO",
        "qdrant_writes": "NO",
        "ingest": "NO",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review Packet 34 threads and emit gated review packets.")
    parser.add_argument("--packet34", type=Path, required=True, help="Packet 34 thread worksheet TSV")
    parser.add_argument("--packet33", type=Path, required=True, help="Packet 33 locator/preview TSV")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for completed packets")
    parser.add_argument("--responses-json", type=Path, help="Non-interactive operator responses JSON")
    parser.add_argument("--interactive", action="store_true", help="Prompt the operator one thread at a time")
    parser.add_argument("--overwrite", action="store_true", help="Use stable output filenames instead of timestamped names")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.interactive and args.responses_json is None:
        print(
            "No responses provided. Existing Packet 34 values will be validated and all incomplete rows will stay blocked.",
            file=sys.stderr,
        )
    summary = run_console(
        packet34=args.packet34,
        packet33=args.packet33,
        output_dir=args.output_dir,
        responses_json=args.responses_json,
        interactive=args.interactive,
        overwrite=args.overwrite,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
