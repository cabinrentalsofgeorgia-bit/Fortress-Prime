"""add_owner_charges_table

Phase C: creates the owner_charges table and owner_charge_type_enum.

Owner charges represent manual expense entries posted against an owner's
account by staff (e.g., cleaning, maintenance, linen costs). They reduce
the owner's closing balance in the statement period they are posted to.

Revision ID: c9e2f4a7b1d3
Revises: a3b5c7d9e1f2
Create Date: 2026-04-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9e2f4a7b1d3"
down_revision: Union[str, Sequence[str], None] = "a3b5c7d9e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The 17 transaction types from Streamline's owner charge workflow.
# Hacienda Tax, Statement Marker, Room Revenue, and Charge Expired Owner
# were deliberately excluded (see NOTES.md).
CHARGE_TYPE_VALUES = [
    "cleaning_fee",
    "maintenance",
    "management_fee",
    "supplies",
    "landscaping",
    "linen",
    "electric_bill",
    "housekeeper_pay",
    "advertising_fee",
    "third_party_ota_commission",
    "travel_agent_fee",
    "credit_card_dispute",
    "federal_tax_withholding",
    "adjust_owner_revenue",
    "credit_from_management",
    "pay_to_old_owner",
    "misc_guest_charges",
]


def upgrade() -> None:
    bind = op.get_bind()

    # Create the enum type
    charge_type_enum = postgresql.ENUM(
        *CHARGE_TYPE_VALUES,
        name="owner_charge_type_enum",
        create_type=False,
    )
    charge_type_enum.create(bind, checkfirst=True)

    op.execute(sa.text("""
        CREATE TABLE owner_charges (
            id                      BIGSERIAL       PRIMARY KEY,
            owner_payout_account_id BIGINT          NOT NULL
                REFERENCES owner_payout_accounts(id) ON DELETE RESTRICT,
            posting_date            DATE            NOT NULL,
            transaction_type        owner_charge_type_enum NOT NULL,
            description             VARCHAR(500)    NOT NULL,
            amount                  NUMERIC(12,2)   NOT NULL,
            reference_id            VARCHAR(100),
            originating_work_order_id BIGINT,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
            created_by              VARCHAR(255)    NOT NULL,
            voided_at               TIMESTAMPTZ,
            voided_by               VARCHAR(255),
            void_reason             TEXT,

            CONSTRAINT chk_oc_amount_not_zero
                CHECK (amount != 0),

            CONSTRAINT chk_oc_description_not_empty
                CHECK (description != ''),

            -- voided_at and voided_by must be set together
            CONSTRAINT chk_oc_void_pair
                CHECK (
                    (voided_at IS NULL AND voided_by IS NULL)
                    OR
                    (voided_at IS NOT NULL AND voided_by IS NOT NULL)
                )
        )
    """))

    # Indexes
    op.execute(sa.text(
        "CREATE INDEX ix_oc_owner_date "
        "ON owner_charges (owner_payout_account_id, posting_date)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_oc_transaction_type "
        "ON owner_charges (transaction_type)"
    ))
    # Partial index for fast active-charge lookups
    op.execute(sa.text(
        "CREATE INDEX ix_oc_active "
        "ON owner_charges (owner_payout_account_id, posting_date) "
        "WHERE voided_at IS NULL"
    ))

    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE ON owner_charges TO fortress_api"
    ))
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON SEQUENCE owner_charges_id_seq TO fortress_api"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS owner_charges"))
    charge_type_enum = postgresql.ENUM(name="owner_charge_type_enum")
    charge_type_enum.drop(op.get_bind(), checkfirst=True)
