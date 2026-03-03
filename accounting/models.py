"""
Accounting Models — The DNA of Double-Entry Bookkeeping
=========================================================
These are the core data structures. Every financial event in Fortress
ultimately becomes a JournalEntry with balanced LedgerLines.

Rules:
    1. Every JournalEntry has >= 2 LedgerLines
    2. sum(debits) MUST equal sum(credits) — always, no exceptions
    3. Accounts follow a hierarchical code: "Expenses:Utilities:Electric"
    4. Normal balances: Assets/Expenses = Debit, Liabilities/Equity/Revenue = Credit
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# ACCOUNT TYPES
# =============================================================================

class AccountType(str, Enum):
    """Standard accounting categories (GAAP)."""
    ASSET = "asset"             # Normal balance: Debit  (1xxx)
    LIABILITY = "liability"     # Normal balance: Credit (2xxx)
    EQUITY = "equity"           # Normal balance: Credit (3xxx)
    REVENUE = "revenue"         # Normal balance: Credit (4xxx)
    EXPENSE = "expense"         # Normal balance: Debit  (5xxx)
    COGS = "cogs"               # Normal balance: Debit  (6xxx) Cost of Goods Sold

    @property
    def normal_balance(self) -> str:
        """The side that increases this account type."""
        if self in (AccountType.ASSET, AccountType.EXPENSE, AccountType.COGS):
            return "debit"
        return "credit"

    @property
    def code_prefix(self) -> str:
        """Standard numbering prefix."""
        return {
            AccountType.ASSET: "1",
            AccountType.LIABILITY: "2",
            AccountType.EQUITY: "3",
            AccountType.REVENUE: "4",
            AccountType.EXPENSE: "5",
            AccountType.COGS: "6",
        }[self]


# =============================================================================
# CHART OF ACCOUNTS
# =============================================================================

@dataclass
class Account:
    """A single account in the Chart of Accounts."""
    code: str                          # e.g., "5200" or "5200.10"
    name: str                          # e.g., "Utilities:Electric"
    account_type: AccountType          # ASSET, LIABILITY, etc.
    parent_code: Optional[str] = None  # Parent account for hierarchy
    description: str = ""
    is_active: bool = True
    qbo_id: Optional[str] = None       # QBO account ID (for reconciliation)
    qbo_name: Optional[str] = None     # QBO display name

    @property
    def full_path(self) -> str:
        """Hierarchical path e.g., 'Expenses:Utilities:Electric'."""
        return f"{self.account_type.value.title()}:{self.name}"


# =============================================================================
# ACCOUNTING ERROR
# =============================================================================

class AccountingError(Exception):
    """Raised when the books don't balance. This is FATAL."""
    pass


# =============================================================================
# LEDGER LINE (one half of a double-entry)
# =============================================================================

@dataclass
class LedgerLine:
    """
    A single line in a journal entry — one debit or one credit.

    In a journal entry for "Paid $347.82 to Blue Ridge Electric":
        Line 1: Debit  Expenses:Utilities:Electric  $347.82
        Line 2: Credit Assets:Bank:Operating        $347.82
    """
    account_code: str               # Chart of Accounts code
    account_name: str               # Human-readable name
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")
    memo: str = ""

    def __post_init__(self):
        """Normalize to 2 decimal places."""
        self.debit = Decimal(str(self.debit)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        self.credit = Decimal(str(self.credit)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )

    def validate(self):
        """A line must be EITHER a debit OR a credit, never both."""
        if self.debit > 0 and self.credit > 0:
            raise AccountingError(
                f"Line cannot be both debit and credit: "
                f"{self.account_code} D={self.debit} C={self.credit}"
            )
        if self.debit == 0 and self.credit == 0:
            raise AccountingError(
                f"Line must have a non-zero amount: {self.account_code}"
            )
        if self.debit < 0 or self.credit < 0:
            raise AccountingError(
                f"Negative amounts not allowed: {self.account_code} "
                f"D={self.debit} C={self.credit}"
            )


# =============================================================================
# JOURNAL ENTRY (the complete double-entry transaction)
# =============================================================================

@dataclass
class JournalEntry:
    """
    A complete double-entry journal entry.

    The ABSOLUTE rule: sum(debits) == sum(credits).
    If this invariant is violated, the entry is rejected and an
    AccountingError is raised. There are no exceptions.
    """
    entry_id: str                                   # Unique ID
    date: date                                      # Transaction date
    description: str                                # What happened
    lines: List[LedgerLine] = field(default_factory=list)

    # Source tracking
    source_type: str = "plaid"                      # plaid, manual, import, adjustment
    source_ref: str = ""                            # plaid_txn_id, invoice #, etc.
    division: str = ""                              # division_a or division_b

    # Metadata
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    created_by: str = "fortress"                    # agent, manual, import
    memo: str = ""
    is_posted: bool = False                         # True once written to GL

    # =================================================================
    # VALIDATION — The Books MUST Balance
    # =================================================================

    def validate(self) -> bool:
        """
        Validate this journal entry. Raises AccountingError if invalid.

        Checks:
            1. At least 2 lines
            2. Each line is valid (debit XOR credit)
            3. sum(debits) == sum(credits) — THE FUNDAMENTAL RULE
        """
        if len(self.lines) < 2:
            raise AccountingError(
                f"Journal entry {self.entry_id} must have at least 2 lines "
                f"(has {len(self.lines)})"
            )

        for line in self.lines:
            line.validate()

        total_debits = sum(l.debit for l in self.lines)
        total_credits = sum(l.credit for l in self.lines)

        if total_debits != total_credits:
            raise AccountingError(
                f"THE BOOKS ARE NOT BALANCED! Entry {self.entry_id}: "
                f"Debits={total_debits} Credits={total_credits} "
                f"Delta={total_debits - total_credits}"
            )

        return True

    @property
    def total_debits(self) -> Decimal:
        return sum(l.debit for l in self.lines)

    @property
    def total_credits(self) -> Decimal:
        return sum(l.credit for l in self.lines)

    @property
    def is_balanced(self) -> bool:
        return self.total_debits == self.total_credits
