"""
Accounting — Double-Entry Ledger Engine
==========================================
Operation Strangler Fig: The system that kills QuickBooks Online.

This package implements a full GAAP-compliant double-entry bookkeeping
engine. Every Plaid transaction becomes two ledger lines (debit + credit).
The fundamental invariant: sum(debits) == sum(credits) at ALL times.

Sub-modules:
    models         — JournalEntry, LedgerLine, AccountType
    engine         — Posting, validation, balance computation
    schema         — PostgreSQL table creation
    mapper         — Plaid category → Chart of Accounts (self-learning)
    statements     — P&L, Balance Sheet, Trial Balance generators
    import_qbo_coa — QBO Chart of Accounts CSV importer
    revenue_bridge — QuantRevenue forecast → GL bridge
    cfo_bridge     — CFO Extractor CSV → GL bridge (9,899 PDF extractions)
    train_mapper   — QBO transaction history → learned account mappings
"""

__all__ = [
    "models", "engine", "schema", "mapper", "statements", "import_qbo_coa",
    "revenue_bridge", "cfo_bridge", "train_mapper",
]
