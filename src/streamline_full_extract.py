#!/usr/bin/env python3
"""
Streamline VRS — Full Historical Data Extractor
================================================
Pulls every accessible byte of data from Streamline VRS and archives
it as raw JSON on the NAS.  This is YOUR data — we're taking custody.

Extraction Plan:
  1. GetPropertyList        → All 14 properties (master list)
  2. GetPropertyInfo        → Per-property detail (each unit)
  3. GetPropertyAmenities   → Per-property amenities
  4. GetPropertyGalleryImages → Per-property photos metadata
  5. GetPropertyRates       → Per-property pricing/seasons
  6. GetReservations        → ALL reservations (paginated, multi-year)
  7. GetBlockedDaysForUnit  → Availability per property (multi-year)
  8. GetWorkOrders          → All maintenance records
  9. GetOwnerList           → Owner directory
 10. GetGuestReviews        → All guest reviews

Output: /mnt/fortress_nas/fortress_data/model_vault/streamline_archive/
"""

import asyncio
import json
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

import httpx

API_URL = "https://web.streamlinevrs.com/api/json"
TOKEN_KEY = os.getenv(
    "STREAMLINE_API_KEY", "f97677a4725bc121cf83011825b0ea46"
)
TOKEN_SECRET = os.getenv(
    "STREAMLINE_API_SECRET", "54f7236b53f30e60a28c7aaadd31e8f17b532e00"
)

NAS_BASE = Path("/mnt/fortress_nas/fortress_data/model_vault/streamline_archive")
TIMEOUT = httpx.Timeout(60.0, connect=15.0)

stats = {
    "started_at": None,
    "methods_called": 0,
    "bytes_saved": 0,
    "files_written": 0,
    "errors": [],
    "reservation_count": 0,
}


def save_json(subdir: str, filename: str, data) -> int:
    path = NAS_BASE / subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    path.write_text(raw, encoding="utf-8")
    size = len(raw)
    stats["bytes_saved"] += size
    stats["files_written"] += 1
    return size


async def call_api(client: httpx.AsyncClient, method: str, extra=None):
    params = {"token_key": TOKEN_KEY, "token_secret": TOKEN_SECRET}
    if extra:
        params.update(extra)
    payload = {"methodName": method, "params": params}

    resp = await client.post(API_URL, json=payload)
    data = resp.json()
    stats["methods_called"] += 1

    if "status" in data and isinstance(data["status"], dict):
        code = data["status"].get("code", "")
        if code == "E0014":
            return None
        if code.startswith("E"):
            raise RuntimeError(f"{method} error {code}: {data['status'].get('description')}")

    return data.get("data", data)


async def extract_properties(client):
    print("\n[1/10] GetPropertyList — master property list...")
    data = await call_api(client, "GetPropertyList")
    props = data.get("property", []) if isinstance(data, dict) else []
    if isinstance(props, dict):
        props = [props]
    save_json("properties", "property_list.json", data)
    print(f"       → {len(props)} properties saved")
    return props


async def extract_property_details(client, props):
    print(f"\n[2/10] GetPropertyInfo — detail for each of {len(props)} properties...")
    all_detail = []
    for p in props:
        uid = p.get("id")
        if not uid:
            continue
        try:
            data = await call_api(client, "GetPropertyInfo", {"unit_id": str(uid)})
            if data:
                save_json("properties", f"property_detail_{uid}.json", data)
                all_detail.append(data)
        except Exception as e:
            stats["errors"].append(f"PropertyInfo {uid}: {e}")
    print(f"       → {len(all_detail)} property details saved")
    return all_detail


async def extract_amenities(client, props):
    print(f"\n[3/10] GetPropertyAmenities — per-property amenities...")
    count = 0
    for p in props:
        uid = p.get("id")
        if not uid:
            continue
        try:
            data = await call_api(client, "GetPropertyAmenities", {"unit_id": str(uid)})
            if data:
                save_json("properties", f"amenities_{uid}.json", data)
                count += 1
        except Exception as e:
            stats["errors"].append(f"Amenities {uid}: {e}")
    print(f"       → {count} amenity files saved")


async def extract_gallery(client, props):
    print(f"\n[4/10] GetPropertyGalleryImages — photo metadata...")
    count = 0
    total_images = 0
    for p in props:
        uid = p.get("id")
        if not uid:
            continue
        try:
            data = await call_api(client, "GetPropertyGalleryImages", {"unit_id": str(uid)})
            if data:
                save_json("properties", f"gallery_{uid}.json", data)
                imgs = data.get("image", []) if isinstance(data, dict) else []
                if isinstance(imgs, dict):
                    imgs = [imgs]
                total_images += len(imgs)
                count += 1
        except Exception as e:
            stats["errors"].append(f"Gallery {uid}: {e}")
    print(f"       → {count} galleries saved, {total_images} total images cataloged")


async def extract_rates(client, props):
    print(f"\n[5/10] GetPropertyRates — pricing and season data...")
    count = 0
    for p in props:
        uid = p.get("id")
        if not uid:
            continue
        try:
            data = await call_api(client, "GetPropertyRates", {"unit_id": str(uid)})
            if data:
                save_json("properties", f"rates_{uid}.json", data)
                count += 1
        except Exception as e:
            stats["errors"].append(f"Rates {uid}: {e}")
    print(f"       → {count} rate files saved")


async def extract_reservations(client):
    """Pull ALL reservations going back to the beginning of time."""
    print("\n[6/10] GetReservations — FULL HISTORICAL PULL...")

    # Go back to 2015 (or whenever CROG started) through end of 2027
    start_year = 2015
    end_year = 2027
    all_reservations = []

    for year in range(start_year, end_year + 1):
        for half in [0, 1]:
            if half == 0:
                sd = f"01/01/{year}"
                ed = f"06/30/{year}"
                label = f"{year}-H1"
            else:
                sd = f"07/01/{year}"
                ed = f"12/31/{year}"
                label = f"{year}-H2"

            # Skip future periods past current
            check_date = date(year, 7 if half else 1, 1)
            if check_date > date.today() + timedelta(days=365):
                continue

            page = 1
            period_count = 0
            while True:
                try:
                    data = await call_api(client, "GetReservations", {
                        "startdate": sd,
                        "enddate": ed,
                        "return_full": "true",
                        "page": str(page),
                    })
                except Exception as e:
                    stats["errors"].append(f"Reservations {label} p{page}: {e}")
                    break

                if not data:
                    break

                raw_list = data.get("reservations", []) if isinstance(data, dict) else []
                if isinstance(raw_list, dict):
                    raw_list = [raw_list]

                if not raw_list:
                    break

                all_reservations.extend(raw_list)
                period_count += len(raw_list)

                save_json("reservations", f"reservations_{label}_page{page}.json", {
                    "period": label,
                    "page": page,
                    "count": len(raw_list),
                    "reservations": raw_list,
                })

                pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
                total_pages = int(pagination.get("total_pages", 1))

                if page >= total_pages:
                    break
                page += 1
                await asyncio.sleep(0.5)  # rate limit courtesy

            if period_count > 0:
                print(f"       {label}: {period_count:,} reservations ({page} pages)")

    # Save combined master file
    save_json("reservations", "ALL_reservations_master.json", {
        "extracted_at": datetime.utcnow().isoformat(),
        "total_count": len(all_reservations),
        "reservations": all_reservations,
    })
    stats["reservation_count"] = len(all_reservations)
    print(f"       → TOTAL: {len(all_reservations):,} reservations archived")
    return all_reservations


async def extract_availability(client, props):
    """Pull blocked days going back several years per property."""
    print(f"\n[7/10] GetBlockedDaysForUnit — availability history per property...")
    count = 0
    total_blocks = 0

    for p in props:
        uid = p.get("id")
        if not uid:
            continue
        try:
            # Go back 3 years, forward 1 year
            data = await call_api(client, "GetBlockedDaysForUnit", {
                "unit_id": str(uid),
                "startdate": "01/01/2023",
                "enddate": "12/31/2027",
            })
            if data:
                save_json("availability", f"blocked_days_{uid}.json", data)
                blocked = (data.get("blocked_days", {}) or {}).get("blocked", [])
                if isinstance(blocked, dict):
                    blocked = [blocked]
                total_blocks += len(blocked)
                count += 1
        except Exception as e:
            stats["errors"].append(f"Availability {uid}: {e}")

    print(f"       → {count} properties, {total_blocks:,} booking blocks archived")


async def extract_work_orders(client):
    print("\n[8/10] GetWorkOrders — all maintenance records...")
    data = await call_api(client, "GetWorkOrders")
    if data:
        size = save_json("work_orders", "work_orders_all.json", data)
        m = data.get("maintenances", {}) if isinstance(data, dict) else {}
        wos = m.get("maintenance", []) if isinstance(m, dict) else []
        if isinstance(wos, dict):
            wos = [wos]
        print(f"       → {len(wos)} work orders saved ({size:,} bytes)")
    else:
        print("       → No work order data returned")


async def extract_owners(client):
    print("\n[9/10] GetOwnerList — property owner directory...")
    data = await call_api(client, "GetOwnerList")
    if data:
        owners = data.get("owner", []) if isinstance(data, dict) else []
        if isinstance(owners, dict):
            owners = [owners]
        save_json("owners", "owner_list.json", data)
        print(f"       → {len(owners)} owners saved")
    else:
        print("       → No owner data returned")


async def extract_reviews(client, props):
    print(f"\n[10/10] GetGuestReviews — all guest reviews...")
    all_reviews = []
    data = await call_api(client, "GetGuestReviews")
    if data:
        reviews = data.get("review", []) if isinstance(data, dict) else []
        if isinstance(reviews, dict):
            reviews = [reviews]
        all_reviews.extend(reviews)
        save_json("reviews", "reviews_all.json", data)

    # Also try per-property
    for p in props:
        uid = p.get("id")
        if not uid:
            continue
        try:
            data = await call_api(client, "GetGuestReviews", {"unit_id": str(uid)})
            if data:
                reviews = data.get("review", []) if isinstance(data, dict) else []
                if isinstance(reviews, dict):
                    reviews = [reviews]
                if reviews:
                    save_json("reviews", f"reviews_{uid}.json", data)
                    all_reviews.extend(reviews)
        except Exception as e:
            stats["errors"].append(f"Reviews {uid}: {e}")

    print(f"       → {len(all_reviews)} reviews archived")


async def main():
    stats["started_at"] = datetime.utcnow().isoformat()
    print("=" * 70)
    print("STREAMLINE VRS — FULL HISTORICAL DATA EXTRACTION")
    print(f"Target: {NAS_BASE}")
    print(f"Started: {stats['started_at']}")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Phase 1: Properties (master list)
        props = await extract_properties(client)

        # Phase 2-5: Per-property data
        await extract_property_details(client, props)
        await extract_amenities(client, props)
        await extract_gallery(client, props)
        await extract_rates(client, props)

        # Phase 6: ALL reservations (the big one)
        await extract_reservations(client)

        # Phase 7: Availability
        await extract_availability(client, props)

        # Phase 8: Work Orders
        await extract_work_orders(client)

        # Phase 9: Owners
        await extract_owners(client)

        # Phase 10: Reviews
        await extract_reviews(client, props)

    # Final summary
    stats["completed_at"] = datetime.utcnow().isoformat()
    save_json(".", "extraction_manifest.json", stats)

    print("\n" + "=" * 70)
    print("EXTRACTION COMPLETE")
    print("=" * 70)
    print(f"  API calls made:     {stats['methods_called']:,}")
    print(f"  Files written:      {stats['files_written']:,}")
    print(f"  Data archived:      {stats['bytes_saved'] / 1024 / 1024:.1f} MB")
    print(f"  Reservations:       {stats['reservation_count']:,}")
    print(f"  Errors:             {len(stats['errors'])}")
    if stats["errors"]:
        print("  First 5 errors:")
        for e in stats["errors"][:5]:
            print(f"    - {e}")
    print(f"  Archive location:   {NAS_BASE}")
    print(f"  Completed:          {stats['completed_at']}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
