#!/usr/bin/env python3
"""
Idempotently seed sovereign tax and fee primitives into fortress_prod.
"""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[2]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def load_environment() -> None:
    for env_file in (
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
    ):
        if env_file.exists():
            load_dotenv(env_file, override=True)


load_environment()

from backend.core.database import AsyncSessionLocal, close_db
from backend.models.financial_primitives import Fee, PropertyFee, PropertyTax, Tax
from backend.models.property import Property


TWO_PLACES = Decimal("0.01")
BASELINE_TAX_NAME = "Fannin County Lodging Tax"
BASELINE_TAX_RATE = Decimal("12.00")
STANDARD_CLEANING_FEE_NAME = "Standard Cleaning Fee"
STANDARD_CLEANING_FEE_AMOUNT = Decimal("225.00")
PET_FEE_NAME = "Pet Fee"
PET_FEE_AMOUNT = Decimal("75.00")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


async def _upsert_tax(name: str, percentage_rate: Decimal) -> Tax:
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(Tax).where(Tax.name == name).limit(1))
        ).scalar_one_or_none()
        normalized_rate = _money(percentage_rate)
        if existing is not None:
            existing.percentage_rate = normalized_rate
            existing.is_active = True
            await session.commit()
            await session.refresh(existing)
            return existing

        tax = Tax(
            name=name,
            percentage_rate=normalized_rate,
            is_active=True,
        )
        session.add(tax)
        await session.commit()
        await session.refresh(tax)
        return tax


async def _upsert_fee(name: str, amount: Decimal, *, is_pet_fee: bool) -> Fee:
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(Fee).where(Fee.name == name).limit(1))
        ).scalar_one_or_none()
        normalized_amount = _money(amount)
        if existing is not None:
            existing.flat_amount = normalized_amount
            existing.is_pet_fee = is_pet_fee
            existing.is_active = True
            await session.commit()
            await session.refresh(existing)
            return existing

        fee = Fee(
            name=name,
            flat_amount=normalized_amount,
            is_pet_fee=is_pet_fee,
            is_active=True,
        )
        session.add(fee)
        await session.commit()
        await session.refresh(fee)
        return fee


async def seed_financial_primitives() -> int:
    if not os.getenv("DATABASE_URL", "").strip():
        raise RuntimeError("DATABASE_URL is not set after loading environment files.")

    tax = await _upsert_tax(BASELINE_TAX_NAME, BASELINE_TAX_RATE)
    cleaning_fee = await _upsert_fee(
        STANDARD_CLEANING_FEE_NAME,
        STANDARD_CLEANING_FEE_AMOUNT,
        is_pet_fee=False,
    )
    pet_fee = await _upsert_fee(
        PET_FEE_NAME,
        PET_FEE_AMOUNT,
        is_pet_fee=True,
    )

    async with AsyncSessionLocal() as session:
        properties = list(
            (
                await session.execute(
                    select(Property).where(Property.is_active.is_(True)).order_by(Property.name.asc())
                )
            ).scalars().all()
        )

        linked_taxes = 0
        linked_fees = 0
        for property_record in properties:
            property_tax = (
                await session.execute(
                    select(PropertyTax)
                    .where(PropertyTax.property_id == property_record.id, PropertyTax.tax_id == tax.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if property_tax is None:
                session.add(
                    PropertyTax(
                        property_id=property_record.id,
                        tax_id=tax.id,
                        is_active=True,
                    )
                )
                linked_taxes += 1
            else:
                property_tax.is_active = True

            for fee in (cleaning_fee, pet_fee):
                property_fee = (
                    await session.execute(
                        select(PropertyFee)
                        .where(PropertyFee.property_id == property_record.id, PropertyFee.fee_id == fee.id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if property_fee is None:
                    session.add(
                        PropertyFee(
                            property_id=property_record.id,
                            fee_id=fee.id,
                            is_active=True,
                        )
                    )
                    linked_fees += 1
                else:
                    property_fee.is_active = True

        await session.commit()

    print(
        "[seed] financial primitives ready: "
        f"tax='{tax.name}' rate={tax.percentage_rate} "
        f"cleaning_fee='{cleaning_fee.name}' amount={cleaning_fee.flat_amount} "
        f"pet_fee='{pet_fee.name}' amount={pet_fee.flat_amount} "
        f"properties_linked={len(properties)} "
        f"new_tax_links={linked_taxes} "
        f"new_fee_links={linked_fees}"
    )
    return 0


async def amain() -> int:
    try:
        return await seed_financial_primitives()
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
