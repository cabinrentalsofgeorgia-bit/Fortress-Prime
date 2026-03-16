"""
Checkout Gateway API — Guest-facing payment flow.
Serves the checkout experience for direct bookings.
"""
from typing import Any, Dict, List
from fastapi import APIRouter
import structlog


logger = structlog.get_logger()
router = APIRouter()


def _build_quote_data_for_docs(
    quote: Any,
    lead: Any,
    options: List[Any],
    grand_total: str,
) -> Dict[str, Any]:
    """Build the data dict used by post-payment document automation."""
    first_opt = options[0] if options else None
    return {
        "quote_id": str(quote.id),
        "guest_name": getattr(lead, "guest_name", "Guest") if lead else "Guest",
        "guest_email": getattr(lead, "email", "") if lead else "",
        "property_name": (
            first_opt.property.name if first_opt and getattr(first_opt, "property", None) else "—"
        ),
        "check_in": str(first_opt.check_in_date) if first_opt else "",
        "check_out": str(first_opt.check_out_date) if first_opt else "",
        "grand_total": grand_total,
        "payment_method": quote.payment_method or "—",
        "options": [
            {
                "property_name": (
                    opt.property.name if getattr(opt, "property", None) else "—"
                ),
                "check_in": str(opt.check_in_date),
                "check_out": str(opt.check_out_date),
                "total_price": str(opt.total_price or "0"),
            }
            for opt in options
        ],
    }


async def _send_post_payment_docs(guest_email: str, quote_data: Dict[str, Any]) -> None:
    """Send post-payment documents (receipt, agreement) to the guest.

    This is a placeholder that logs the event. The full implementation
    would generate PDF receipt + rental agreement and email them.
    """
    logger.info(
        "post_payment_docs_sent",
        guest_email=guest_email,
        quote_id=quote_data.get("quote_id"),
        property_name=quote_data.get("property_name"),
    )


@router.get("/health")
async def checkout_health():
    return {"status": "ok", "service": "checkout_gateway"}
