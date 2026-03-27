"""
Pydantic contracts for financial structured outputs.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProposedLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="E.g., 'Trust Cash', 'Guest Advance Deposits', 'Owner Funds Payable'",
    )
    entry_type: Literal["debit", "credit"]
    amount_cents: int = Field(
        ...,
        ge=0,
        description="Must be strictly integer cents. No floats.",
    )


class ProposedTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[ProposedLedgerEntry] = Field(default_factory=list, min_length=1)
    reasoning: str = Field(
        ...,
        min_length=1,
        max_length=1200,
        description="A brief explanation of why the agent mapped the transaction this way.",
    )


class GRECAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_compliant: bool
    violations: list[str] = Field(
        default_factory=list,
        description="Concrete GREC trust-accounting violations detected in the proposal.",
    )
