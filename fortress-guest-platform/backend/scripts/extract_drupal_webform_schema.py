#!/usr/bin/env python3
"""
Extract Drupal webform schema directly from the legacy data source and backfill
the FunctionalNode ledger.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import select


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]
DUMP_PATH = Path("/mnt/vol1_source/Backups/CPanel_Extracted/cabinre_legacy_migration_cut.sql")

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def load_environment() -> list[Path]:
    loaded_files: list[Path] = []
    for env_file in (
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
    ):
        if env_file.exists():
            load_dotenv(env_file, override=True)
            loaded_files.append(env_file)
    return loaded_files


LOADED_ENV_FILES = load_environment()

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal, close_db
from backend.models.functional_node import FunctionalNode
from backend.services.worker_hardening import require_legacy_host_active


WEBFORM_COLUMNS = [
    "nid",
    "confirmation",
    "confirmation_format",
    "redirect_url",
    "status",
    "block",
    "allow_draft",
    "auto_save",
    "submit_notice",
    "submit_text",
    "submit_limit",
    "submit_interval",
    "total_submit_limit",
    "total_submit_interval",
    "progressbar_bar",
    "progressbar_page_number",
    "progressbar_percent",
    "progressbar_pagebreak_labels",
    "progressbar_include_confirmation",
    "progressbar_label_first",
    "progressbar_label_confirmation",
    "preview",
    "preview_next_button_label",
    "preview_prev_button_label",
    "preview_title",
    "preview_message",
    "preview_message_format",
    "preview_excluded_components",
    "next_serial",
    "confidential",
]

WEBFORM_COMPONENT_COLUMNS = [
    "nid",
    "cid",
    "pid",
    "form_key",
    "name",
    "type",
    "value",
    "extra",
    "required",
    "weight",
]

WEBFORM_EMAIL_COLUMNS = [
    "nid",
    "eid",
    "email",
    "subject",
    "from_name",
    "from_address",
    "template",
    "excluded_components",
    "html",
    "attachments",
    "extra",
    "exclude_empty",
    "status",
]

WEBFORM_CONDITIONAL_COLUMNS = ["nid", "rgid", "andor", "weight"]
WEBFORM_CONDITIONAL_RULE_COLUMNS = ["nid", "rgid", "rid", "source_type", "source", "operator", "value"]
WEBFORM_CONDITIONAL_ACTION_COLUMNS = ["nid", "rgid", "aid", "target_type", "target", "invert", "action", "argument"]

TABLE_COLUMN_MAP = {
    "webform": WEBFORM_COLUMNS,
    "webform_component": WEBFORM_COMPONENT_COLUMNS,
    "webform_emails": WEBFORM_EMAIL_COLUMNS,
    "webform_conditional": WEBFORM_CONDITIONAL_COLUMNS,
    "webform_conditional_rules": WEBFORM_CONDITIONAL_RULE_COLUMNS,
    "webform_conditional_actions": WEBFORM_CONDITIONAL_ACTION_COLUMNS,
}


@dataclass
class WebformSchema:
    source_mode: str
    webform: dict[str, Any]
    components: list[dict[str, Any]]
    notifications: list[dict[str, Any]]
    conditionals: list[dict[str, Any]]


class PHPUnserializeError(ValueError):
    pass


class PHPUnserializer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def parse(self) -> Any:
        value = self._parse_value()
        return value

    def _read_until(self, delimiter: str) -> str:
        end = self.text.find(delimiter, self.index)
        if end == -1:
            raise PHPUnserializeError("Unexpected end of serialized payload")
        value = self.text[self.index : end]
        self.index = end + len(delimiter)
        return value

    def _expect(self, token: str) -> None:
        if not self.text.startswith(token, self.index):
            raise PHPUnserializeError(f"Expected {token!r} at offset {self.index}")
        self.index += len(token)

    def _parse_value(self) -> Any:
        if self.index >= len(self.text):
            raise PHPUnserializeError("Unexpected end of serialized payload")
        tag = self.text[self.index]
        self.index += 2  # skip "<tag>:"
        if tag == "N":
            self.index -= 1
            self._expect(";")
            return None
        if tag == "b":
            raw = self._read_until(";")
            return raw == "1"
        if tag == "i":
            return int(self._read_until(";"))
        if tag == "d":
            return float(self._read_until(";"))
        if tag == "s":
            length = int(self._read_until(":"))
            self._expect('"')
            value = self.text[self.index : self.index + length]
            self.index += length
            self._expect('";')
            return value
        if tag == "a":
            size = int(self._read_until(":"))
            self._expect("{")
            items: list[tuple[Any, Any]] = []
            for _ in range(size):
                key = self._parse_value()
                value = self._parse_value()
                items.append((key, value))
            self._expect("}")
            if all(isinstance(key, int) for key, _ in items):
                numeric_keys = [int(key) for key, _ in items]
                if numeric_keys == list(range(len(items))):
                    return [value for _, value in items]
            return {key: value for key, value in items}
        raise PHPUnserializeError(f"Unsupported serialized tag {tag!r}")


def _maybe_unserialize(raw: str) -> Any:
    candidate = raw.strip()
    if not candidate:
        return {}
    if not re.match(r"^[abisdN]:", candidate):
        return candidate
    try:
        return PHPUnserializer(candidate).parse()
    except Exception:
        return candidate


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _decode_mysql_quoted(value: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            nxt = value[index + 1]
            mapping = {
                "0": "\0",
                "b": "\b",
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "Z": "\x1a",
                "'": "'",
                '"': '"',
                "\\": "\\",
            }
            out.append(mapping.get(nxt, nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _parse_scalar(raw: str) -> Any:
    token = raw.strip()
    if not token:
        return None
    if token.upper() == "NULL":
        return None
    binary_match = re.match(r"(?is)^_binary\s+'(.*)'$", token)
    if binary_match:
        return _decode_mysql_quoted(binary_match.group(1))
    if token.startswith("'") and token.endswith("'"):
        return _decode_mysql_quoted(token[1:-1])
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    return token


def _split_tuples(values_blob: str) -> list[str]:
    tuples: list[str] = []
    in_quote = False
    escaped = False
    depth = 0
    start: int | None = None
    for index, char in enumerate(values_blob):
        if in_quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_quote = False
            continue
        if char == "'":
            in_quote = True
            continue
        if char == "(":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0 and start is not None:
                tuples.append(values_blob[start + 1 : index])
                start = None
    return tuples


def _split_fields(row_blob: str) -> list[str]:
    fields: list[str] = []
    in_quote = False
    escaped = False
    start = 0
    for index, char in enumerate(row_blob):
        if in_quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_quote = False
            continue
        if char == "'":
            in_quote = True
            continue
        if char == ",":
            fields.append(row_blob[start:index])
            start = index + 1
    fields.append(row_blob[start:])
    return fields


def _extract_insert_blob(sql_text: str, table_name: str) -> str:
    prefix = f"INSERT INTO `{table_name}` VALUES "
    collecting = False
    chunks: list[str] = []
    for line in sql_text.splitlines():
        if not collecting:
            if line.startswith(prefix):
                collecting = True
                chunks.append(line[len(prefix) :])
                if line.rstrip().endswith(";"):
                    break
            continue
        chunks.append(line)
        if line.rstrip().endswith(";"):
            break
    if not chunks:
        return ""
    statement = "\n".join(chunks).strip()
    if statement.endswith(";"):
        statement = statement[:-1]
    return statement


def _load_rows_from_dump(sql_text: str, table_name: str, expected_nid: int) -> list[dict[str, Any]]:
    blob = _extract_insert_blob(sql_text, table_name)
    if not blob:
        return []
    columns = TABLE_COLUMN_MAP[table_name]
    rows: list[dict[str, Any]] = []
    for tuple_blob in _split_tuples(blob):
        parsed = [_parse_scalar(field) for field in _split_fields(tuple_blob)]
        if len(parsed) != len(columns):
            continue
        row = dict(zip(columns, parsed))
        if int(row.get("nid") or 0) != expected_nid:
            continue
        rows.append(row)
    return rows


def _component_id_map(components: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(component["cid"]): component for component in components}


def _resolve_component_reference(raw_value: object, component_map: dict[int, dict[str, Any]]) -> dict[str, Any]:
    text = _normalize_text(raw_value)
    if re.fullmatch(r"\d+", text):
        cid = int(text)
        component = component_map.get(cid)
        if component is not None:
            return {
                "mode": "component",
                "cid": cid,
                "form_key": component.get("form_key"),
                "label": component.get("label"),
            }
    return {"mode": "literal", "value": text}


def _parse_component(row: dict[str, Any]) -> dict[str, Any]:
    extra = _maybe_unserialize(_normalize_text(row.get("extra")))
    extra_payload = extra if isinstance(extra, dict) else {}
    return {
        "cid": int(row["cid"]),
        "pid": int(row["pid"]),
        "form_key": _normalize_text(row.get("form_key")),
        "label": _normalize_text(row.get("name")),
        "type": _normalize_text(row.get("type")),
        "default_value": row.get("value"),
        "required": bool(int(row.get("required") or 0)),
        "weight": int(row.get("weight") or 0),
        "validation": {
            "maxlength": _normalize_text(extra_payload.get("maxlength")),
            "minlength": _normalize_text(extra_payload.get("minlength")),
            "unique": bool(extra_payload.get("unique")) if "unique" in extra_payload else False,
            "format": _normalize_text(extra_payload.get("format")),
            "multiple": bool(extra_payload.get("multiple")) if "multiple" in extra_payload else False,
            "disabled": bool(extra_payload.get("disabled")) if "disabled" in extra_payload else False,
        },
        "presentation": {
            "placeholder": _normalize_text(extra_payload.get("placeholder")),
            "description": _normalize_text(extra_payload.get("description")),
            "title_display": _normalize_text(extra_payload.get("title_display")),
            "css_classes": _normalize_text(extra_payload.get("css_classes")),
            "wrapper_classes": _normalize_text(extra_payload.get("wrapper_classes")),
            "rows": _normalize_text(extra_payload.get("rows")),
        },
        "raw_extra": extra_payload,
    }


def _parse_notification(row: dict[str, Any], component_map: dict[int, dict[str, Any]]) -> dict[str, Any]:
    extra = _maybe_unserialize(_normalize_text(row.get("extra")))
    excluded = [
        int(value)
        for value in _normalize_text(row.get("excluded_components")).split(",")
        if re.fullmatch(r"\d+", value.strip())
    ]
    return {
        "eid": int(row["eid"]),
        "status": bool(int(row.get("status") or 0)),
        "to": _resolve_component_reference(row.get("email"), component_map),
        "subject": _resolve_component_reference(row.get("subject"), component_map),
        "from_name": _resolve_component_reference(row.get("from_name"), component_map),
        "from_address": _resolve_component_reference(row.get("from_address"), component_map),
        "template": _normalize_text(row.get("template")),
        "excluded_components": excluded,
        "html": bool(int(row.get("html") or 0)),
        "attachments": bool(int(row.get("attachments") or 0)),
        "exclude_empty": bool(int(row.get("exclude_empty") or 0)),
        "raw_extra": extra if isinstance(extra, dict) else extra,
    }


def _parse_conditionals(
    conditional_rows: list[dict[str, Any]],
    rule_rows: list[dict[str, Any]],
    action_rows: list[dict[str, Any]],
    component_map: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped_rules: dict[tuple[int, int], list[dict[str, Any]]] = {}
    grouped_actions: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rule_rows:
        key = (int(row["nid"]), int(row["rgid"]))
        grouped_rules.setdefault(key, []).append(row)
    for row in action_rows:
        key = (int(row["nid"]), int(row["rgid"]))
        grouped_actions.setdefault(key, []).append(row)

    parsed: list[dict[str, Any]] = []
    for row in conditional_rows:
        key = (int(row["nid"]), int(row["rgid"]))
        rules = []
        for rule in grouped_rules.get(key, []):
            source_component = component_map.get(int(rule["source"]))
            rules.append(
                {
                    "source_cid": int(rule["source"]),
                    "source_form_key": source_component.get("form_key") if source_component else None,
                    "source_label": source_component.get("label") if source_component else None,
                    "operator": _normalize_text(rule.get("operator")),
                    "value": rule.get("value"),
                }
            )
        actions = []
        for action in grouped_actions.get(key, []):
            target_component = component_map.get(int(action["target"])) if re.fullmatch(r"\d+", _normalize_text(action.get("target"))) else None
            actions.append(
                {
                    "target_type": _normalize_text(action.get("target_type")),
                    "target": action.get("target"),
                    "target_form_key": target_component.get("form_key") if target_component else None,
                    "target_label": target_component.get("label") if target_component else None,
                    "invert": bool(int(action.get("invert") or 0)),
                    "action": _normalize_text(action.get("action")),
                    "argument": action.get("argument"),
                }
            )
        parsed.append(
            {
                "rgid": int(row["rgid"]),
                "andor": _normalize_text(row.get("andor")),
                "weight": int(row.get("weight") or 0),
                "rules": rules,
                "actions": actions,
            }
        )
    return parsed


def _parse_webform(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "nid": int(row["nid"]),
        "status": bool(int(row.get("status") or 0)),
        "confirmation_html": _normalize_text(row.get("confirmation")),
        "confirmation_format": _normalize_text(row.get("confirmation_format")),
        "redirect_url": _normalize_text(row.get("redirect_url")),
        "submit_text": _normalize_text(row.get("submit_text")),
        "submit_limit": int(row.get("submit_limit") or -1),
        "submit_interval_seconds": int(row.get("submit_interval") or -1),
        "total_submit_limit": int(row.get("total_submit_limit") or -1),
        "total_submit_interval_seconds": int(row.get("total_submit_interval") or -1),
        "preview_enabled": bool(int(row.get("preview") or 0)),
        "preview_title": _normalize_text(row.get("preview_title")),
        "next_serial": int(row.get("next_serial") or 0),
        "confidential": bool(int(row.get("confidential") or 0)),
        "allow_draft": bool(int(row.get("allow_draft") or 0)),
        "auto_save": bool(int(row.get("auto_save") or 0)),
        "submit_notice": bool(int(row.get("submit_notice") or 0)),
        "submit_limit_policy": {
            "submit_limit": int(row.get("submit_limit") or -1),
            "submit_interval_seconds": int(row.get("submit_interval") or -1),
        },
    }


def _load_from_dump(node_id: int, dump_path: Path) -> WebformSchema:
    sql_text = dump_path.read_text(encoding="utf-8", errors="replace")
    webform_rows = _load_rows_from_dump(sql_text, "webform", node_id)
    component_rows = _load_rows_from_dump(sql_text, "webform_component", node_id)
    email_rows = _load_rows_from_dump(sql_text, "webform_emails", node_id)
    conditional_rows = _load_rows_from_dump(sql_text, "webform_conditional", node_id)
    rule_rows = _load_rows_from_dump(sql_text, "webform_conditional_rules", node_id)
    action_rows = _load_rows_from_dump(sql_text, "webform_conditional_actions", node_id)
    if not webform_rows:
        raise RuntimeError(f"No Drupal webform row found for node {node_id} in dump {dump_path}")

    components = sorted((_parse_component(row) for row in component_rows), key=lambda item: (item["weight"], item["cid"]))
    component_map = _component_id_map(components)
    notifications = [_parse_notification(row, component_map) for row in email_rows]
    conditionals = _parse_conditionals(conditional_rows, rule_rows, action_rows, component_map)
    return WebformSchema(
        source_mode="sql_dump",
        webform=_parse_webform(webform_rows[0]),
        components=components,
        notifications=notifications,
        conditionals=conditionals,
    )


def _load_from_mysql(node_id: int) -> WebformSchema:
    import pymysql
    from pymysql.cursors import DictCursor

    connection = pymysql.connect(
        host=settings.mysql_source_host,
        port=settings.mysql_source_port,
        user=settings.mysql_source_user,
        password=settings.mysql_source_password,
        database=settings.mysql_source_database or None,
        cursorclass=DictCursor,
        connect_timeout=10,
        read_timeout=20,
        write_timeout=20,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM webform WHERE nid = %s", (node_id,))
            webform_row = cursor.fetchone()
            cursor.execute("SELECT * FROM webform_component WHERE nid = %s ORDER BY weight ASC, cid ASC", (node_id,))
            component_rows = cursor.fetchall()
            cursor.execute("SELECT * FROM webform_emails WHERE nid = %s ORDER BY eid ASC", (node_id,))
            email_rows = cursor.fetchall()
            cursor.execute("SELECT * FROM webform_conditional WHERE nid = %s ORDER BY weight ASC, rgid ASC", (node_id,))
            conditional_rows = cursor.fetchall()
            cursor.execute("SELECT * FROM webform_conditional_rules WHERE nid = %s ORDER BY rgid ASC, rid ASC", (node_id,))
            rule_rows = cursor.fetchall()
            cursor.execute("SELECT * FROM webform_conditional_actions WHERE nid = %s ORDER BY rgid ASC, aid ASC", (node_id,))
            action_rows = cursor.fetchall()
    finally:
        connection.close()

    if not webform_row:
        raise RuntimeError(f"No Drupal webform row found for node {node_id} in MySQL source")

    components = sorted((_parse_component(row) for row in component_rows), key=lambda item: (item["weight"], item["cid"]))
    component_map = _component_id_map(components)
    notifications = [_parse_notification(row, component_map) for row in email_rows]
    conditionals = _parse_conditionals(conditional_rows, rule_rows, action_rows, component_map)
    return WebformSchema(
        source_mode="mysql_live",
        webform=_parse_webform(webform_row),
        components=components,
        notifications=notifications,
        conditionals=conditionals,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Drupal webform component and notification schema into the functional node ledger.",
    )
    parser.add_argument("--node-id", type=int, default=2719)
    parser.add_argument("--dump-path", type=Path, default=DUMP_PATH)
    parser.add_argument(
        "--source-mode",
        choices=("auto", "mysql", "dump"),
        default="auto",
        help="Prefer live MySQL when credentials are configured, otherwise fall back to the local SQL dump.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def _run() -> int:
    args = _parse_args()
    node_id = int(args.node_id)
    dump_path = Path(args.dump_path).expanduser().resolve()

    mysql_configured = all(
        [
            _normalize_text(settings.mysql_source_host),
            _normalize_text(settings.mysql_source_user),
            _normalize_text(settings.mysql_source_password),
        ]
    )

    if args.source_mode == "mysql":
        schema = _load_from_mysql(node_id)
    elif args.source_mode == "dump":
        schema = _load_from_dump(node_id, dump_path)
    else:
        if mysql_configured:
            try:
                schema = _load_from_mysql(node_id)
            except Exception:
                schema = _load_from_dump(node_id, dump_path)
        else:
            schema = _load_from_dump(node_id, dump_path)

    field_manifest = [
        {
            "cid": component["cid"],
            "form_key": component["form_key"],
            "label": component["label"],
            "type": component["type"],
            "required": component["required"],
            "weight": component["weight"],
        }
        for component in schema.components
        if component["type"] != "markup"
    ]

    print("[drupal-webform-extractor] schema manifest")
    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"source_mode={schema.source_mode}")
    print(f"node_id={node_id}")
    print(f"component_count={len(schema.components)}")
    print(f"notification_count={len(schema.notifications)}")
    print(f"conditional_group_count={len(schema.conditionals)}")
    print("field_manifest=" + json.dumps(field_manifest, ensure_ascii=True))
    print("notifications=" + json.dumps(schema.notifications, ensure_ascii=True))
    print("webform=" + json.dumps(schema.webform, ensure_ascii=True))

    async with AsyncSessionLocal() as session:
        node = (
            await session.execute(
                select(FunctionalNode).where(
                    (FunctionalNode.legacy_node_id == node_id)
                    | (FunctionalNode.source_path == f"node/{node_id}")
                )
            )
        ).scalars().first()
        if node is None:
            raise RuntimeError(f"FunctionalNode ledger row not found for Drupal node {node_id}")

        source_metadata = dict(node.source_metadata or {})
        source_metadata["webform_schema"] = {
            "source_mode": schema.source_mode,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        node.form_fields = {
            "source_mode": schema.source_mode,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "webform": schema.webform,
            "components": schema.components,
            "field_manifest": field_manifest,
            "notifications": schema.notifications,
            "conditionals": schema.conditionals,
        }
        node.source_metadata = source_metadata
        node.crawl_status = "schema_extracted"
        node.mirror_status = "ready_for_blueprint"
        node.updated_at = datetime.now(timezone.utc)

        if args.dry_run:
            await session.rollback()
            print("[dry-run] ledger update prepared")
        else:
            await session.commit()
            print("[ok] ledger updated")
    return 0


async def amain() -> int:
    try:
        require_legacy_host_active("extract_drupal_webform_schema legacy source access")
        return await _run()
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
