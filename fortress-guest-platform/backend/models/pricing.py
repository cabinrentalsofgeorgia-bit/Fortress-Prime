"""
Pydantic contracts for the Sovereign Fast Quote pipeline.

These schemas serve double-duty:

1. **Runtime**: Validate incoming quote requests and serialize outgoing responses
   for both the ``/api/quote`` and ``/api/v1/checkout/quote`` endpoints.

2. **AI Forensics**: The Godhead Swarm's ``agent_hermes`` LLM receives the
   serialized ``QuoteResponse`` (specifically the ``line_items`` array) inside
   an Evidence Packet when auditing Legacy-vs-DGX pricing parity.  Each
   ``QuoteLineItem`` provides **semantic meaning** — the AI does not need to
   reverse-engineer math; it reads items like::

       {"description": "Pet Cleaning Fee", "amount": 150.00, "type": "fee"}

   If a line item is missing from the DGX response but present in the Legacy
   payload, Hermes flags the discrepancy and may auto-generate a
   ``LearnedRule`` to correct the Quote Engine at runtime.

The **Universal Ledger** format in ``storefront_checkout.py`` extends these
primitives with ``is_taxable``, ``id``, and ``summary`` fields for the
frontend checkout sidebar.  Storefront checkout uses its own fee loop with
the same optional-fee rules; the fast-quote pipeline uses ``calculate_fast_quote``
in ``pricing_service.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


TWO_PLACES = Decimal("0.01")


class QuoteRequest(BaseModel):
    """
    Inbound quote request parameters.

    Used by:
      - ``POST /api/quote`` (fast_quote endpoint)
      - ``calculate_fast_quote()`` in the sovereign pricing pipeline
      - ``agent_paper_clip()`` in the Godhead Swarm (shadow audit intake)

    The ``pets`` field directly controls whether pet-related fees and deposits
    appear in the response.  ``adults + children`` determines the extra-guest
    fee threshold (currently > 4 adults triggers a per-night surcharge).

    ``selected_add_on_ids`` lists fee UUIDs (as strings) the caller wants included
    in the quote; optional fees are excluded unless their id appears here.
    """
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    check_in: date
    check_out: date
    adults: int = Field(ge=1)
    children: int = Field(ge=0)
    pets: int = Field(ge=0)
    selected_add_on_ids: list[str] = Field(default_factory=list)


class QuoteLineItem(BaseModel):
    """
    A single pricing row in the quote response.

    This is the atomic unit of pricing transparency.  The ``type`` field gives
    both the frontend and the AI agent semantic context:

      - **rent**: Base nightly accommodation total.
      - **fee**: Mandatory property fees (cleaning, pet cleaning, extra guest).
      - **tax**: Government-mandated lodging taxes.
      - **discount**: Yield adjustments, AI-learned corrections, or promotions.

    ``agent_hermes`` uses this schema to build its Evidence Packet.  If a known
    fee type (e.g. cleaning) is absent from the DGX ``line_items`` but present
    in the Legacy payload, Hermes infers a ``LearnedRule`` to close the gap.
    """
    model_config = ConfigDict(extra="forbid")

    description: str
    amount: Decimal
    type: Literal["rent", "fee", "tax", "discount"]

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> float:
        return float(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


class QuoteResponse(BaseModel):
    """
    Complete quote response from the sovereign pricing pipeline.

    ``line_items`` is the source of truth — every dollar charged appears as a
    ``QuoteLineItem``.  ``total_amount`` is the pre-computed grand total; the
    frontend must display this value directly and never sum line items
    client-side (prevents floating-point rounding drift).

    This response is fed directly to the Godhead Swarm in two flows:

    1. **Shadow Router**: ``agent_paper_clip`` compares ``total_amount`` (in
       cents) against the Legacy total.  If they differ, the full ``line_items``
       array is forwarded through Claw → Hermes → Nemo.

    2. **Universal Ledger**: ``storefront_checkout.py`` maps these line items
       into the extended ``LedgerLineItem`` format (with ``is_taxable``, ``id``)
       and groups them with a ``LedgerSummary`` for the checkout sidebar.
    """
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    currency: str = "USD"
    line_items: list[QuoteLineItem]
    total_amount: Decimal
    is_bookable: bool

    @field_serializer("total_amount")
    def serialize_total_amount(self, value: Decimal) -> float:
        return float(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))
