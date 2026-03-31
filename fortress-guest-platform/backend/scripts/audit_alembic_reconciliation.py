"""Audit live schema vs local Alembic branch coverage.

This script inspects the local Alembic revision graph, extracts simple DDL intents
(`create_table`, `add_column`), and compares them against the live database.

It is intentionally conservative:
- `present` means all detected objects from a revision exist
- `missing` means none of the detected objects exist
- `partial` means some exist and some do not
- `no_op` means the revision appears to be a merge/anchor/no-op from the parser's perspective

The output is written to:
- docs/alembic-reconciliation-report.md
- backend/artifacts/alembic-reconciliation-report.json
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import psycopg2


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "backend" / "alembic" / "versions"
DOC_REPORT_PATH = REPO_ROOT / "docs" / "alembic-reconciliation-report.md"
JSON_REPORT_PATH = REPO_ROOT / "backend" / "artifacts" / "alembic-reconciliation-report.json"

LEGACY_BRANCH_REVISIONS = {"a9c1e4f8b2d0", "c7d8e9f0a1b2"}
WATCHLIST_TABLES = {
    "public": [
        "owner_property_map",
        "management_splits",
        "owner_markup_rules",
        "capex_staging",
        "marketing_attribution",
        "owner_marketing_preferences",
        "owner_magic_tokens",
        "trust_balance",
        "accounts",
        "journal_entries",
        "journal_line_items",
    ],
    "core": [
        "deliberation_logs",
    ],
}


@dataclass
class OperationCheck:
    op_type: str
    schema: str
    table: str
    column: str | None
    present: bool | None


@dataclass
class RevisionAudit:
    revision: str
    file: str
    down_revision: str | list[str] | None
    classification: str
    checks: list[OperationCheck]


def _load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _admin_pg_uri() -> str:
    _load_env()
    value = os.environ.get("POSTGRES_ADMIN_URI", "").strip()
    if not value:
        raise RuntimeError("POSTGRES_ADMIN_URI is not set")
    parsed = urlsplit(value)
    if parsed.scheme == "postgresql+asyncpg":
        value = value.replace("postgresql+asyncpg://", "postgresql://", 1)
    return value


def _parse_revision_file(path: Path) -> tuple[str | None, str | list[str] | None]:
    text = path.read_text()
    revision_match = re.search(r'revision:\s*str\s*=\s*"([^"]+)"', text)
    if not revision_match:
        return None, None
    revision = revision_match.group(1)

    tuple_match = re.search(r"down_revision:\s*[^=]*=\s*\(([^)]*)\)", text)
    if tuple_match:
        items = [
            part.strip().strip('"').strip("'")
            for part in tuple_match.group(1).split(",")
            if part.strip().strip('"').strip("'")
        ]
        return revision, items

    single_match = re.search(r'down_revision:\s*[^=]*=\s*"([^"]+)"', text)
    if single_match:
        return revision, single_match.group(1)

    none_match = re.search(r"down_revision:\s*[^=]*=\s*None", text)
    if none_match:
        return revision, None

    return revision, None


def _extract_operations(path: Path) -> list[OperationCheck]:
    text = path.read_text()
    checks: list[OperationCheck] = []

    for match in re.finditer(r'op\.create_table\(\s*"([^"]+)"', text, flags=re.MULTILINE | re.DOTALL):
        table = match.group(1)
        window = text[match.start() : min(len(text), match.start() + 5000)]
        schema_match = re.search(r'schema\s*=\s*"([^"]+)"', window)
        schema = schema_match.group(1) if schema_match else "public"
        checks.append(
            OperationCheck(
                op_type="create_table",
                schema=schema,
                table=table,
                column=None,
                present=None,
            )
        )

    for match in re.finditer(r'op\.add_column\(\s*"([^"]+)"', text, flags=re.MULTILINE | re.DOTALL):
        table = match.group(1)
        window = text[match.start() : min(len(text), match.start() + 1200)]
        column_match = re.search(r'sa\.Column\(\s*"([^"]+)"', window)
        if column_match:
            checks.append(
                OperationCheck(
                    op_type="add_column",
                    schema="public",
                    table=table,
                    column=column_match.group(1),
                    present=None,
                )
            )
    return checks


def _load_revision_graph() -> tuple[dict[str, tuple[Path, str | list[str] | None]], dict[str, list[str]]]:
    nodes: dict[str, tuple[Path, str | list[str] | None]] = {}
    children: dict[str, list[str]] = defaultdict(list)
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        revision, down_revision = _parse_revision_file(path)
        if not revision:
            continue
        nodes[revision] = (path, down_revision)
        if isinstance(down_revision, list):
            for parent in down_revision:
                children[parent].append(revision)
        elif isinstance(down_revision, str):
            children[down_revision].append(revision)
    return nodes, children


def _head_revisions(nodes: dict[str, tuple[Path, str | list[str] | None]], children: dict[str, list[str]]) -> list[str]:
    return sorted([revision for revision in nodes if revision not in children])


def _collect_target_revisions(
    nodes: dict[str, tuple[Path, str | list[str] | None]],
    heads: Iterable[str],
) -> list[str]:
    seen: set[str] = set()
    queue = deque(head for head in heads if head not in LEGACY_BRANCH_REVISIONS)
    while queue:
        revision = queue.popleft()
        if revision in seen:
            continue
        seen.add(revision)
        _, down_revision = nodes[revision]
        if isinstance(down_revision, list):
            for parent in down_revision:
                if parent and parent not in LEGACY_BRANCH_REVISIONS and parent in nodes:
                    queue.append(parent)
        elif isinstance(down_revision, str):
            if down_revision not in LEGACY_BRANCH_REVISIONS and down_revision in nodes:
                queue.append(down_revision)
    return sorted(seen)


def _classify(checks: list[OperationCheck]) -> str:
    if not checks:
        return "no_op"
    states = [check.present for check in checks]
    if all(state is True for state in states):
        return "present"
    if all(state is False for state in states):
        return "missing"
    return "partial"


def _mark_presence(conn, checks: list[OperationCheck]) -> list[OperationCheck]:
    cur = conn.cursor()
    for check in checks:
        if check.op_type == "create_table":
            cur.execute("SELECT to_regclass(%s)::text", (f"{check.schema}.{check.table}",))
            check.present = cur.fetchone()[0] is not None
        elif check.op_type == "add_column":
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                  AND column_name = %s
                """,
                (check.schema, check.table, check.column),
            )
            check.present = cur.fetchone() is not None
    cur.close()
    return checks


def _build_report() -> dict:
    nodes, children = _load_revision_graph()
    heads = _head_revisions(nodes, children)
    target_revisions = _collect_target_revisions(nodes, heads)

    conn = psycopg2.connect(_admin_pg_uri())
    try:
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
        live_versions = [row[0] for row in cur.fetchall()]
        cur.close()

        audits: list[RevisionAudit] = []
        summary = {"present": 0, "missing": 0, "partial": 0, "no_op": 0}
        for revision in target_revisions:
            path, down_revision = nodes[revision]
            checks = _mark_presence(conn, _extract_operations(path))
            classification = _classify(checks)
            summary[classification] += 1
            audits.append(
                RevisionAudit(
                    revision=revision,
                    file=path.name,
                    down_revision=down_revision,
                    classification=classification,
                    checks=checks,
                )
            )
        covered_tables = {
            (check.schema, check.table)
            for audit in audits
            for check in audit.checks
        }
        watchlist: dict[str, dict[str, dict[str, bool]]] = {}
        cur = conn.cursor()
        for schema, tables in WATCHLIST_TABLES.items():
            watchlist[schema] = {}
            for table in tables:
                cur.execute("SELECT to_regclass(%s)::text", (f"{schema}.{table}",))
                exists = cur.fetchone()[0] is not None
                watchlist[schema][table] = {
                    "exists": exists,
                    "covered_by_audit": (schema, table) in covered_tables,
                }
        cur.close()
        return {
            "live_alembic_versions": live_versions,
            "local_heads": heads,
            "target_revisions": target_revisions,
            "summary": summary,
            "watchlist": watchlist,
            "audits": [
                {
                    "revision": audit.revision,
                    "file": audit.file,
                    "down_revision": audit.down_revision,
                    "classification": audit.classification,
                    "checks": [asdict(check) for check in audit.checks],
                }
                for audit in audits
            ],
        }
    finally:
        conn.close()


def _write_markdown(report: dict) -> str:
    lines = [
        "# Alembic Reconciliation Report",
        "",
        "Generated by `backend/scripts/audit_alembic_reconciliation.py`.",
        "",
        "## Live State",
        "",
        f"- Live `alembic_version`: `{', '.join(report['live_alembic_versions']) or 'none'}`",
        f"- Local heads: `{', '.join(report['local_heads'])}`",
        "",
        "## Summary",
        "",
        f"- Present revisions: {report['summary']['present']}",
        f"- Missing revisions: {report['summary']['missing']}",
        f"- Partial revisions: {report['summary']['partial']}",
        f"- No-op revisions: {report['summary']['no_op']}",
        "",
        "## Watchlist Tables",
        "",
    ]
    for schema, tables in report.get("watchlist", {}).items():
        lines.append(f"### `{schema}`")
        lines.append("")
        for table, meta in tables.items():
            lines.append(
                f"- `{schema}.{table}` -> "
                f"{'present' if meta['exists'] else 'missing'}"
                f" | covered_by_audit={meta['covered_by_audit']}"
            )
        lines.append("")
    lines.extend([
        "## Revision Audit",
        "",
    ])
    for audit in report["audits"]:
        lines.append(
            f"### `{audit['revision']}` — {audit['classification']} "
            f"(`{audit['file']}`)"
        )
        lines.append("")
        lines.append(f"- Down revision: `{audit['down_revision']}`")
        if not audit["checks"]:
            lines.append("- No structural operations detected by the lightweight parser.")
        else:
            for check in audit["checks"]:
                target = f"{check['schema']}.{check['table']}"
                if check["column"]:
                    target += f".{check['column']}"
                lines.append(
                    f"- `{check['op_type']}` `{target}` -> "
                    f"{'present' if check['present'] else 'missing'}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    report = _build_report()
    JSON_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    DOC_REPORT_PATH.write_text(_write_markdown(report))
    print(f"Wrote JSON report to {JSON_REPORT_PATH}")
    print(f"Wrote Markdown report to {DOC_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
