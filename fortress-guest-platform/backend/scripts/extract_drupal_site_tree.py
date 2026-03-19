#!/usr/bin/env python3
"""
Extract a Drupal site blueprint from a legacy MySQL SQL dump.

Targets only these tables:
  - menu_links
  - taxonomy_term_data
  - taxonomy_term_hierarchy
  - node
  - node_type
  - url_alias
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


DUMP_PATH = Path("/mnt/vol1_source/Backups/CPanel_Extracted/cabinre_legacy_migration_cut.sql")
OUTPUT_PATH = Path(__file__).resolve().parent / "drupal_granular_blueprint.json"

TARGET_TABLES = {
    "menu_links",
    "taxonomy_term_data",
    "taxonomy_term_hierarchy",
    "node",
    "node_type",
    "url_alias",
}

DEFAULT_COLUMN_ORDER = {
    # Drupal 7 default schema order
    "menu_links": [
        "menu_name",
        "mlid",
        "plid",
        "link_path",
        "router_path",
        "link_title",
        "options",
        "module",
        "hidden",
        "external",
        "has_children",
        "expanded",
        "weight",
        "depth",
        "customized",
        "p1",
        "p2",
        "p3",
        "p4",
        "p5",
        "p6",
        "p7",
        "p8",
        "p9",
        "updated",
    ],
    "taxonomy_term_data": ["tid", "vid", "name", "description", "format", "weight"],
    "taxonomy_term_hierarchy": ["tid", "parent"],
    "node": [
        "nid",
        "vid",
        "type",
        "language",
        "title",
        "uid",
        "status",
        "created",
        "changed",
        "comment",
        "promote",
        "sticky",
        "tnid",
        "translate",
    ],
    "node_type": [
        "type",
        "name",
        "module",
        "description",
        "help",
        "has_title",
        "title_label",
        "custom",
        "modified",
        "locked",
        "orig_type",
    ],
    "url_alias": ["pid", "source", "alias", "language"],
}

INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+`?(?P<table>[a-zA-Z0-9_]+)`?\s*"
    r"(?:\((?P<columns>.*?)\))?\s*VALUES\s*(?P<values>.*)\s*;\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _human_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{size_bytes} B"


def _decode_mysql_quoted(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
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
            i += 2
            continue
        out.append(ch)
        i += 1
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
        try:
            return int(token)
        except ValueError:
            return token
    if re.fullmatch(r"-?\d+\.\d+", token):
        try:
            return float(token)
        except ValueError:
            return token
    return token


def _split_tuples(values_blob: str) -> list[str]:
    tuples: list[str] = []
    in_quote = False
    escaped = False
    depth = 0
    start = None

    for i, ch in enumerate(values_blob):
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_quote = False
            continue

        if ch == "'":
            in_quote = True
            continue

        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
            continue

        if ch == ")":
            depth -= 1
            if depth == 0 and start is not None:
                tuples.append(values_blob[start + 1 : i])
                start = None
            continue

    return tuples


def _split_fields(row_blob: str) -> list[str]:
    fields: list[str] = []
    in_quote = False
    escaped = False
    start = 0

    for i, ch in enumerate(row_blob):
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_quote = False
            continue

        if ch == "'":
            in_quote = True
            continue

        if ch == ",":
            fields.append(row_blob[start:i])
            start = i + 1

    fields.append(row_blob[start:])
    return fields


def _extract_rows(values_blob: str) -> list[list[Any]]:
    out: list[list[Any]] = []
    for tup in _split_tuples(values_blob):
        fields = _split_fields(tup)
        out.append([_parse_scalar(field) for field in fields])
    return out


def _create_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS menu_links (
            menu_name TEXT,
            mlid INTEGER,
            plid INTEGER,
            link_path TEXT,
            router_path TEXT,
            link_title TEXT,
            options TEXT,
            module TEXT,
            hidden INTEGER,
            external INTEGER,
            has_children INTEGER,
            expanded INTEGER,
            weight INTEGER,
            depth INTEGER,
            customized INTEGER,
            p1 INTEGER,
            p2 INTEGER,
            p3 INTEGER,
            p4 INTEGER,
            p5 INTEGER,
            p6 INTEGER,
            p7 INTEGER,
            p8 INTEGER,
            p9 INTEGER,
            updated INTEGER
        );

        CREATE TABLE IF NOT EXISTS taxonomy_term_data (
            tid INTEGER,
            vid INTEGER,
            name TEXT,
            description TEXT,
            format TEXT,
            weight INTEGER
        );

        CREATE TABLE IF NOT EXISTS taxonomy_term_hierarchy (
            tid INTEGER,
            parent INTEGER
        );

        CREATE TABLE IF NOT EXISTS node (
            nid INTEGER,
            vid INTEGER,
            type TEXT,
            language TEXT,
            title TEXT,
            uid INTEGER,
            status INTEGER,
            created INTEGER,
            changed INTEGER,
            comment INTEGER,
            promote INTEGER,
            sticky INTEGER,
            tnid INTEGER,
            translate INTEGER
        );

        CREATE TABLE IF NOT EXISTS node_type (
            type TEXT,
            name TEXT,
            module TEXT,
            description TEXT,
            help TEXT,
            has_title INTEGER,
            title_label TEXT,
            custom INTEGER,
            modified INTEGER,
            locked INTEGER,
            orig_type TEXT
        );

        CREATE TABLE IF NOT EXISTS url_alias (
            pid INTEGER,
            source TEXT,
            alias TEXT,
            language TEXT
        );
        """
    )
    conn.commit()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _insert_rows(
    conn: sqlite3.Connection,
    table: str,
    incoming_columns: list[str] | None,
    rows: list[list[Any]],
) -> int:
    if not rows:
        return 0

    if incoming_columns is None:
        incoming_columns = DEFAULT_COLUMN_ORDER.get(table)
        if incoming_columns is None:
            return 0

    known = _table_columns(conn, table)
    usable = [c for c in incoming_columns if c in known]
    if not usable:
        return 0

    idx_map = [incoming_columns.index(c) for c in usable]
    placeholders = ", ".join("?" for _ in usable)
    col_sql = ", ".join(usable)
    sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"

    payload = []
    for row in rows:
        values = [row[i] if i < len(row) else None for i in idx_map]
        payload.append(values)

    conn.executemany(sql, payload)
    return len(payload)


def _iter_target_inserts(sql_path: Path):
    collecting = False
    statement_parts: list[str] = []
    in_quote = False
    escaped = False
    target_table: str | None = None

    with sql_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not collecting:
                m = re.match(r"\s*INSERT\s+INTO\s+`?([a-zA-Z0-9_]+)`?", line, flags=re.IGNORECASE)
                if not m:
                    continue
                table = m.group(1)
                if table not in TARGET_TABLES:
                    continue
                collecting = True
                target_table = table
                statement_parts = [line]
            else:
                statement_parts.append(line)

            for ch in line:
                if in_quote:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == "'":
                        in_quote = False
                else:
                    if ch == "'":
                        in_quote = True

            if collecting and not in_quote:
                stripped = line.strip()
                if stripped.endswith(";"):
                    yield target_table, "".join(statement_parts)
                    collecting = False
                    statement_parts = []
                    target_table = None
                    escaped = False


def _build_menus(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
    rows = conn.execute(
        """
        SELECT mlid, plid, menu_name, link_title, link_path, router_path, hidden, has_children, weight
        FROM menu_links
        ORDER BY menu_name, weight, mlid
        """
    ).fetchall()

    by_menu: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    child_map: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))

    for mlid, plid, menu_name, link_title, link_path, router_path, hidden, has_children, weight in rows:
        menu = str(menu_name or "unknown")
        node = {
            "mlid": int(mlid or 0),
            "plid": int(plid or 0),
            "title": link_title or "",
            "link_path": link_path or "",
            "router_path": router_path or "",
            "hidden": bool(hidden or 0),
            "has_children": bool(has_children or 0),
            "weight": int(weight or 0),
            "children": [],
        }
        by_menu[menu][node["mlid"]] = node
        child_map[menu][node["plid"]].append(node["mlid"])

    def build_subtree(menu: str, mlid: int) -> dict[str, Any]:
        item = by_menu[menu][mlid]
        children = sorted(
            (build_subtree(menu, child_id) for child_id in child_map[menu].get(mlid, [])),
            key=lambda c: (c["weight"], c["mlid"]),
        )
        item["children"] = children
        return item

    out: dict[str, Any] = {}
    for menu, records in by_menu.items():
        roots = []
        for mlid, item in records.items():
            plid = item["plid"]
            if plid == 0 or plid not in records:
                roots.append(build_subtree(menu, mlid))
        roots.sort(key=lambda c: (c["weight"], c["mlid"]))
        out[menu] = roots

    return out, len(rows)


def _build_taxonomy(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
    terms = conn.execute(
        """
        SELECT tid, vid, name, description, weight, format
        FROM taxonomy_term_data
        ORDER BY vid, weight, tid
        """
    ).fetchall()
    hier = conn.execute(
        """
        SELECT tid, parent
        FROM taxonomy_term_hierarchy
        ORDER BY parent, tid
        """
    ).fetchall()

    term_list = [
        {
            "tid": int(tid or 0),
            "vid": int(vid or 0),
            "name": name or "",
            "description": description or "",
            "weight": int(weight or 0),
            "format": format_,
        }
        for tid, vid, name, description, weight, format_ in terms
    ]

    hierarchy_map: dict[str, list[int]] = defaultdict(list)
    for tid, parent in hier:
        hierarchy_map[str(int(parent or 0))].append(int(tid or 0))

    return {"terms": term_list, "hierarchy_map": dict(hierarchy_map)}, len(terms)


def _build_nodes_by_type(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
    alias_rows = conn.execute(
        """
        SELECT source, alias
        FROM url_alias
        WHERE source IS NOT NULL AND alias IS NOT NULL
        ORDER BY pid
        """
    ).fetchall()
    alias_map: dict[str, str] = {}
    for source, alias in alias_rows:
        if source not in alias_map:
            alias_map[source] = alias

    node_type_rows = conn.execute(
        """
        SELECT type, name, description
        FROM node_type
        ORDER BY type
        """
    ).fetchall()
    node_type_map = {row[0]: {"label": row[1], "description": row[2]} for row in node_type_rows}

    node_rows = conn.execute(
        """
        SELECT nid, type, title, status, created, changed, uid, language
        FROM node
        ORDER BY type, nid
        """
    ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for nid, node_type, title, status, created, changed, uid, language in node_rows:
        source = f"node/{int(nid or 0)}"
        grouped[str(node_type or "unknown")].append(
            {
                "nid": int(nid or 0),
                "title": title or "",
                "status": int(status or 0),
                "created": int(created or 0),
                "changed": int(changed or 0),
                "uid": int(uid or 0),
                "language": language,
                "source_path": source,
                "url_alias": alias_map.get(source),
            }
        )

    out = {}
    for node_type, items in grouped.items():
        out[node_type] = {
            "type_info": node_type_map.get(node_type, {"label": None, "description": None}),
            "nodes": items,
        }

    return out, len(node_rows)


def main() -> None:
    if not DUMP_PATH.exists():
        raise FileNotFoundError(f"SQL dump not found: {DUMP_PATH}")

    conn = sqlite3.connect(":memory:")
    _create_sqlite_schema(conn)

    inserted_counts = defaultdict(int)
    seen_insert_statements = 0

    for table, statement in _iter_target_inserts(DUMP_PATH):
        seen_insert_statements += 1
        m = INSERT_RE.match(statement.strip())
        if not m:
            continue

        columns_blob = m.group("columns")
        values_blob = m.group("values")
        incoming_columns = None
        if columns_blob:
            incoming_columns = [c.strip().strip("`") for c in columns_blob.split(",")]

        rows = _extract_rows(values_blob)
        inserted = _insert_rows(conn, table, incoming_columns, rows)
        inserted_counts[table] += inserted

    menus, menu_rows = _build_menus(conn)
    taxonomy, taxonomy_term_rows = _build_taxonomy(conn)
    nodes_by_type, exported_nodes = _build_nodes_by_type(conn)

    output_payload = {
        "source_dump": str(DUMP_PATH),
        "insert_statements_processed": seen_insert_statements,
        "inserted_row_counts": dict(inserted_counts),
        "menus": menus,
        "taxonomy": taxonomy,
        "nodes_by_type": nodes_by_type,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    size_text = _human_size(OUTPUT_PATH.stat().st_size)
    print("Drupal granular blueprint extraction complete.")
    print(f"Output file: {OUTPUT_PATH}")
    print(f"File size: {size_text}")
    print(
        "Row counts: "
        f"menus={menu_rows}, taxonomy_terms={taxonomy_term_rows}, exported_nodes={exported_nodes}"
    )


if __name__ == "__main__":
    main()

