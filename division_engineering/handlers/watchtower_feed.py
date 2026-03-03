"""
Engineering Division — Watchtower Feed
=========================================
Generates Stream 5 (Engineering Intelligence) for the Morning Interrogation.

This handler is called by the Watchtower briefing system (src/watchtower_briefing.py)
at 06:00 daily. It scans the engineering database for:

    1. Expiring permits (within 30 days)
    2. Failed inspections awaiting re-inspection
    3. Open compliance issues (CRITICAL/HIGH)
    4. Active construction projects status
    5. MEP systems past expected lifespan
    6. Overdue maintenance alerts

Output: A structured intelligence report that R1 incorporates into
        the Morning Interrogation email.

Usage:
    from division_engineering.handlers.watchtower_feed import generate_engineering_brief

    brief = generate_engineering_brief()
    # Returns dict suitable for Watchtower integration
"""

import logging
import psycopg2
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import os

logger = logging.getLogger("division_engineering.watchtower")

PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")


def _get_conn():
    return psycopg2.connect(
        host=PG_HOST, database=PG_DB, user=PG_USER,
        password=PG_PASS, port=PG_PORT,
    )


def generate_engineering_brief() -> Dict[str, Any]:
    """
    Generate the Engineering Intelligence brief for the Watchtower.

    Returns a structured dict with sections that the Watchtower
    briefing system can render into the Morning Interrogation.
    """
    try:
        conn = _get_conn()
    except Exception as e:
        logger.error(f"Cannot connect to database for engineering brief: {e}")
        return {
            "stream": "engineering",
            "stream_name": "Stream 5 — Engineering Intelligence",
            "status": "offline",
            "error": str(e),
        }

    cur = conn.cursor()
    alerts = []
    metrics = {}

    # ── 1. EXPIRING PERMITS ──────────────────────────────────────
    try:
        cur.execute("""
            SELECT p.permit_number, p.permit_type, p.expiration_date,
                   pr.project_code, pr.property_name
            FROM engineering.permits p
            JOIN engineering.projects pr ON p.project_id = pr.id
            WHERE p.expiration_date BETWEEN CURRENT_DATE
                  AND CURRENT_DATE + INTERVAL '30 days'
                  AND p.status NOT IN ('closed', 'revoked', 'expired')
            ORDER BY p.expiration_date
        """)
        expiring = cur.fetchall()
        metrics["expiring_permits"] = len(expiring)

        for row in expiring:
            days_left = (row[2] - datetime.now(timezone.utc).date()).days
            severity = "CRITICAL" if days_left <= 7 else "HIGH"
            alerts.append({
                "type": "PERMIT_EXPIRING",
                "severity": severity,
                "message": (
                    f"{row[1]} permit {row[0] or '(no number)'} expires in "
                    f"{days_left} days — {row[4] or row[3]}"
                ),
                "days_until": days_left,
                "property": row[4],
                "project": row[3],
            })
    except Exception:
        conn.rollback()

    # ── 2. FAILED INSPECTIONS ────────────────────────────────────
    try:
        cur.execute("""
            SELECT i.inspection_type, i.actual_date, i.deficiencies,
                   pr.project_code, pr.property_name
            FROM engineering.inspections i
            JOIN engineering.projects pr ON i.project_id = pr.id
            WHERE i.result = 'failed'
                  AND i.re_inspection_date IS NULL
            ORDER BY i.actual_date DESC
        """)
        failed = cur.fetchall()
        metrics["failed_inspections"] = len(failed)

        for row in failed:
            alerts.append({
                "type": "INSPECTION_FAILED",
                "severity": "HIGH",
                "message": (
                    f"Failed {row[0]} inspection on {row[1]} — "
                    f"{row[4] or row[3]}: {(row[2] or 'No deficiency details')[:100]}"
                ),
                "property": row[4],
                "project": row[3],
            })
    except Exception:
        conn.rollback()

    # ── 3. OPEN COMPLIANCE ISSUES ────────────────────────────────
    try:
        cur.execute("""
            SELECT severity, COUNT(*) FROM engineering.compliance_log
            WHERE status = 'open'
            GROUP BY severity
            ORDER BY CASE severity
                WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3 ELSE 4 END
        """)
        compliance = dict(cur.fetchall())
        metrics["compliance_critical"] = compliance.get("CRITICAL", 0)
        metrics["compliance_high"] = compliance.get("HIGH", 0)
        metrics["compliance_total_open"] = sum(compliance.values())

        if compliance.get("CRITICAL", 0) > 0:
            alerts.append({
                "type": "COMPLIANCE_CRITICAL",
                "severity": "CRITICAL",
                "message": (
                    f"{compliance['CRITICAL']} CRITICAL code compliance "
                    f"issues open — immediate attention required"
                ),
            })
    except Exception:
        conn.rollback()

    # ── 4. ACTIVE PROJECTS ───────────────────────────────────────
    try:
        cur.execute("""
            SELECT phase, COUNT(*) FROM engineering.projects
            WHERE status = 'active'
            GROUP BY phase
        """)
        projects_by_phase = dict(cur.fetchall())
        metrics["active_projects"] = sum(projects_by_phase.values())
        metrics["projects_in_construction"] = projects_by_phase.get("construction", 0)
        metrics["projects_in_permitting"] = projects_by_phase.get("permitting", 0)

        # Behind schedule
        cur.execute("""
            SELECT project_code, name, property_name, target_completion, phase
            FROM engineering.projects
            WHERE status = 'active'
                  AND target_completion < CURRENT_DATE
            ORDER BY target_completion
        """)
        behind = cur.fetchall()
        metrics["projects_behind_schedule"] = len(behind)

        for row in behind:
            days_late = (datetime.now(timezone.utc).date() - row[3]).days
            alerts.append({
                "type": "PROJECT_BEHIND_SCHEDULE",
                "severity": "MEDIUM",
                "message": (
                    f"Project {row[0]} ({row[1]}) is {days_late} days "
                    f"behind schedule — {row[2] or 'unknown property'} "
                    f"(current phase: {row[4]})"
                ),
                "property": row[2],
                "project": row[0],
                "days_late": days_late,
            })
    except Exception:
        conn.rollback()

    # ── 5. MEP SYSTEMS PAST LIFESPAN ────────────────────────────
    try:
        cur.execute("""
            SELECT property_name, system_type, condition,
                   install_date, expected_life_years
            FROM engineering.mep_systems
            WHERE condition IN ('critical', 'poor')
               OR (install_date IS NOT NULL AND expected_life_years IS NOT NULL
                   AND install_date + (expected_life_years || ' years')::INTERVAL
                   < CURRENT_DATE)
            ORDER BY condition, install_date
        """)
        aging = cur.fetchall()
        metrics["mep_critical_systems"] = len(aging)

        for row in aging:
            alerts.append({
                "type": "MEP_SYSTEM_ALERT",
                "severity": "HIGH" if row[2] == "critical" else "MEDIUM",
                "message": (
                    f"{row[1]} at {row[0]} — condition: {row[2]}"
                    + (f", installed {row[3]}" if row[3] else "")
                ),
                "property": row[0],
                "system_type": row[1],
            })
    except Exception:
        conn.rollback()

    # ── 6. DOCUMENT STATS ────────────────────────────────────────
    try:
        cur.execute("SELECT COUNT(*) FROM engineering.drawings")
        metrics["total_drawings"] = cur.fetchone()[0]

        # CAD file breakdown
        cur.execute("""
            SELECT extension, COUNT(*) FROM engineering.drawings
            WHERE extension IN ('.dwg', '.dxf')
            GROUP BY extension
        """)
        cad_breakdown = dict(cur.fetchall())
        metrics["dwg_files"] = cad_breakdown.get(".dwg", 0)
        metrics["dxf_files"] = cad_breakdown.get(".dxf", 0)

        # Parsed vs unparsed CAD
        cur.execute("""
            SELECT COUNT(*) FROM engineering.drawings
            WHERE confidence = 'cad_parsed'
        """)
        metrics["cad_parsed"] = cur.fetchone()[0]

        # Drawings indexed in ChromaDB (cross-division availability)
        cur.execute("""
            SELECT COUNT(*) FROM engineering.drawings
            WHERE ai_json::text LIKE '%cad_reader%'
        """)
        metrics["cad_with_intelligence"] = cur.fetchone()[0]

    except Exception:
        conn.rollback()
        metrics["total_drawings"] = 0

    conn.close()

    # ── BUILD BRIEF ──────────────────────────────────────────────
    # Sort alerts by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    alerts.sort(key=lambda a: severity_order.get(a.get("severity", "LOW"), 99))

    # Determine overall threat level
    if any(a["severity"] == "CRITICAL" for a in alerts):
        threat_level = "RED"
    elif any(a["severity"] == "HIGH" for a in alerts):
        threat_level = "AMBER"
    elif alerts:
        threat_level = "YELLOW"
    else:
        threat_level = "GREEN"

    return {
        "stream": "engineering",
        "stream_name": "Stream 5 — Engineering Intelligence",
        "stream_codename": "The Drawing Board",
        "status": "operational",
        "threat_level": threat_level,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "alerts": alerts,
        "alert_count": len(alerts),
        "summary": _build_summary(metrics, alerts, threat_level),
    }


def _build_summary(
    metrics: Dict[str, Any],
    alerts: List[Dict[str, Any]],
    threat_level: str,
) -> str:
    """Build a human-readable summary for the Morning Interrogation."""
    parts = [f"Engineering Division Status: {threat_level}"]

    active = metrics.get("active_projects", 0)
    if active:
        parts.append(f"{active} active projects")
        in_construction = metrics.get("projects_in_construction", 0)
        if in_construction:
            parts.append(f"({in_construction} in construction)")

    behind = metrics.get("projects_behind_schedule", 0)
    if behind:
        parts.append(f"WARNING: {behind} projects behind schedule")

    expiring = metrics.get("expiring_permits", 0)
    if expiring:
        parts.append(f"{expiring} permits expiring within 30 days")

    failed = metrics.get("failed_inspections", 0)
    if failed:
        parts.append(f"{failed} failed inspections pending re-inspection")

    critical = metrics.get("compliance_critical", 0)
    if critical:
        parts.append(f"CRITICAL: {critical} code compliance issues open")

    mep = metrics.get("mep_critical_systems", 0)
    if mep:
        parts.append(f"{mep} MEP systems requiring attention")

    drawings = metrics.get("total_drawings", 0)
    cad_parsed = metrics.get("cad_parsed", 0)
    parts.append(f"{drawings:,} documents in engineering registry")
    if cad_parsed > 0:
        parts.append(f"{cad_parsed} CAD files parsed (cross-division)")

    return " | ".join(parts)
