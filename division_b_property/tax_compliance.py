"""
Fannin County Tax Compliance
==============================
Monitors and computes tax obligations for Cabin Rentals of Georgia.

Tax types tracked:
    - Georgia Sales Tax (state + county)
    - Fannin County Lodging Tax / Excise Tax
    - Property Tax on cabin assets
    - Income Tax estimates (pass-through)
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger("division_b.tax")


# =============================================================================
# TAX RATES (Fannin County, Georgia)
# =============================================================================

TAX_RATES = {
    "ga_state_sales_tax": Decimal("0.04"),           # 4% state
    "fannin_county_sales_tax": Decimal("0.04"),       # 4% county (total 8% combined)
    "lodging_excise_tax": Decimal("0.05"),            # 5% lodging/excise
    "hotel_motel_tax": Decimal("0.05"),               # 5% hotel/motel tax
}


@dataclass
class TaxObligation:
    """A computed tax obligation for a given period."""
    tax_type: str
    period_start: date
    period_end: date
    taxable_revenue: Decimal
    rate: Decimal
    amount_due: Decimal
    amount_paid: Decimal = Decimal("0.00")
    status: str = "pending"  # pending, filed, paid, overdue

    @property
    def balance_due(self) -> Decimal:
        return self.amount_due - self.amount_paid


def compute_lodging_taxes(
    gross_rental_revenue: Decimal,
    period_start: date,
    period_end: date,
) -> List[TaxObligation]:
    """
    Compute all applicable lodging taxes for a given period.

    Returns a list of TaxObligation objects — one per tax type.
    """
    obligations = []

    for tax_type, rate in TAX_RATES.items():
        amount = (gross_rental_revenue * rate).quantize(Decimal("0.01"))
        obligations.append(TaxObligation(
            tax_type=tax_type,
            period_start=period_start,
            period_end=period_end,
            taxable_revenue=gross_rental_revenue,
            rate=rate,
            amount_due=amount,
        ))

    total = sum(o.amount_due for o in obligations)
    logger.info(
        f"Computed lodging taxes for {period_start} to {period_end}: "
        f"${total:,.2f} on ${gross_rental_revenue:,.2f} revenue"
    )

    return obligations


def generate_tax_report(
    obligations: List[TaxObligation],
) -> Dict[str, Any]:
    """Generate a tax summary report for the Sovereign."""
    return {
        "total_obligations": len(obligations),
        "total_due": float(sum(o.amount_due for o in obligations)),
        "total_paid": float(sum(o.amount_paid for o in obligations)),
        "total_balance": float(sum(o.balance_due for o in obligations)),
        "by_type": {
            o.tax_type: {
                "rate": float(o.rate),
                "due": float(o.amount_due),
                "paid": float(o.amount_paid),
                "status": o.status,
            }
            for o in obligations
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
