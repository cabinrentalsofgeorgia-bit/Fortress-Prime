"""
Engineering Project Tracker — Lifecycle Management
=====================================================
Tracks construction projects from concept through Certificate of Occupancy
to closeout. Every project is a state machine that flows through phases:

    Concept → Schematic Design → Design Development → Construction Documents
    → Permitting → Bidding → Construction → Punch List → Inspection
    → Certificate of Occupancy → Closeout

Each phase transition triggers:
    1. Status update in PostgreSQL
    2. Compliance verification for required deliverables
    3. Cost tracking update
    4. Sovereign notification (if milestone or anomaly)

Usage:
    from division_engineering.project_tracker import ProjectTracker

    tracker = ProjectTracker()
    tracker.create_project("PRJ-2026-001", "Buckhorn Deck Rebuild", ...)
    tracker.advance_phase("PRJ-2026-001", "permitting")
    tracker.get_project_status("PRJ-2026-001")
    tracker.get_all_active()
"""

import json
import logging
import psycopg2
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("division_engineering.project_tracker")

PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")


# Valid phase transitions (directed graph)
PHASE_ORDER = [
    "concept",
    "schematic",
    "dd",
    "cd",
    "permitting",
    "bidding",
    "construction",
    "punch_list",
    "inspection",
    "co",
    "closeout",
]

# Phases that can be entered from any phase
SPECIAL_PHASES = {"on_hold", "cancelled"}

# Required deliverables per phase (checked before advancing)
PHASE_REQUIREMENTS = {
    "permitting": {
        "description": "Construction Documents phase must produce permit-ready drawings",
        "checks": ["drawings_exist", "disciplines_covered"],
    },
    "bidding": {
        "description": "Permits must be approved before soliciting bids",
        "checks": ["permits_approved"],
    },
    "construction": {
        "description": "Must have approved permits and selected contractor",
        "checks": ["permits_approved", "contractor_assigned"],
    },
    "inspection": {
        "description": "Punch list items must be addressed before final inspection",
        "checks": ["punch_items_resolved"],
    },
    "co": {
        "description": "All inspections must pass before Certificate of Occupancy",
        "checks": ["inspections_passed"],
    },
    "closeout": {
        "description": "CO must be issued before closeout",
        "checks": ["co_issued"],
    },
}


class ProjectTracker:
    """
    Construction project lifecycle manager.

    Enforces phase transitions, validates deliverables,
    and tracks costs/schedule for the Sovereign reporting.
    """

    def __init__(self):
        self._conn = None

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                host=PG_HOST, database=PG_DB, user=PG_USER,
                password=PG_PASS, port=PG_PORT,
            )
        return self._conn

    def create_project(
        self,
        project_code: str,
        name: str,
        property_name: Optional[str] = None,
        project_type: str = "renovation",
        disciplines: Optional[List[str]] = None,
        estimated_cost: Optional[float] = None,
        target_completion: Optional[str] = None,
        architect_of_record: Optional[str] = None,
        engineer_of_record: Optional[str] = None,
        general_contractor: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new construction project.

        Returns:
            Project record dict.
        """
        cur = self.conn.cursor()

        # Look up property_id
        property_id = None
        if property_name:
            cur.execute(
                "SELECT id FROM properties WHERE name = %s", (property_name,)
            )
            row = cur.fetchone()
            if row:
                property_id = row[0]

        cur.execute("""
            INSERT INTO engineering.projects
            (project_code, name, description, property_id, property_name,
             phase, status, project_type, disciplines, estimated_cost,
             target_completion, architect_of_record, engineer_of_record,
             general_contractor, start_date)
            VALUES (%s, %s, %s, %s, %s,
                    'concept', 'active', %s, %s, %s,
                    %s, %s, %s, %s, CURRENT_DATE)
            ON CONFLICT (project_code) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description
            RETURNING id, project_code, name, phase, status
        """, (
            project_code, name, description, property_id, property_name,
            project_type, disciplines, estimated_cost,
            target_completion, architect_of_record,
            engineer_of_record, general_contractor,
        ))

        row = cur.fetchone()
        self.conn.commit()

        result = {
            "id": row[0],
            "project_code": row[1],
            "name": row[2],
            "phase": row[3],
            "status": row[4],
            "property_name": property_name,
            "project_type": project_type,
        }

        logger.info(f"Project created: {project_code} — {name} ({project_type})")
        return result

    def advance_phase(
        self,
        project_code: str,
        target_phase: str,
        force: bool = False,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Advance a project to the next phase.

        Validates:
            1. Phase transition is valid (follows order or special)
            2. Required deliverables for new phase are met (unless forced)

        Returns:
            Updated project record with any warnings.
        """
        cur = self.conn.cursor()

        # Get current project state
        cur.execute("""
            SELECT id, project_code, name, phase, status, property_name
            FROM engineering.projects
            WHERE project_code = %s
        """, (project_code,))
        row = cur.fetchone()

        if not row:
            return {"error": f"Project {project_code} not found"}

        proj_id, code, name, current_phase, status, prop_name = row

        if status in ("completed", "cancelled"):
            return {"error": f"Project {code} is {status} — cannot advance"}

        # Validate transition
        warnings = []
        if target_phase not in SPECIAL_PHASES:
            if target_phase in PHASE_ORDER and current_phase in PHASE_ORDER:
                current_idx = PHASE_ORDER.index(current_phase)
                target_idx = PHASE_ORDER.index(target_phase)
                if target_idx != current_idx + 1 and not force:
                    return {
                        "error": (
                            f"Invalid transition: {current_phase} → {target_phase}. "
                            f"Expected next phase: {PHASE_ORDER[current_idx + 1]}. "
                            f"Use force=True to override."
                        )
                    }
                if target_idx > current_idx + 1:
                    warnings.append(
                        f"Skipping phases: {current_phase} → {target_phase}"
                    )

        # Check requirements (unless forced)
        if target_phase in PHASE_REQUIREMENTS and not force:
            req = PHASE_REQUIREMENTS[target_phase]
            unmet = self._check_requirements(proj_id, req["checks"], cur)
            if unmet:
                return {
                    "error": f"Requirements not met for {target_phase}: {', '.join(unmet)}",
                    "description": req["description"],
                    "unmet_requirements": unmet,
                    "hint": "Use force=True to override",
                }

        # Update phase
        new_status = "active"
        if target_phase == "closeout":
            new_status = "completed"
        elif target_phase in ("on_hold", "cancelled"):
            new_status = target_phase

        actual_completion = None
        if target_phase == "co":
            actual_completion = datetime.now(timezone.utc).date()

        cur.execute("""
            UPDATE engineering.projects SET
                phase = %s,
                status = %s,
                actual_completion = COALESCE(%s, actual_completion),
                notes = COALESCE(%s, notes),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING phase, status
        """, (
            target_phase, new_status, actual_completion, notes, proj_id,
        ))

        new_phase, new_status = cur.fetchone()
        self.conn.commit()

        logger.info(
            f"Project {code} advanced: {current_phase} → {new_phase} "
            f"(status: {new_status})"
        )

        return {
            "project_code": code,
            "name": name,
            "previous_phase": current_phase,
            "current_phase": new_phase,
            "status": new_status,
            "property_name": prop_name,
            "warnings": warnings,
        }

    def get_project_status(self, project_code: str) -> Dict[str, Any]:
        """Get full status of a project including related records."""
        cur = self.conn.cursor()

        cur.execute("""
            SELECT id, project_code, name, description, property_name,
                   phase, status, project_type, disciplines,
                   start_date, target_completion, actual_completion,
                   estimated_cost, actual_cost,
                   architect_of_record, engineer_of_record,
                   general_contractor, jurisdiction, permit_number
            FROM engineering.projects
            WHERE project_code = %s
        """, (project_code,))
        row = cur.fetchone()

        if not row:
            return {"error": f"Project {project_code} not found"}

        proj_id = row[0]

        # Count related records
        counts = {}
        for table, label in [
            ("drawings", "drawings"),
            ("permits", "permits"),
            ("inspections", "inspections"),
            ("change_orders", "change_orders"),
            ("rfis", "rfis"),
            ("submittals", "submittals"),
            ("punch_items", "punch_items"),
        ]:
            try:
                cur.execute(
                    f"SELECT COUNT(*) FROM engineering.{table} WHERE project_id = %s",
                    (proj_id,),
                )
                counts[label] = cur.fetchone()[0]
            except Exception:
                self.conn.rollback()
                counts[label] = 0

        # Get open compliance issues
        try:
            cur.execute("""
                SELECT COUNT(*) FROM engineering.compliance_log
                WHERE project_id = %s AND status = 'open'
            """, (proj_id,))
            counts["open_compliance_issues"] = cur.fetchone()[0]
        except Exception:
            self.conn.rollback()
            counts["open_compliance_issues"] = 0

        return {
            "id": row[0],
            "project_code": row[1],
            "name": row[2],
            "description": row[3],
            "property_name": row[4],
            "phase": row[5],
            "status": row[6],
            "project_type": row[7],
            "disciplines": row[8],
            "start_date": str(row[9]) if row[9] else None,
            "target_completion": str(row[10]) if row[10] else None,
            "actual_completion": str(row[11]) if row[11] else None,
            "estimated_cost": float(row[12]) if row[12] else None,
            "actual_cost": float(row[13]) if row[13] else None,
            "architect_of_record": row[14],
            "engineer_of_record": row[15],
            "general_contractor": row[16],
            "jurisdiction": row[17],
            "permit_number": row[18],
            "related_counts": counts,
            "phase_index": (
                PHASE_ORDER.index(row[5]) if row[5] in PHASE_ORDER else -1
            ),
            "total_phases": len(PHASE_ORDER),
        }

    def get_all_active(self) -> List[Dict[str, Any]]:
        """Get all active projects with summary info."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT project_code, name, property_name, phase, status,
                   project_type, estimated_cost, target_completion
            FROM engineering.projects
            WHERE status = 'active'
            ORDER BY
                CASE phase
                    WHEN 'construction' THEN 1
                    WHEN 'permitting' THEN 2
                    WHEN 'inspection' THEN 3
                    WHEN 'punch_list' THEN 4
                    WHEN 'cd' THEN 5
                    WHEN 'dd' THEN 6
                    WHEN 'bidding' THEN 7
                    WHEN 'schematic' THEN 8
                    WHEN 'concept' THEN 9
                    ELSE 10
                END
        """)

        projects = []
        for row in cur.fetchall():
            # Check if behind schedule
            behind = False
            if row[7]:  # target_completion
                if datetime.now(timezone.utc).date() > row[7]:
                    behind = True

            projects.append({
                "project_code": row[0],
                "name": row[1],
                "property_name": row[2],
                "phase": row[3],
                "status": row[4],
                "project_type": row[5],
                "estimated_cost": float(row[6]) if row[6] else None,
                "target_completion": str(row[7]) if row[7] else None,
                "behind_schedule": behind,
            })

        return projects

    def get_permits_expiring_soon(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get permits expiring within the specified number of days."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT p.permit_number, p.permit_type, p.status,
                   p.expiration_date, p.jurisdiction,
                   pr.project_code, pr.name as project_name,
                   pr.property_name
            FROM engineering.permits p
            JOIN engineering.projects pr ON p.project_id = pr.id
            WHERE p.expiration_date BETWEEN CURRENT_DATE
                  AND CURRENT_DATE + INTERVAL '%s days'
                  AND p.status NOT IN ('closed', 'revoked', 'expired')
            ORDER BY p.expiration_date
        """, (days,))

        return [
            {
                "permit_number": row[0],
                "permit_type": row[1],
                "status": row[2],
                "expiration_date": str(row[3]),
                "jurisdiction": row[4],
                "project_code": row[5],
                "project_name": row[6],
                "property_name": row[7],
                "days_until_expiry": (row[3] - datetime.now(timezone.utc).date()).days,
                "severity": "CRITICAL" if (row[3] - datetime.now(timezone.utc).date()).days <= 7 else "HIGH",
            }
            for row in cur.fetchall()
        ]

    def get_failed_inspections(self) -> List[Dict[str, Any]]:
        """Get all failed inspections requiring re-inspection."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT i.id, i.inspection_type, i.discipline, i.actual_date,
                   i.result, i.deficiencies, i.corrections_required,
                   pr.project_code, pr.name as project_name,
                   pr.property_name
            FROM engineering.inspections i
            JOIN engineering.projects pr ON i.project_id = pr.id
            WHERE i.result = 'failed' AND i.re_inspection_date IS NULL
            ORDER BY i.actual_date DESC
        """)

        return [
            {
                "inspection_id": row[0],
                "inspection_type": row[1],
                "discipline": row[2],
                "failed_date": str(row[3]) if row[3] else None,
                "deficiencies": row[5],
                "corrections_required": row[6],
                "project_code": row[7],
                "project_name": row[8],
                "property_name": row[9],
            }
            for row in cur.fetchall()
        ]

    # =========================================================================
    # REQUIREMENT CHECKS
    # =========================================================================

    def _check_requirements(
        self, project_id: int, checks: List[str], cur
    ) -> List[str]:
        """Check phase advancement requirements. Returns list of unmet checks."""
        unmet = []

        for check in checks:
            if check == "drawings_exist":
                cur.execute(
                    "SELECT COUNT(*) FROM engineering.drawings WHERE project_id = %s",
                    (project_id,),
                )
                if cur.fetchone()[0] == 0:
                    unmet.append("No drawings linked to project")

            elif check == "disciplines_covered":
                cur.execute(
                    "SELECT disciplines FROM engineering.projects WHERE id = %s",
                    (project_id,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    cur.execute(
                        "SELECT DISTINCT discipline FROM engineering.drawings "
                        "WHERE project_id = %s",
                        (project_id,),
                    )
                    drawing_discs = {r[0] for r in cur.fetchall()}
                    required_discs = set(row[0])
                    missing = required_discs - drawing_discs
                    if missing:
                        unmet.append(f"Missing drawings for: {', '.join(missing)}")

            elif check == "permits_approved":
                cur.execute(
                    "SELECT COUNT(*) FROM engineering.permits "
                    "WHERE project_id = %s AND status = 'approved'",
                    (project_id,),
                )
                if cur.fetchone()[0] == 0:
                    unmet.append("No approved permits")

            elif check == "contractor_assigned":
                cur.execute(
                    "SELECT general_contractor FROM engineering.projects WHERE id = %s",
                    (project_id,),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    unmet.append("No general contractor assigned")

            elif check == "punch_items_resolved":
                cur.execute(
                    "SELECT COUNT(*) FROM engineering.punch_items "
                    "WHERE project_id = %s AND status IN ('open', 'in_progress')",
                    (project_id,),
                )
                open_items = cur.fetchone()[0]
                if open_items > 0:
                    unmet.append(f"{open_items} open punch list items")

            elif check == "inspections_passed":
                cur.execute(
                    "SELECT COUNT(*) FROM engineering.inspections "
                    "WHERE project_id = %s AND result = 'failed'",
                    (project_id,),
                )
                failed = cur.fetchone()[0]
                if failed > 0:
                    unmet.append(f"{failed} failed inspections")

            elif check == "co_issued":
                cur.execute(
                    "SELECT phase FROM engineering.projects WHERE id = %s",
                    (project_id,),
                )
                row = cur.fetchone()
                if not row or row[0] != "co":
                    unmet.append("Certificate of Occupancy not yet issued")

        return unmet

    def close(self):
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
