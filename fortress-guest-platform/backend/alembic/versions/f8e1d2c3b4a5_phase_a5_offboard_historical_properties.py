"""phase_a5_offboard_historical_properties

Sets renting_state = 'offboarded' on all properties that are NOT in the current
Streamline active roster (reconciled 2026-04-14).

The 14 IDs below are the Crog-VRS primary keys for the 14 properties Streamline
currently manages.  Everything else in the properties table is historical data from
past management relationships and has zero reservations.

Verification queries run inside the migration and will raise if the counts are wrong:
  - 13 active (the 13 actively-renting properties)
  - 1 pre_launch (Restoration Luxury — in Streamline but not yet generating revenue)
  - 44 offboarded (all historical properties)
  - 58 total (no rows created or destroyed)

Revision ID: f8e1d2c3b4a5
Revises: d1e2f3a4b5c6
Create Date: 2026-04-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8e1d2c3b4a5"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The 14 Crog-VRS property UUIDs that are in Streamline's active roster.
# These must NOT be touched by the offboarding UPDATE.
# Verified against live Streamline API on 2026-04-14 via GetPropertyList.
ACTIVE_PROPERTY_IDS = [
    "50f8e859-c30c-4d4c-a32e-8c8189eebb6c",  # Above the Timberline
    "8302f1c9-40d8-4d4d-99ae-f83647a15cc6",  # Aska Escape Lodge
    "ba440208-cfcf-4b47-b687-0f07f0436c21",  # Blue Ridge Lake Sanctuary
    "ed6a2ba8-6cca-4f69-b822-4b825e44d4af",  # Chase Mountain Dreams
    "50a9066d-fc2e-44c4-a716-25adb8fbad3e",  # Cherokee Sunrise on Noontootla Creek
    "53d047f9-2ba4-4ef4-bb29-22f34df279d3",  # Cohutta Sunset
    "72e278a3-1dc1-4bd8-9373-ce8f234f8ea0",  # Creekside Green
    "93b2253d-7ae4-4d6f-8be2-125d33799c88",  # Fallen Timber Lodge
    "25e397f9-ce07-4924-9fb6-c09759aff357",  # High Hopes
    "d7f4a8d3-7947-4d56-9c46-1cb37b96fd85",  # Restoration Luxury (pre_launch)
    "200780d1-2d26-494f-ae7a-5214ac0dd9e7",  # Riverview Lodge
    "63bf8847-9990-4a36-9943-b6c160ce1ec4",  # Serendipity on Noontootla Creek
    "e22e6ef2-1d8e-4310-ad73-0a105eda0583",  # Skyfall
    "7a263caf-6b0f-46cd-af22-6d1a0bfe486e",  # The Rivers Edge
]


def upgrade() -> None:
    bind = op.get_bind()

    # ── Offboard every property NOT in the 14-ID list ────────────────────────
    bind.execute(sa.text("""
        UPDATE properties
        SET renting_state = 'offboarded'
        WHERE id::text NOT IN :active_ids
    """).bindparams(sa.bindparam("active_ids", value=tuple(ACTIVE_PROPERTY_IDS),
                                expanding=True)))

    # ── Verification: counts MUST be exactly 13 / 1 / 44 / 58 ───────────────
    result = bind.execute(sa.text("""
        SELECT
            COUNT(*) FILTER (WHERE renting_state = 'active')       AS n_active,
            COUNT(*) FILTER (WHERE renting_state = 'pre_launch')   AS n_pre_launch,
            COUNT(*) FILTER (WHERE renting_state = 'offboarded')   AS n_offboarded,
            COUNT(*)                                                AS n_total
        FROM properties
    """))
    row = result.fetchone()
    n_active, n_pre_launch, n_offboarded, n_total = (
        row[0], row[1], row[2], row[3]
    )

    errors = []
    if n_active != 13:
        errors.append(f"active={n_active} (expected 13)")
    if n_pre_launch != 1:
        errors.append(f"pre_launch={n_pre_launch} (expected 1)")
    if n_offboarded != 44:
        errors.append(f"offboarded={n_offboarded} (expected 44)")
    if n_total != 58:
        errors.append(f"total={n_total} (expected 58)")
    if n_active + n_pre_launch + n_offboarded != n_total:
        errors.append(
            f"sum({n_active}+{n_pre_launch}+{n_offboarded}) != total({n_total})"
        )

    if errors:
        raise RuntimeError(
            "Migration f8e1d2c3b4a5 verification failed — counts are wrong: "
            + "; ".join(errors)
            + ". The migration has been rolled back."
        )


def downgrade() -> None:
    # Reset the 44 offboarded rows back to 'active' (their Phase A default).
    # Does not touch the 13 active or 1 pre_launch rows.
    op.execute(sa.text("""
        UPDATE properties
        SET renting_state = 'active'
        WHERE renting_state = 'offboarded'
    """))
