import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from backend.core.config import settings
from backend.models import DamageClaim, Reservation, Guest, Property
from backend.services.damage_workflow import process_damage_claim

async def main():
    # Bypass database.py entirely and wire the engine directly
    db_url = settings.database_url.replace('postgresql://', 'postgresql+asyncpg://')
    engine = create_async_engine(db_url)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("Searching for Scott Lovell at Riverview Lodge...")
        query = (
            select(DamageClaim)
            .join(Reservation, DamageClaim.reservation_id == Reservation.id)
            .join(Guest, DamageClaim.guest_id == Guest.id)
            .join(Property, DamageClaim.property_id == Property.id)
            .where(Guest.last_name.ilike("%Lovell%"))
            .where(Property.name.ilike("%Riverview%"))
        )
        result = await db.execute(query)
        claim = result.scalars().first()

        if not claim:
            print("ERROR: Could not find the damage claim for Scott Lovell at Riverview.")
            return

        print(f"TARGET ACQUIRED -> Reservation ID: {claim.reservation_id}")
        print(f"Staff Notes: {claim.damage_description}")
        print("\nFiring Riverview Protocol. The Council is deliberating...")

        # Fire the multi-agent workflow
        updated_claim = await process_damage_claim(
            reservation_id=claim.reservation_id,
            staff_notes=claim.damage_description,
            db=db,
            reported_by=claim.reported_by,
            damage_areas=claim.damage_areas,
            estimated_cost=claim.estimated_cost
        )

        print("\n" + "═"*60)
        print(" COUNCIL APPROVED LEGAL DRAFT ".center(60, "═"))
        print("═"*60 + "\n")
        print(updated_claim.legal_draft)
        print("\n" + "═"*60)
        
        # Safely print audit trail if it exists
        audit_trail = getattr(updated_claim, 'agreement_clauses', "No audit trail generated.")
        print(f"Audit Trail: {audit_trail}")

if __name__ == "__main__":
    asyncio.run(main())
