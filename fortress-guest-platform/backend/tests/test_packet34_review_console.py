from __future__ import annotations

import csv
import json
from pathlib import Path

from backend.scripts.packet34_review_console import run_console


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


PACKET34_FIELDS = [
    "thread_worksheet_id",
    "thread_group_id",
    "thread_key",
    "worksheet_ids",
    "source_review_ids",
    "subjects",
    "participants",
    "privilege_risks",
    "matched_groups",
    "selected_attachment_file_names",
    "source_absolute_paths",
    "body_preview_digest",
    "review_questions",
    "operator_opened_thread_yes_no",
    "operator_issue_confirmed_yes_no",
    "operator_privilege_cleared_yes_no",
    "operator_source_documents_identified_yes_no",
    "operator_promotion_candidate_count",
    "operator_promote_any_yes_no",
    "operator_next_action",
    "operator_notes",
]

PACKET33_FIELDS = [
    "worksheet_id",
    "source_review_id",
    "source_type",
    "review_item",
    "source_absolute_path",
    "source_sha256",
    "thread_key",
    "selected_attachment_file_name",
    "selected_attachment_sha256",
    "selected_attachment_content_type",
    "selected_attachment_size_bytes",
    "case_slug_guess",
    "privilege_risk",
    "privilege_reason",
    "matched_groups",
]


def _fixture_files(tmp_path: Path) -> tuple[Path, Path]:
    packet34 = tmp_path / "packet34.tsv"
    packet33 = tmp_path / "packet33.tsv"
    _write_tsv(
        packet34,
        PACKET34_FIELDS,
        [
            {
                "thread_worksheet_id": "TW34-01",
                "thread_group_id": "TG33-01",
                "thread_key": "ref:abc",
                "worksheet_ids": "PW32-01; PW32-02",
                "source_review_ids": "PR31-001; PR31-002",
                "subjects": "Test thread",
                "participants": "gary@example.com; counsel@example.com",
                "privilege_risks": "likely_privileged",
                "matched_groups": "argo_counsel; easement_crossing",
                "selected_attachment_file_names": "source.pdf",
                "source_absolute_paths": "/nas/source.eml",
                "body_preview_digest": "Preview text",
                "review_questions": "Review questions",
                "operator_opened_thread_yes_no": "NO",
                "operator_issue_confirmed_yes_no": "",
                "operator_privilege_cleared_yes_no": "",
                "operator_source_documents_identified_yes_no": "",
                "operator_promotion_candidate_count": "0",
                "operator_promote_any_yes_no": "NO",
                "operator_next_action": "",
                "operator_notes": "",
            }
        ],
    )
    _write_tsv(
        packet33,
        PACKET33_FIELDS,
        [
            {
                "worksheet_id": "PW32-01",
                "source_review_id": "PR31-001",
                "source_type": "email",
                "review_item": "Email",
                "source_absolute_path": "/nas/source.eml",
                "source_sha256": "aaa",
                "thread_key": "ref:abc",
                "selected_attachment_file_name": "",
                "selected_attachment_sha256": "",
                "selected_attachment_content_type": "",
                "selected_attachment_size_bytes": "",
                "case_slug_guess": "7il-v-knight-ndga-ii",
                "privilege_risk": "likely_privileged",
                "privilege_reason": "counsel domain",
                "matched_groups": "argo_counsel",
            },
            {
                "worksheet_id": "PW32-02",
                "source_review_id": "PR31-002",
                "source_type": "attachment",
                "review_item": "source.pdf",
                "source_absolute_path": "/nas/source.eml",
                "source_sha256": "bbb",
                "thread_key": "ref:abc",
                "selected_attachment_file_name": "source.pdf",
                "selected_attachment_sha256": "ccc",
                "selected_attachment_content_type": "application/pdf",
                "selected_attachment_size_bytes": "123",
                "case_slug_guess": "7il-v-knight-ndga-ii",
                "privilege_risk": "likely_privileged",
                "privilege_reason": "counsel domain",
                "matched_groups": "easement_crossing",
            },
        ],
    )
    return packet34, packet33


def test_console_blocks_incomplete_existing_packet34(tmp_path: Path) -> None:
    packet34, packet33 = _fixture_files(tmp_path)

    summary = run_console(packet34=packet34, packet33=packet33, output_dir=tmp_path / "out")

    assert summary["promotion_candidates"] == 0
    gate_rows = _read_tsv(Path(summary["packet36_gate_report"]))
    assert gate_rows[0]["candidate_extraction_gate_status"] == "BLOCKED_INCOMPLETE_OR_CONTRADICTORY"
    assert "operator_issue_confirmed_yes_no" in gate_rows[0]["missing_or_not_yes_fields"]
    assert gate_rows[0]["dry_run_ingest_allowed"] == "NO"
    assert gate_rows[0]["real_ingest_allowed"] == "NO"


def test_console_emits_candidates_only_for_fully_cleared_selected_rows(tmp_path: Path) -> None:
    packet34, packet33 = _fixture_files(tmp_path)
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps({
        "TW34-01": {
            "operator_opened_thread_yes_no": "YES",
            "operator_issue_confirmed_yes_no": "YES",
            "operator_privilege_cleared_yes_no": "YES",
            "operator_source_documents_identified_yes_no": "YES",
            "operator_promote_any_yes_no": "YES",
            "operator_promotion_candidate_count": "1",
            "promotion_worksheet_ids": ["PW32-02"],
            "operator_next_action": "prepare candidate for second authorization",
            "operator_notes": "attachment selected only",
        }
    }))

    summary = run_console(
        packet34=packet34,
        packet33=packet33,
        output_dir=tmp_path / "out",
        responses_json=responses,
    )

    assert summary["threads_gate_cleared"] == 1
    assert summary["promotion_candidates"] == 1
    candidates = _read_tsv(Path(summary["promotion_candidate_packet"]))
    assert candidates[0]["worksheet_id"] == "PW32-02"
    assert candidates[0]["second_authorization_status"] == "REQUIRED"
    assert candidates[0]["dry_run_ingest_authorized"] == "NO"
    assert candidates[0]["real_ingest_authorized"] == "NO"


def test_console_blocks_contradictory_promotion_decision(tmp_path: Path) -> None:
    packet34, packet33 = _fixture_files(tmp_path)
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps({
        "TW34-01": {
            "operator_opened_thread_yes_no": "YES",
            "operator_issue_confirmed_yes_no": "YES",
            "operator_privilege_cleared_yes_no": "NO",
            "operator_source_documents_identified_yes_no": "YES",
            "operator_promote_any_yes_no": "YES",
            "operator_promotion_candidate_count": "1",
            "promotion_worksheet_ids": ["PW32-02"],
            "operator_next_action": "bad contradictory response",
        }
    }))

    summary = run_console(
        packet34=packet34,
        packet33=packet33,
        output_dir=tmp_path / "out",
        responses_json=responses,
    )

    assert summary["promotion_candidates"] == 0
    gate_rows = _read_tsv(Path(summary["packet36_gate_report"]))
    assert gate_rows[0]["candidate_extraction_gate_status"] == "BLOCKED_INCOMPLETE_OR_CONTRADICTORY"
    assert "promote_yes_requires_operator_privilege_cleared_yes_no_yes" in gate_rows[0]["validation_errors"]
