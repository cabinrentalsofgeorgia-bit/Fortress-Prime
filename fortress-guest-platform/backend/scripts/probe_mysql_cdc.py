#!/usr/bin/env python3
"""
Vanguard MySQL CDC readiness probe.

Standalone, read-only operator tool for verifying whether the source MySQL
instance is prepared for binary-log-based CDC extraction.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.config import settings
from backend.services.worker_hardening import require_legacy_host_active

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def print_header(title: str) -> None:
    logger.info(f"\n{BOLD}{'=' * 50}{RESET}")
    logger.info(f"{BOLD} {title}{RESET}")
    logger.info(f"{BOLD}{'=' * 50}{RESET}")


def _existing_path(raw_path: str) -> str | None:
    candidate = (raw_path or "").strip()
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    return str(path) if path.exists() else None


def ssl_kwargs() -> dict | None:
    mode = (settings.mysql_source_ssl_mode or "PREFERRED").strip().upper()
    if mode == "DISABLED":
        return None

    ssl_config: dict[str, str] = {}
    ca_path = _existing_path(settings.mysql_source_ssl_ca_path)
    cert_path = _existing_path(settings.mysql_source_ssl_cert_path)
    key_path = _existing_path(settings.mysql_source_ssl_key_path)

    if ca_path:
        ssl_config["ca"] = ca_path
    if cert_path:
        ssl_config["cert"] = cert_path
    if key_path:
        ssl_config["key"] = key_path

    # PREFERRED and REQUIRED both enable TLS. REQUIRED should ideally be paired
    # with CA / client material, but still attempts SSL even if those paths are
    # not yet staged.
    return {"ssl": ssl_config}


def describe_tls_mode() -> None:
    mode = (settings.mysql_source_ssl_mode or "PREFERRED").strip().upper()
    logger.info(f"TLS Mode: {mode}")
    logger.info(
        "TLS CA: %s",
        _existing_path(settings.mysql_source_ssl_ca_path) or "<unset-or-missing>",
    )
    logger.info(
        "TLS Client Cert: %s",
        _existing_path(settings.mysql_source_ssl_cert_path) or "<unset-or-missing>",
    )
    logger.info(
        "TLS Client Key: %s\n",
        _existing_path(settings.mysql_source_ssl_key_path) or "<unset-or-missing>",
    )


def fetch_variable(cursor: DictCursor, name: str) -> str | None:
    cursor.execute("SHOW VARIABLES LIKE %s;", (name,))
    row = cursor.fetchone()
    if not row:
        return None
    return str(row.get("Value") or "")


def probe_master_status(cursor: DictCursor) -> tuple[bool, str]:
    statements = [
        "SHOW MASTER STATUS;",
        "SHOW BINARY LOG STATUS;",
    ]
    last_error = "unknown"
    for statement in statements:
        try:
            cursor.execute(statement)
            row = cursor.fetchone()
            if row and "File" in row:
                return True, f"Current File: {row['File']}"
            return True, "Access granted, but no active log file found."
        except pymysql.err.OperationalError as exc:
            last_error = exc.args[1] if len(exc.args) > 1 else str(exc)
    return False, last_error


def run_probe() -> None:
    print_header("VANGUARD MYSQL CDC READINESS PROBE")
    require_legacy_host_active("probe_mysql_cdc legacy source access")

    if not settings.mysql_source_host:
        logger.error(f"{RED}[FAIL]{RESET} MySQL source host not configured in settings.")
        sys.exit(1)

    logger.info(
        "Target: %s:%s | DB: %s\n",
        settings.mysql_source_host,
        settings.mysql_source_port,
        settings.mysql_source_database or "<unspecified>",
    )
    describe_tls_mode()

    try:
        connection = pymysql.connect(
            host=settings.mysql_source_host,
            port=settings.mysql_source_port,
            user=settings.mysql_source_user,
            password=settings.mysql_source_password,
            database=settings.mysql_source_database or None,
            cursorclass=DictCursor,
            connect_timeout=10,
            read_timeout=10,
            write_timeout=10,
            **(ssl_kwargs() or {}),
        )
    except Exception as exc:
        logger.error(f"{RED}[OFFLINE]{RESET} Connection failed: {exc}")
        logger.info(
            f"{YELLOW}Remediation: Verify network routes, firewall rules, "
            f"SSL mode, and credentials.{RESET}"
        )
        sys.exit(1)

    logger.info(f"{GREEN}[ONLINE]{RESET} Connection established.")

    readiness_score = 0
    max_score = 4

    try:
        with connection.cursor() as cursor:
            server_id = fetch_variable(cursor, "server_id") or "0"
            if server_id != "0":
                logger.info(f"  {GREEN}[PASS]{RESET} server_id: {server_id}")
                readiness_score += 1
            else:
                logger.warning(
                    f"  {RED}[FAIL]{RESET} server_id: {server_id} "
                    "(must be > 0 for replication)"
                )

            log_bin = (fetch_variable(cursor, "log_bin") or "OFF").upper()
            if log_bin == "ON":
                logger.info(f"  {GREEN}[PASS]{RESET} log_bin: {log_bin}")
                readiness_score += 1
            else:
                logger.warning(
                    f"  {RED}[FAIL]{RESET} log_bin: {log_bin} "
                    "(binary logging is disabled)"
                )

            binlog_format = (fetch_variable(cursor, "binlog_format") or "UNKNOWN").upper()
            if binlog_format == "ROW":
                logger.info(f"  {GREEN}[PASS]{RESET} binlog_format: {binlog_format}")
                readiness_score += 1
            else:
                logger.warning(
                    f"  {YELLOW}[DEGRADED]{RESET} binlog_format: {binlog_format} "
                    "(Debezium/CDC requires ROW)"
                )

            has_access, detail = probe_master_status(cursor)
            if has_access and "Current File:" in detail:
                logger.info(f"  {GREEN}[PASS]{RESET} Binlog Access: Granted ({detail})")
                readiness_score += 1
            elif has_access:
                logger.warning(f"  {YELLOW}[DEGRADED]{RESET} Binlog Access: {detail}")
                readiness_score += 1
            else:
                logger.error(f"  {RED}[FAIL]{RESET} Binlog Access: Denied ({detail})")
                logger.info(
                    f"    {YELLOW}Remediation: GRANT REPLICATION SLAVE, "
                    f"REPLICATION CLIENT ON *.* TO "
                    f"'{settings.mysql_source_user}'@'%';{RESET}"
                )
    finally:
        connection.close()

    print_header("PROBE SUMMARY")
    if readiness_score == max_score:
        logger.info(f"{GREEN}STATUS: CDC READY{RESET}")
        logger.info(
            "The Vanguard MySQL source meets all prerequisites for real-time "
            "binary log extraction."
        )
    elif readiness_score > 0:
        logger.info(f"{YELLOW}STATUS: DEGRADED{RESET}")
        logger.info(
            "Source is partially configured. Remediate failed checks before "
            "deploying the CDC daemon."
        )
    else:
        logger.info(f"{RED}STATUS: INCOMPATIBLE{RESET}")
        logger.info(
            "Source lacks required configuration or permissions for CDC."
        )


if __name__ == "__main__":
    run_probe()
