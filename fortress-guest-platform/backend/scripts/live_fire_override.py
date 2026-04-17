"""
Live Fire Override — setup / teardown a $1.00 promo rule.

Usage:
    .uv-venv/bin/python -m backend.scripts.live_fire_override setup
    .uv-venv/bin/python -m backend.scripts.live_fire_override teardown
"""

from __future__ import annotations

import subprocess
import sys

DB_NAME = "fortress_shadow"
DB_USER = "fortress_admin"
DB_PASS = "fortress"
DB_HOST = "127.0.0.1"
DB_PORT = "5432"

RULE_NAME = "LIVE_FIRE_PROMO"

SETUP_SQL = f"""\
INSERT INTO learned_rules (
    id, property_id, rule_name, trigger_condition,
    adjustment_type, adjustment_value, confidence_score,
    status, created_at, updated_at
) VALUES (
    gen_random_uuid(), NULL, '{RULE_NAME}', '{{}}'::jsonb,
    'flat_fee', 0, 1.0,
    'active', NOW(), NOW()
)
ON CONFLICT DO NOTHING;
"""

TEARDOWN_SQL = f"DELETE FROM learned_rules WHERE rule_name = '{RULE_NAME}';"


def _run_psql(sql: str, label: str) -> None:
    result = subprocess.run(
        [
            "psql",
            "-h", DB_HOST,
            "-p", DB_PORT,
            "-U", DB_USER,
            "-d", DB_NAME,
            "-c", sql,
        ],
        env={**__import__("os").environ, "PGPASSWORD": DB_PASS},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[ERROR] {label} failed:\n{result.stderr}")
        sys.exit(1)
    print(f"[OK] {label}\n{result.stdout.strip()}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("setup", "teardown"):
        print("Usage: python -m backend.scripts.live_fire_override <setup|teardown>")
        sys.exit(1)

    action = sys.argv[1]

    if action == "setup":
        _run_psql(TEARDOWN_SQL, "Clearing any existing LIVE_FIRE_PROMO rows")
        _run_psql(SETUP_SQL, "Inserting LIVE_FIRE_PROMO rule (active)")
        print("\n=== LIVE FIRE PROMO ARMED ===")
        print("Promo code: COMMANDER-LIVE-FIRE")
        print("Any checkout with this code will resolve to $1.00.\n")
    else:
        _run_psql(TEARDOWN_SQL, "Removing LIVE_FIRE_PROMO rule")
        print("\n=== LIVE FIRE PROMO DISARMED ===\n")


if __name__ == "__main__":
    main()
