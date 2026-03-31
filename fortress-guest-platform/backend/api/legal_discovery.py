"""
Phase 2 discovery draft API.
"""
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from backend.core.database import AsyncSessionLocal
from backend.core.security import require_manager_or_admin
from backend.services.legal_discovery_engine import LegalDiscoveryEngine
from backend.services.legal_discovery_validator import LegalDiscoveryValidator

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


class DiscoveryDraftRequest(BaseModel):
    # New dashboard payload compatibility.
    local_rules_cap: int = Field(default=25, ge=1, le=25)
    # Legacy payload compatibility.
    target_entity: str = Field(default="Opposing Party", min_length=1, max_length=255)
    max_items: int = Field(default=10, ge=1, le=100)


@router.post("/cases/{case_slug}/discovery/draft-pack", summary="Generate discovery draft pack from legal case graph")
async def generate_discovery_draft_pack(case_slug: str, body: DiscoveryDraftRequest):
    async with AsyncSessionLocal() as db:
        try:
            # Use Rule 26 local cap when provided by the new dashboard contract.
            effective_max = int(body.local_rules_cap or body.max_items or 25)
            effective_max = max(1, min(effective_max, 25))
            return await LegalDiscoveryEngine.generate_draft_pack(
                case_slug=case_slug,
                target_entity=body.target_entity or "Opposing Party",
                max_items=effective_max,
                db=db,
            )
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to generate discovery draft pack: {str(exc)[:220]}") from exc


@router.get("/cases/{case_slug}/discovery/packs", summary="List discovery draft packs for case")
async def list_discovery_packs(case_slug: str):
    async with AsyncSessionLocal() as db:
        try:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT id, case_slug, target_entity, status, created_at
                        FROM legal.discovery_draft_packs_v2
                        WHERE case_slug = :case_slug
                        ORDER BY created_at DESC
                        """
                    ),
                    {"case_slug": case_slug},
                )
            ).mappings().all()
            packs = []
            for row in rows:
                packs.append(
                    {
                        "id": str(row["id"]),
                        "case_slug": row["case_slug"],
                        "target_entity": row["target_entity"],
                        "status": row["status"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    }
                )
            return {"case_slug": case_slug, "count": len(packs), "packs": packs}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to list discovery packs: {str(exc)[:220]}") from exc


@router.get("/cases/{case_slug}/discovery/packs/{pack_id}", summary="Get one discovery draft pack with items")
async def get_discovery_pack(case_slug: str, pack_id: str):
    async with AsyncSessionLocal() as db:
        try:
            pack = (
                await db.execute(
                    text(
                        """
                        SELECT id, case_slug, target_entity, status, created_at
                        FROM legal.discovery_draft_packs_v2
                        WHERE case_slug = :case_slug AND id = CAST(:pack_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"case_slug": case_slug, "pack_id": pack_id},
                )
            ).mappings().first()
            if not pack:
                raise HTTPException(status_code=404, detail=f"Discovery pack not found: {pack_id}")

            item_rows = (
                await db.execute(
                    text(
                        """
                        SELECT id, category, content, rationale_from_graph, sequence_number,
                               lethality_score, proportionality_score, correction_notes
                        FROM legal.discovery_draft_items_v2
                        WHERE pack_id = CAST(:pack_id AS uuid)
                        ORDER BY sequence_number ASC
                        """
                    ),
                    {"pack_id": pack_id},
                )
            ).mappings().all()

            items = []
            for row in item_rows:
                items.append(
                    {
                        "id": str(row["id"]),
                        "category": row["category"],
                        "content": row["content"],
                        "rationale_from_graph": row["rationale_from_graph"],
                        "sequence_number": row["sequence_number"],
                        "lethality_score": row["lethality_score"],
                        "proportionality_score": row["proportionality_score"],
                        "correction_notes": row["correction_notes"],
                    }
                )

            return {
                "pack": {
                    "id": str(pack["id"]),
                    "case_slug": pack["case_slug"],
                    "target_entity": pack["target_entity"],
                    "status": pack["status"],
                    "created_at": pack["created_at"].isoformat() if pack["created_at"] else None,
                },
                "items": items,
            }
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to load discovery pack: {str(exc)[:220]}") from exc


@router.post("/cases/{case_slug}/discovery/packs/{pack_id}/validate", summary="Validate and score discovery draft pack with DeepSeek")
async def validate_discovery_pack(case_slug: str, pack_id: str):
    async with AsyncSessionLocal() as db:
        try:
            return await LegalDiscoveryValidator.validate_and_score_pack(
                pack_id=pack_id,
                case_slug=case_slug,
                db=db,
            )
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to validate discovery pack: {str(exc)[:220]}") from exc

