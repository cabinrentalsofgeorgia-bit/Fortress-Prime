"""
Canonical Legal Qdrant collection names for the current 7IL runtime.

Do not route 7IL evidence through the v2 alias until Case I/II coverage has
been reindexed and verified. The legacy 768-dim collections remain the active
work-product and privileged targets for ingest, reprocess, and Council reads.
"""

from __future__ import annotations

from typing import Final

LEGAL_WORK_PRODUCT_COLLECTION: Final = "legal_ediscovery"
LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION: Final = "legal_privileged_communications"
LEGAL_LEGACY_VECTOR_SIZE: Final = 768

LEGAL_EDISCOVERY_ACTIVE_ALIAS: Final = "legal_ediscovery_active"
LEGAL_EDISCOVERY_V2_COLLECTION: Final = "legal_ediscovery_v2"
LEGAL_PRIVILEGED_COMMUNICATIONS_V2_COLLECTION: Final = (
    "legal_privileged_communications_v2"
)

LEGAL_COLLECTIONS_UNSAFE_FOR_7IL: Final = frozenset(
    {
        LEGAL_EDISCOVERY_ACTIVE_ALIAS,
        LEGAL_EDISCOVERY_V2_COLLECTION,
        LEGAL_PRIVILEGED_COMMUNICATIONS_V2_COLLECTION,
    }
)
