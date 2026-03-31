"""
Contract Generator — Dynamic management agreement creation from Iron Dome data.

Queries the Iron Dome financial database for the exact owner/property split ratios,
CapEx markup percentages, and rate card data, then renders a legally-accurate
management agreement PDF via Jinja2 + WeasyPrint.
"""

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(service="contract_generator")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
CONTRACT_STORAGE = Path(
    os.getenv("CONTRACT_STORAGE_DIR", str(PROJECT_ROOT / "storage" / "contracts"))
)
CONTRACT_STORAGE.mkdir(parents=True, exist_ok=True)

NAS_CONTRACT_BASE = Path("/mnt/fortress_nas/sectors/legal/owner-contracts")

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,
)


async def _fetch_owner_info(db: AsyncSession, owner_id: str) -> Dict[str, Any]:
    """Fetch owner contact info from owner_property_map."""
    result = await db.execute(
        text("""
            SELECT owner_name, email, phone
            FROM owner_property_map
            WHERE sl_owner_id = :oid
            LIMIT 1
        """),
        {"oid": owner_id},
    )
    row = result.first()
    if row:
        return {"owner_name": row.owner_name or "", "owner_email": row.email or "", "owner_phone": row.phone or ""}
    return {"owner_name": "", "owner_email": "", "owner_phone": ""}


async def _fetch_property_info(db: AsyncSession, property_id: str) -> Dict[str, Any]:
    """Fetch property details from the properties table."""
    result = await db.execute(
        text("""
            SELECT name, address, bedrooms, bathrooms, max_guests, rate_card, owner_id
            FROM properties
            WHERE id::text = :pid OR streamline_property_id = :pid
            LIMIT 1
        """),
        {"pid": property_id},
    )
    row = result.first()
    if not row:
        return {}

    rate_range = ""
    if row.rate_card and isinstance(row.rate_card, dict):
        rates = row.rate_card.get("rates", [])
        if rates:
            amounts = [float(r.get("rate", 0)) for r in rates if r.get("rate")]
            if amounts:
                rate_range = f"${min(amounts):,.0f} – ${max(amounts):,.0f} per night"

    return {
        "property_name": row.name or "",
        "property_address": row.address or "",
        "bedrooms": str(row.bedrooms or ""),
        "bathrooms": str(row.bathrooms or ""),
        "max_guests": str(row.max_guests or ""),
        "nightly_rate_range": rate_range,
        "db_owner_id": row.owner_id or "",
    }


async def _fetch_management_split(db: AsyncSession, property_id: str) -> Dict[str, Any]:
    """Fetch the owner/PM revenue split from management_splits."""
    result = await db.execute(
        text("""
            SELECT owner_pct, pm_pct
            FROM management_splits
            WHERE property_id::text = :pid
            LIMIT 1
        """),
        {"pid": property_id},
    )
    row = result.first()
    if row:
        return {
            "owner_pct": str(int(row.owner_pct)) if row.owner_pct == int(row.owner_pct) else str(row.owner_pct),
            "pm_pct": str(int(row.pm_pct)) if row.pm_pct == int(row.pm_pct) else str(row.pm_pct),
        }
    return {"owner_pct": "65", "pm_pct": "35"}


async def _fetch_capex_markup(db: AsyncSession, property_id: str) -> str:
    """Fetch the CapEx markup percentage from owner_markup_rules."""
    result = await db.execute(
        text("""
            SELECT markup_percentage AS markup_pct
            FROM owner_markup_rules
            WHERE property_id::text = :pid
            LIMIT 1
        """),
        {"pid": property_id},
    )
    row = result.first()
    if row:
        val = row.markup_pct
        return str(int(val)) if val == int(val) else str(val)
    return "23"


async def generate_management_contract(
    owner_id: str,
    property_id: str,
    db: AsyncSession,
    term_years: int = 1,
    effective_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Generate a management agreement PDF from Iron Dome financial data.

    Returns dict with: pdf_path, rendered_html, variables_used, nas_path (if NAS available)
    """
    if effective_date is None:
        effective_date = date.today()

    owner_info = await _fetch_owner_info(db, owner_id)
    prop_info = await _fetch_property_info(db, property_id)
    split_info = await _fetch_management_split(db, property_id)
    capex_markup = await _fetch_capex_markup(db, property_id)

    if not prop_info:
        raise ValueError(f"Property {property_id} not found")

    variables = {
        **owner_info,
        **prop_info,
        **split_info,
        "capex_markup_pct": capex_markup,
        "term_years": str(term_years),
        "effective_date": effective_date.strftime("%B %d, %Y"),
    }

    template = _jinja_env.get_template("management_agreement.html")
    rendered_html = template.render(**variables)

    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint_not_installed")
        return {
            "pdf_path": None,
            "rendered_html": rendered_html,
            "variables_used": variables,
            "error": "WeasyPrint not installed",
        }

    owner_dir = CONTRACT_STORAGE / owner_id
    owner_dir.mkdir(parents=True, exist_ok=True)

    filename = f"management_agreement_{property_id}_{effective_date.isoformat()}.pdf"
    pdf_path = owner_dir / filename

    try:
        HTML(string=rendered_html).write_pdf(str(pdf_path))
        logger.info(
            "management_contract_generated",
            owner_id=owner_id,
            property_id=property_id,
            pdf_path=str(pdf_path),
        )
    except Exception as e:
        logger.error("management_contract_pdf_failed", error=str(e)[:300])
        return {
            "pdf_path": None,
            "rendered_html": rendered_html,
            "variables_used": variables,
            "error": str(e)[:300],
        }

    nas_path = None
    try:
        nas_owner_dir = NAS_CONTRACT_BASE / owner_id
        if NAS_CONTRACT_BASE.exists():
            nas_owner_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            nas_dest = nas_owner_dir / filename
            shutil.copy2(str(pdf_path), str(nas_dest))
            nas_path = str(nas_dest)
            logger.info("management_contract_nas_copy", nas_path=nas_path)
    except Exception as e:
        logger.warning("management_contract_nas_copy_failed", error=str(e)[:200])

    return {
        "pdf_path": str(pdf_path),
        "nas_path": nas_path,
        "rendered_html": rendered_html,
        "variables_used": variables,
    }


async def vault_signed_contract(
    agreement_id: str,
    pdf_path: str,
    owner_id: str,
    db: AsyncSession,
) -> Optional[str]:
    """
    Copy a signed management contract to the NAS vault and trigger Qdrant ingestion.
    Called from the post-signature hook in agreements.py.
    Returns the NAS path on success, None on failure.
    """
    import shutil

    nas_owner_dir = NAS_CONTRACT_BASE / owner_id
    try:
        nas_owner_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error("vault_nas_mkdir_failed", error=str(e)[:200])
        return None

    filename = Path(pdf_path).name
    signed_filename = f"signed_{filename}" if not filename.startswith("signed_") else filename
    nas_dest = nas_owner_dir / signed_filename

    try:
        shutil.copy2(pdf_path, str(nas_dest))
        logger.info("contract_vaulted_to_nas", nas_path=str(nas_dest), owner_id=owner_id)
    except Exception as e:
        logger.error("contract_vault_copy_failed", error=str(e)[:200])
        return None

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "Modules" / "CF-03_CounselorCRM"))
        from ingest_docs import ingest_file
        ingest_file(
            str(nas_dest),
            category="management_contract",
            extra_metadata={"owner_id": owner_id},
        )
        logger.info(
            "contract_ingested_to_qdrant",
            nas_path=str(nas_dest),
            owner_id=owner_id,
            collection="legal_library",
        )
    except Exception as e:
        logger.warning("contract_qdrant_ingest_failed", error=str(e)[:300])

    return str(nas_dest)
