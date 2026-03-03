"""
Engineering Division — Permit Tracker Handler
================================================
CRUD operations for building permits. Manages the full permit lifecycle:

    Draft → Submitted → Under Review → Approved → (Active) → Closed
                                     → Denied → (Resubmit or Appeal)

Also handles:
    - Permit renewal tracking
    - Fee tracking
    - Conditional approval management
    - Expiration alerts (fed to Watchtower)

Usage:
    from division_engineering.handlers.permit_tracker import PermitTracker

    tracker = PermitTracker()
    tracker.create_permit(project_code="PRJ-2026-001", permit_type="building", ...)
    tracker.update_status("BLD-2026-001", "approved", approval_date="2026-03-15")
    tracker.get_expiring(days=30)
"""

import logging
import psycopg2
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import os

logger = logging.getLogger("division_engineering.permits")

PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")


class PermitTracker:
    """Manages building permit lifecycle for all engineering projects."""

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

    def create_permit(
        self,
        project_code: str,
        permit_type: str,
        permit_number: Optional[str] = None,
        jurisdiction: str = "Fannin County",
        issuing_authority: Optional[str] = None,
        application_date: Optional[str] = None,
        application_fee: Optional[float] = None,
        impact_fee: Optional[float] = None,
        conditions: Optional[str] = None,
        special_inspections: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new permit application."""
        cur = self.conn.cursor()

        # Look up project
        cur.execute(
            "SELECT id, property_id FROM engineering.projects WHERE project_code = %s",
            (project_code,),
        )
        row = cur.fetchone()
        if not row:
            return {"error": f"Project {project_code} not found"}

        project_id, property_id = row

        cur.execute("""
            INSERT INTO engineering.permits
            (project_id, property_id, permit_type, permit_number,
             jurisdiction, issuing_authority, status,
             application_date, application_fee, impact_fee,
             conditions, special_inspections, notes)
            VALUES (%s, %s, %s, %s, %s, %s, 'draft',
                    %s, %s, %s, %s, %s, %s)
            RETURNING id, permit_type, status
        """, (
            project_id, property_id, permit_type, permit_number,
            jurisdiction, issuing_authority,
            application_date, application_fee, impact_fee,
            conditions, special_inspections, notes,
        ))

        result = cur.fetchone()
        self.conn.commit()

        logger.info(
            f"Permit created: {permit_type} for project {project_code} "
            f"(ID: {result[0]})"
        )

        return {
            "id": result[0],
            "permit_type": result[1],
            "status": result[2],
            "project_code": project_code,
            "jurisdiction": jurisdiction,
        }

    def update_status(
        self,
        permit_id: int,
        new_status: str,
        approval_date: Optional[str] = None,
        expiration_date: Optional[str] = None,
        permit_number: Optional[str] = None,
        conditions: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update permit status (submitted, approved, denied, etc.)."""
        cur = self.conn.cursor()

        cur.execute("""
            UPDATE engineering.permits SET
                status = %s,
                approval_date = COALESCE(%s, approval_date),
                expiration_date = COALESCE(%s, expiration_date),
                permit_number = COALESCE(%s, permit_number),
                conditions = COALESCE(%s, conditions),
                notes = COALESCE(%s, notes),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, permit_type, status, permit_number
        """, (
            new_status, approval_date, expiration_date,
            permit_number, conditions, notes, permit_id,
        ))

        row = cur.fetchone()
        self.conn.commit()

        if not row:
            return {"error": f"Permit {permit_id} not found"}

        logger.info(f"Permit {row[3] or row[0]} → {new_status}")
        return {
            "id": row[0],
            "permit_type": row[1],
            "status": row[2],
            "permit_number": row[3],
        }

    def get_expiring(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get permits expiring within N days."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT p.id, p.permit_number, p.permit_type, p.status,
                   p.expiration_date, p.jurisdiction,
                   pr.project_code, pr.name, pr.property_name
            FROM engineering.permits p
            JOIN engineering.projects pr ON p.project_id = pr.id
            WHERE p.expiration_date BETWEEN CURRENT_DATE
                  AND CURRENT_DATE + INTERVAL '%s days'
                  AND p.status NOT IN ('closed', 'revoked', 'expired')
            ORDER BY p.expiration_date
        """, (days,))

        results = []
        for row in cur.fetchall():
            days_left = (row[4] - datetime.now(timezone.utc).date()).days
            results.append({
                "id": row[0],
                "permit_number": row[1],
                "permit_type": row[2],
                "status": row[3],
                "expiration_date": str(row[4]),
                "jurisdiction": row[5],
                "project_code": row[6],
                "project_name": row[7],
                "property_name": row[8],
                "days_until_expiry": days_left,
                "urgency": (
                    "CRITICAL" if days_left <= 7 else
                    "HIGH" if days_left <= 14 else "MEDIUM"
                ),
            })

        return results

    def get_by_project(self, project_code: str) -> List[Dict[str, Any]]:
        """Get all permits for a project."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT p.id, p.permit_number, p.permit_type, p.status,
                   p.application_date, p.approval_date, p.expiration_date,
                   p.jurisdiction, p.conditions
            FROM engineering.permits p
            JOIN engineering.projects pr ON p.project_id = pr.id
            WHERE pr.project_code = %s
            ORDER BY p.created_at
        """, (project_code,))

        return [
            {
                "id": row[0],
                "permit_number": row[1],
                "permit_type": row[2],
                "status": row[3],
                "application_date": str(row[4]) if row[4] else None,
                "approval_date": str(row[5]) if row[5] else None,
                "expiration_date": str(row[6]) if row[6] else None,
                "jurisdiction": row[7],
                "conditions": row[8],
            }
            for row in cur.fetchall()
        ]

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
