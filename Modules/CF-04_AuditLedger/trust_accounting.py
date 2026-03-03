"""
Trust Accounting Workflows for Vacation Rental Management
==========================================================
Extends CF-04 AuditLedger with property management-specific workflows:

  - process_booking_revenue():  Split guest payment into trust accounts
  - process_owner_payout():     Calculate and post monthly owner distribution
  - process_management_fee():   Extract management fee to operating account
  - process_tax_escrow():       Set aside tax liability (TOT / sales tax)
  - generate_owner_statement(): Build monthly owner financial statement
  - reconcile_streamline():     Match ledger entries to Streamline payments

Account structure (Chart of Accounts):
  1000  Cash - Operating
  1010  Cash - Trust (Owner Funds)
  1020  Cash - Tax Escrow
  2000  Accounts Payable - Owners
  2010  Sales Tax Payable
  4000  Rental Revenue
  4010  Cleaning Fee Revenue
  4020  Management Fee Revenue
  4030  Pet Fee Revenue
  4040  Extra/Add-on Revenue
  5000  Cleaning Expense
  5010  Maintenance Expense
  5020  Supplies Expense
  5030  Platform/OTA Fees
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Any

from .ledger_engine import AuditLedger

logger = logging.getLogger("CF04_TrustAccounting")


class TrustAccountingManager:
    """
    Orchestrates trust accounting workflows for vacation rental PM companies.
    Wraps AuditLedger's double-entry engine with property-management semantics.
    """

    DEFAULT_MGMT_FEE_PCT = Decimal("0.20")
    DEFAULT_TAX_RATE = Decimal("0.08")

    def __init__(self, ledger: Optional[AuditLedger] = None):
        self.ledger = ledger or AuditLedger()

    def close(self):
        self.ledger.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ========================================================================
    # Booking Revenue Processing
    # ========================================================================

    def process_booking_revenue(
        self,
        reservation_id: str,
        property_id: str,
        total_amount: Decimal,
        cleaning_fee: Decimal = Decimal("0"),
        pet_fee: Decimal = Decimal("0"),
        extras_total: Decimal = Decimal("0"),
        tax_rate: Optional[Decimal] = None,
        mgmt_fee_pct: Optional[Decimal] = None,
        posted_by: str = "system",
        entry_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Process a booking payment and split into proper trust accounts.

        Flow:
          Guest pays $1,500 total:
            DR Cash - Operating      $1,500   (money received)
            CR Rental Revenue        $1,100   (room revenue)
            CR Cleaning Fee Revenue  $  150   (cleaning)
            CR Pet Fee Revenue       $   50   (pet fee)
            CR Sales Tax Payable     $  100   (8% tax on room)
            CR Extra/Add-on Revenue  $  100   (extras)

        Then immediately split trust funds:
            DR Cash - Operating      $  XXX
            CR Cash - Trust          $  XXX   (owner's share)
            CR Cash - Tax Escrow     $  XXX   (tax escrow)
        """
        if tax_rate is None:
            tax_rate = self.DEFAULT_TAX_RATE
        if mgmt_fee_pct is None:
            mgmt_fee_pct = self.DEFAULT_MGMT_FEE_PCT

        room_revenue = total_amount - cleaning_fee - pet_fee - extras_total
        tax_amount = (room_revenue * tax_rate).quantize(Decimal("0.01"))

        # 1. Record the booking revenue (compound entry)
        revenue_lines = [
            {"account_code": "1000", "debit": total_amount, "credit": Decimal("0"),
             "memo": f"Guest payment received - Res {reservation_id}"},
            {"account_code": "4000", "debit": Decimal("0"), "credit": room_revenue - tax_amount,
             "memo": "Room revenue net of tax"},
            {"account_code": "2010", "debit": Decimal("0"), "credit": tax_amount,
             "memo": f"Sales/TOT tax @ {tax_rate * 100}%"},
        ]

        if cleaning_fee > 0:
            revenue_lines.append({
                "account_code": "4010", "debit": Decimal("0"), "credit": cleaning_fee,
                "memo": "Cleaning fee revenue",
            })
        if pet_fee > 0:
            revenue_lines.append({
                "account_code": "4030", "debit": Decimal("0"), "credit": pet_fee,
                "memo": "Pet fee revenue",
            })
        if extras_total > 0:
            revenue_lines.append({
                "account_code": "4040", "debit": Decimal("0"), "credit": extras_total,
                "memo": "Extras/add-on revenue",
            })

        revenue_result = self.ledger.post_compound_transaction(
            line_items=revenue_lines,
            description=f"Booking revenue — Reservation {reservation_id}",
            property_id=property_id,
            reference_id=reservation_id,
            reference_type="booking",
            entry_date=entry_date,
            posted_by=posted_by,
        )

        # 2. Split into trust accounts
        mgmt_fee = (total_amount * mgmt_fee_pct).quantize(Decimal("0.01"))
        owner_share = total_amount - mgmt_fee - tax_amount

        trust_lines = [
            {"account_code": "1000", "debit": Decimal("0"), "credit": owner_share + tax_amount,
             "memo": "Transfer to trust accounts"},
            {"account_code": "1010", "debit": owner_share, "credit": Decimal("0"),
             "memo": f"Owner trust fund ({(1 - mgmt_fee_pct) * 100}%)"},
            {"account_code": "1020", "debit": tax_amount, "credit": Decimal("0"),
             "memo": "Tax escrow deposit"},
        ]

        trust_result = self.ledger.post_compound_transaction(
            line_items=trust_lines,
            description=f"Trust split — Reservation {reservation_id}",
            property_id=property_id,
            reference_id=reservation_id,
            reference_type="trust_split",
            entry_date=entry_date,
            posted_by=posted_by,
        )

        # 3. Record management fee revenue
        fee_result = self.ledger.post_transaction(
            debit_acct="1000",
            credit_acct="4020",
            amount=float(mgmt_fee),
            description=f"Management fee — Reservation {reservation_id}",
            property_id=property_id,
            reference_id=reservation_id,
            reference_type="mgmt_fee",
            entry_date=entry_date,
            posted_by=posted_by,
        )

        # 4. Update trust balance tracking
        self.ledger.update_trust_balance(
            property_id=property_id,
            owner_delta=owner_share,
            operating_delta=mgmt_fee,
            escrow_delta=tax_amount,
            entry_id=revenue_result.get("entry_id"),
        )

        logger.info(
            f"[TRUST] Booking {reservation_id} processed: "
            f"total=${total_amount}, owner=${owner_share}, "
            f"mgmt_fee=${mgmt_fee}, tax=${tax_amount}"
        )

        return {
            "status": "PROCESSED",
            "reservation_id": reservation_id,
            "property_id": property_id,
            "total_amount": str(total_amount),
            "room_revenue": str(room_revenue),
            "owner_share": str(owner_share),
            "management_fee": str(mgmt_fee),
            "tax_escrow": str(tax_amount),
            "cleaning_fee": str(cleaning_fee),
            "revenue_entry_id": revenue_result.get("entry_id"),
            "trust_entry_id": trust_result.get("entry_id"),
            "fee_entry_id": fee_result.get("entry_id"),
        }

    # ========================================================================
    # Owner Payout Processing
    # ========================================================================

    def process_owner_payout(
        self,
        property_id: str,
        owner_name: str,
        payout_amount: Optional[Decimal] = None,
        deductions: Optional[List[Dict[str, Any]]] = None,
        posted_by: str = "system",
        entry_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Process a monthly owner payout.

        Deducts maintenance, supplies, and other expenses from the owner trust
        balance, then distributes the remainder to the owner.

        Flow:
          DR Accounts Payable - Owners   $X,XXX  (owe the owner)
          CR Cash - Trust                $X,XXX  (pay from trust)

        After deductions for any property expenses during the period.
        """
        trust_balances = self.ledger.get_trust_balance(property_id)
        available = Decimal("0")
        for tb in trust_balances:
            available += Decimal(str(tb.get("owner_funds", 0)))

        total_deductions = Decimal("0")
        deduction_entries = []

        for ded in (deductions or []):
            amt = Decimal(str(ded["amount"]))
            total_deductions += amt
            deduction_entries.append(self.ledger.post_transaction(
                debit_acct=ded.get("expense_account", "5010"),
                credit_acct="1010",
                amount=float(amt),
                description=f"Owner deduction: {ded['description']} — {property_id}",
                property_id=property_id,
                reference_type="owner_deduction",
                entry_date=entry_date,
                posted_by=posted_by,
            ))

        if payout_amount is None:
            payout_amount = max(available - total_deductions, Decimal("0"))

        if payout_amount <= 0:
            return {
                "status": "NO_PAYOUT",
                "property_id": property_id,
                "owner_name": owner_name,
                "available_balance": str(available),
                "deductions": str(total_deductions),
                "reason": "Insufficient balance after deductions",
            }

        payout_entry = self.ledger.post_transaction(
            debit_acct="2000",
            credit_acct="1010",
            amount=float(payout_amount),
            description=f"Owner payout — {owner_name} — {property_id}",
            property_id=property_id,
            reference_type="owner_payout",
            entry_date=entry_date,
            posted_by=posted_by,
        )

        self.ledger.update_trust_balance(
            property_id=property_id,
            owner_delta=-payout_amount,
            entry_id=payout_entry.get("entry_id"),
        )

        logger.info(
            f"[TRUST] Owner payout: {owner_name} — {property_id} — "
            f"${payout_amount} (deductions: ${total_deductions})"
        )

        return {
            "status": "PAID",
            "property_id": property_id,
            "owner_name": owner_name,
            "gross_available": str(available),
            "deductions": str(total_deductions),
            "net_payout": str(payout_amount),
            "payout_entry_id": payout_entry.get("entry_id"),
            "deduction_count": len(deduction_entries),
        }

    # ========================================================================
    # Tax Escrow Management
    # ========================================================================

    def process_tax_payment(
        self,
        tax_period: str,
        amount: Decimal,
        tax_authority: str = "Georgia DOR",
        posted_by: str = "system",
        entry_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Pay accumulated tax escrow to the tax authority.

        Flow:
          DR Sales Tax Payable     $X,XXX  (reduce liability)
          CR Cash - Tax Escrow     $X,XXX  (pay from escrow)
        """
        result = self.ledger.post_transaction(
            debit_acct="2010",
            credit_acct="1020",
            amount=float(amount),
            description=f"Tax payment — {tax_period} — {tax_authority}",
            reference_id=f"TAX-{tax_period}",
            reference_type="tax_payment",
            entry_date=entry_date,
            posted_by=posted_by,
        )

        logger.info(
            f"[TRUST] Tax payment: ${amount} for {tax_period} to {tax_authority}"
        )

        return {
            "status": "PAID",
            "tax_period": tax_period,
            "amount": str(amount),
            "tax_authority": tax_authority,
            "entry_id": result.get("entry_id"),
        }

    # ========================================================================
    # Monthly Owner Statement Generation
    # ========================================================================

    def generate_owner_statement(
        self,
        property_id: str,
        owner_name: str,
        period_start: date,
        period_end: date,
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive owner statement for a period.

        Returns a structured statement with revenue breakdown, expenses,
        management fees, tax escrow, and net payout.
        """
        entries = self.ledger.get_journal_entries(
            property_id=property_id,
            start_date=period_start,
            end_date=period_end,
            include_void=False,
        )

        gross_revenue = Decimal("0")
        cleaning_revenue = Decimal("0")
        mgmt_fees = Decimal("0")
        tax_escrow = Decimal("0")
        maintenance = Decimal("0")
        owner_payouts = Decimal("0")
        booking_count = 0

        for entry in entries:
            ref_type = entry.get("reference_type", "")
            lines = entry.get("line_items", [])

            if ref_type == "booking":
                booking_count += 1
                for line in lines:
                    if line.get("account_code") == "4000":
                        gross_revenue += Decimal(str(line.get("credit", 0)))
                    elif line.get("account_code") == "4010":
                        cleaning_revenue += Decimal(str(line.get("credit", 0)))

            elif ref_type == "mgmt_fee":
                for line in lines:
                    if line.get("account_code") == "4020":
                        mgmt_fees += Decimal(str(line.get("credit", 0)))

            elif ref_type == "trust_split":
                for line in lines:
                    if line.get("account_code") == "1020" and line.get("debit", 0) > 0:
                        tax_escrow += Decimal(str(line["debit"]))

            elif ref_type == "owner_deduction":
                for line in lines:
                    debit = Decimal(str(line.get("debit", 0)))
                    if debit > 0 and line.get("account_code", "").startswith("5"):
                        maintenance += debit

            elif ref_type == "owner_payout":
                for line in lines:
                    if line.get("account_code") == "2000":
                        owner_payouts += Decimal(str(line.get("debit", 0)))

        net_to_owner = gross_revenue + cleaning_revenue - mgmt_fees - tax_escrow - maintenance

        trust_balance = self.ledger.get_trust_balance(property_id)
        current_trust = Decimal("0")
        for tb in trust_balance:
            current_trust += Decimal(str(tb.get("owner_funds", 0)))

        return {
            "property_id": property_id,
            "owner_name": owner_name,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "booking_count": booking_count,
            "gross_revenue": str(gross_revenue),
            "cleaning_revenue": str(cleaning_revenue),
            "management_fee": str(mgmt_fees),
            "tax_escrow": str(tax_escrow),
            "maintenance_expenses": str(maintenance),
            "net_to_owner": str(net_to_owner),
            "owner_payouts": str(owner_payouts),
            "current_trust_balance": str(current_trust),
            "entry_count": len(entries),
        }
