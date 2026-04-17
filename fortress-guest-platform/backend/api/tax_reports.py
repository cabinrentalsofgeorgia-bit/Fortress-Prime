"""
Owner Tax Vault — Monthly tax report aggregation for filing.

Aggregates tax_breakdown data from completed reservations into a
single summary showing exactly what is owed to each tax authority:
  - GA DOR (State Sales Tax)
  - County (County Sales Tax + Lodging Tax)
  - GA DOT ($5/night fee)
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, extract, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.reservation import Reservation
from backend.models.property import Property

logger = structlog.get_logger()
router = APIRouter()

TWO = Decimal("0.01")


class TaxReportRow(BaseModel):
    property_name: str
    confirmation_code: str
    check_in: str
    check_out: str
    nights: int
    total_amount: float
    state_sales_tax: float
    county_sales_tax: float
    lodging_tax: float
    dot_fee: float
    total_tax: float
    county: str


class TaxReportSummary(BaseModel):
    month: int
    year: int
    total_reservations: int
    total_revenue: float
    total_state_sales_tax: float
    total_county_sales_tax: float
    total_lodging_tax: float
    total_dot_fees: float
    total_all_taxes: float
    rows: list[TaxReportRow]


def _extract_tax(pb: dict | None) -> dict:
    """Pull tax_breakdown from price_breakdown JSONB, with safe fallbacks."""
    if not pb:
        return {"state_sales_tax": 0, "county_sales_tax": 0, "lodging_tax": 0, "dot_fee": 0, "total_tax": 0, "county": "Unknown"}

    tb = pb.get("tax_breakdown")
    if tb:
        return {
            "state_sales_tax": float(tb.get("state_sales_tax", 0)),
            "county_sales_tax": float(tb.get("county_sales_tax", 0)),
            "lodging_tax": float(tb.get("lodging_tax", 0)),
            "dot_fee": float(tb.get("dot_fee", 0)),
            "total_tax": float(tb.get("total_tax", 0)),
            "county": tb.get("county", "Unknown"),
        }

    tax_amount = float(pb.get("tax_amount", 0) or 0)
    return {"state_sales_tax": tax_amount, "county_sales_tax": 0, "lodging_tax": 0, "dot_fee": 0, "total_tax": tax_amount, "county": "Unknown"}


@router.get("/monthly", response_model=TaxReportSummary)
async def get_monthly_tax_report(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
) -> TaxReportSummary:
    stmt = (
        select(Reservation, Property.name.label("prop_name"), Property.county.label("prop_county"))
        .join(Property, Reservation.property_id == Property.id)
        .where(
            and_(
                extract("month", Reservation.check_out_date) == month,
                extract("year", Reservation.check_out_date) == year,
                Reservation.status.in_(["confirmed", "checked_out", "completed"]),
            )
        )
        .order_by(Reservation.check_out_date.asc())
    )
    results = (await db.execute(stmt)).all()

    rows: list[TaxReportRow] = []
    sum_revenue = Decimal("0")
    sum_state = Decimal("0")
    sum_county = Decimal("0")
    sum_lodging = Decimal("0")
    sum_dot = Decimal("0")

    for res, prop_name, prop_county in results:
        tax = _extract_tax(res.price_breakdown)
        nights = (res.check_out_date - res.check_in_date).days if res.check_in_date and res.check_out_date else 0
        total = float(res.total_amount or 0)

        county_label = tax["county"]
        if county_label == "Unknown" and prop_county:
            county_label = prop_county

        row = TaxReportRow(
            property_name=prop_name or "Unknown",
            confirmation_code=res.confirmation_code or "",
            check_in=res.check_in_date.isoformat() if res.check_in_date else "",
            check_out=res.check_out_date.isoformat() if res.check_out_date else "",
            nights=nights,
            total_amount=total,
            state_sales_tax=tax["state_sales_tax"],
            county_sales_tax=tax["county_sales_tax"],
            lodging_tax=tax["lodging_tax"],
            dot_fee=tax["dot_fee"],
            total_tax=tax["total_tax"],
            county=county_label,
        )
        rows.append(row)
        sum_revenue += Decimal(str(total))
        sum_state += Decimal(str(tax["state_sales_tax"]))
        sum_county += Decimal(str(tax["county_sales_tax"]))
        sum_lodging += Decimal(str(tax["lodging_tax"]))
        sum_dot += Decimal(str(tax["dot_fee"]))

    total_all = (sum_state + sum_county + sum_lodging + sum_dot).quantize(TWO, rounding=ROUND_HALF_UP)

    logger.info("tax_report_generated", month=month, year=year, reservations=len(rows), total_tax=float(total_all))

    return TaxReportSummary(
        month=month,
        year=year,
        total_reservations=len(rows),
        total_revenue=float(sum_revenue.quantize(TWO)),
        total_state_sales_tax=float(sum_state.quantize(TWO)),
        total_county_sales_tax=float(sum_county.quantize(TWO)),
        total_lodging_tax=float(sum_lodging.quantize(TWO)),
        total_dot_fees=float(sum_dot.quantize(TWO)),
        total_all_taxes=float(total_all),
        rows=rows,
    )


@router.get("/monthly/csv")
async def download_monthly_csv(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
):
    report = await get_monthly_tax_report(month=month, year=year, db=db)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Property", "Confirmation", "Check-In", "Check-Out", "Nights",
        "Revenue", "State Sales Tax", "County Sales Tax", "Lodging Tax",
        "DOT Fee", "Total Tax", "County",
    ])
    for row in report.rows:
        writer.writerow([
            row.property_name, row.confirmation_code, row.check_in,
            row.check_out, row.nights, f"{row.total_amount:.2f}",
            f"{row.state_sales_tax:.2f}", f"{row.county_sales_tax:.2f}",
            f"{row.lodging_tax:.2f}", f"{row.dot_fee:.2f}",
            f"{row.total_tax:.2f}", row.county,
        ])
    writer.writerow([])
    writer.writerow(["SUMMARY"])
    writer.writerow(["Total Reservations", report.total_reservations])
    writer.writerow(["Total Revenue", f"{report.total_revenue:.2f}"])
    writer.writerow(["GA State Sales Tax (→ GA DOR)", f"{report.total_state_sales_tax:.2f}"])
    writer.writerow(["County Sales Tax (→ County)", f"{report.total_county_sales_tax:.2f}"])
    writer.writerow(["Lodging Tax (→ County)", f"{report.total_lodging_tax:.2f}"])
    writer.writerow(["DOT Fees (→ GA DOR)", f"{report.total_dot_fees:.2f}"])
    writer.writerow(["TOTAL ALL TAXES", f"{report.total_all_taxes:.2f}"])

    output.seek(0)
    filename = f"tax_report_{year}_{month:02d}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/projections")
async def get_revenue_projections(
    db: AsyncSession = Depends(get_db),
):
    """30/60/90-day revenue, payout, and tax obligation projections."""
    from backend.services.ledger import PredictiveAnalytics
    analytics = PredictiveAnalytics(db)
    return await analytics.project()
