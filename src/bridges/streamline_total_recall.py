"""
STREAMLINE TOTAL RECALL — Full Extraction Engine
====================================================
Fortress Prime | Cabin Rentals of Georgia

Pulls everything the current token allows:
  Module 1: ASSETS  — Properties + Amenities  (Guaranteed)
  Module 2: SCHEDULE — Availability & Rates    (Guaranteed)
  Module 3: HISTORY — Reservations & Clients   (Restricted — fails gracefully)

Usage:
    python3 src/bridges/streamline_total_recall.py
"""

import requests
import json
import psycopg2
import os
import sys
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv("/home/admin/Fortress-Prime/.env")

# Streamline Credentials
TOKEN_KEY = os.getenv("STREAMLINE_TOKEN_KEY")
TOKEN_SECRET = os.getenv("STREAMLINE_TOKEN_SECRET")
API_URL = os.getenv("STREAMLINE_API_URL", "https://web.streamlinevrs.com/api/json")

# Database Credentials (Respecting existing config — DB_PASSWORD not DB_PASS)
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")

if not TOKEN_KEY or not TOKEN_SECRET:
    print("❌ CRITICAL: Streamline keys missing from .env")
    sys.exit(1)


def get_db():
    return psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST)


def call_api(method, params=None):
    if params is None:
        params = {}

    payload = {
        "methodName": method,
        "params": {
            "token_key": TOKEN_KEY,
            "token_secret": TOKEN_SECRET
        }
    }
    payload["params"].update(params)

    try:
        res = requests.post(
            API_URL, json=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=30
        )
        if res.status_code == 200:
            data = res.json()
            # Check for Streamline error codes
            status = data.get("status", {})
            if isinstance(status, dict) and status.get("code"):
                code = status["code"]
                desc = status.get("description", "Unknown")
                print(f"      ⚠️  API Error ({method}): [{code}] {desc}")
                return None
            if "error" in data:
                print(f"      ⚠️  API Error ({method}): {data['error']}")
                return None
            return data.get("data", [])
        elif res.status_code == 429:
            print("      ⏳ Rate Limited. Sleeping 5s...")
            time.sleep(5)
            return None
        else:
            print(f"      ❌ HTTP {res.status_code} for {method}")
            return None
    except Exception as e:
        print(f"      🔴 Network Error ({method}): {e}")
        return None


# ---------------------------------------------------------------------------
# MODULE 1: ASSETS (Guaranteed Access)
# ---------------------------------------------------------------------------
def sync_assets():
    print("\n" + "=" * 60)
    print("🏠 MODULE 1: ASSET EXTRACTION (Properties & Amenities)")
    print("=" * 60)

    conn = get_db()
    cur = conn.cursor()

    # --- Properties ---
    raw_data = call_api("GetPropertyList", {"status_id": 1})

    # Streamline nests: data -> property -> [list of dicts]
    if isinstance(raw_data, dict):
        props = raw_data.get("property", raw_data.get("properties", []))
    elif isinstance(raw_data, list):
        props = raw_data
    else:
        props = []

    if props:
        count = 0
        for p in props:
            pid = str(p.get("id", ""))
            name = p.get("name", "")
            addr = p.get("address", "")
            city = p.get("city", "")
            state = p.get("state_name", "")
            zipcode = p.get("zip", "")
            beds = p.get("bedrooms_number")
            baths = p.get("bathrooms_number")
            max_occ = p.get("max_occupants")
            lat = p.get("location_latitude")
            lon = p.get("location_longitude")
            status_name = p.get("status_name", "")
            status_id = p.get("status_id")
            img_path = p.get("default_image_path", "")
            unit_code = p.get("unit_code", "")
            lock_box = p.get("lock_box_code", "")
            wifi_key = p.get("wifi_security_key", "")
            sq_ft = p.get("square_foots")
            max_adults = p.get("max_adults")
            max_pets = p.get("max_pets")
            desc_short = p.get("short_description", "")
            seo_title = p.get("seo_title", "")
            flyer_url = p.get("flyer_url", "")
            company_id = p.get("company_id")
            owning_type_id = p.get("owning_type_id")
            lodging_type_id = p.get("lodging_type_id")
            location_area = p.get("location_area_name", "")
            resort_area = p.get("location_resort_name", "")
            view_name = p.get("view_name", "")
            country = p.get("country_name", "")
            creation_date = p.get("creation_date")

            # Use streamline_id for matching; property_id is our internal slug (underscores)
            slug = name.lower().replace(" ", "_").replace("'", "").replace("-", "_")[:50] if name else pid

            cur.execute("""
                INSERT INTO ops_properties (
                    property_id, streamline_id, name, internal_name, address,
                    city, state_name, zip, country_name,
                    bedrooms, bathrooms, max_occupants, max_adults, max_pets,
                    latitude, longitude, square_feet,
                    status_name, status_id, unit_code,
                    location_area_name, resort_area_name, view_name,
                    seo_title, description_short, flyer_url, default_image_url,
                    company_id, owning_type_id, lodging_type_id,
                    access_code_wifi, access_code_door,
                    last_synced, raw_json
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    NOW(), %s
                )
                ON CONFLICT (streamline_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    internal_name = EXCLUDED.internal_name,
                    address = EXCLUDED.address,
                    city = EXCLUDED.city,
                    state_name = EXCLUDED.state_name,
                    zip = EXCLUDED.zip,
                    country_name = EXCLUDED.country_name,
                    bedrooms = EXCLUDED.bedrooms,
                    bathrooms = EXCLUDED.bathrooms,
                    max_occupants = EXCLUDED.max_occupants,
                    max_adults = EXCLUDED.max_adults,
                    max_pets = EXCLUDED.max_pets,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    square_feet = EXCLUDED.square_feet,
                    status_name = EXCLUDED.status_name,
                    status_id = EXCLUDED.status_id,
                    unit_code = EXCLUDED.unit_code,
                    location_area_name = EXCLUDED.location_area_name,
                    resort_area_name = EXCLUDED.resort_area_name,
                    view_name = EXCLUDED.view_name,
                    seo_title = EXCLUDED.seo_title,
                    description_short = EXCLUDED.description_short,
                    flyer_url = EXCLUDED.flyer_url,
                    default_image_url = EXCLUDED.default_image_url,
                    company_id = EXCLUDED.company_id,
                    owning_type_id = EXCLUDED.owning_type_id,
                    lodging_type_id = EXCLUDED.lodging_type_id,
                    access_code_wifi = EXCLUDED.access_code_wifi,
                    access_code_door = EXCLUDED.access_code_door,
                    last_synced = NOW(),
                    raw_json = EXCLUDED.raw_json;
            """, (
                slug, int(pid) if pid.isdigit() else None, name, name, addr,
                city, state, zipcode, country,
                beds, baths, max_occ, max_adults, max_pets,
                lat, lon, sq_ft,
                status_name, status_id, unit_code,
                location_area, resort_area, view_name,
                seo_title, desc_short, flyer_url, img_path,
                company_id, owning_type_id, lodging_type_id,
                wifi_key, lock_box,
                json.dumps(p)
            ))
            count += 1
            print(f"      {name:35s} (ID: {pid}) — {beds}BR/{baths}BA, {status_name}")
        conn.commit()
        print(f"\n   ✅ Synced {count} Properties to ops_properties.")

        # --- Amenities (Opportunistic scan) ---
        print("\n   🏷️  Scanning Amenities (sample of 3)...")
        amenity_total = 0
        for p in props[:3]:
            pid = str(p.get("id", ""))
            pname = p.get("name", pid)
            amenities = call_api("GetPropertyAmenities", {"unit_id": pid})
            if amenities:
                if isinstance(amenities, dict):
                    alist = amenities.get("amenity", amenities.get("amenities", []))
                    if isinstance(alist, dict):
                        alist = [alist]
                elif isinstance(amenities, list):
                    alist = amenities
                else:
                    alist = []
                amenity_total += len(alist)
                print(f"      {pname}: {len(alist)} amenities")
            time.sleep(0.3)

        if amenity_total > 0:
            print(f"   ✅ Sampled {amenity_total} amenities. Full scan available.")
        else:
            print("   ℹ️  No amenity data returned (may need different method name).")
    else:
        print("   ❌ Property list returned empty or failed.")

    conn.close()
    return props


# ---------------------------------------------------------------------------
# MODULE 2: SCHEDULE (Guaranteed Access via Rates/Availability)
# ---------------------------------------------------------------------------
def sync_calendar():
    print("\n" + "=" * 60)
    print("📅 MODULE 2: CALENDAR EXTRACTION (Availability & Rates)")
    print("=" * 60)

    conn = get_db()
    cur = conn.cursor()

    # Get all property IDs from DB
    cur.execute("SELECT property_id, streamline_id, name FROM ops_properties WHERE streamline_id IS NOT NULL")
    rows = cur.fetchall()

    if not rows:
        print("   ⚠️  No properties with streamline_id in DB. Run Module 1 first.")
        conn.close()
        return

    start_date = datetime.now().strftime("%m/%d/%Y")
    end_date = (datetime.now() + timedelta(days=90)).strftime("%m/%d/%Y")

    print(f"   📆 Window: {start_date} → {end_date}")
    print(f"   🏠 Scanning {len(rows)} properties...\n")

    total_booked = 0
    total_available = 0

    for prop_id, stream_id, name in rows:
        # GetPropertyRates uses unit_id and startdate/enddate (no underscores)
        data = call_api("GetPropertyRates", {
            "unit_id": str(stream_id),
            "startdate": start_date,
            "enddate": end_date
        })

        if data and isinstance(data, dict):
            booked_count = sum(1 for d in data.values()
                               if isinstance(d, dict) and str(d.get("booked", "0")) == "1")
            avail_count = sum(1 for d in data.values()
                              if isinstance(d, dict) and str(d.get("booked", "0")) == "0")
            total_booked += booked_count
            total_available += avail_count
            occ_pct = (booked_count / max(booked_count + avail_count, 1)) * 100
            bar = "█" * int(occ_pct / 5) + "░" * (20 - int(occ_pct / 5))
            print(f"      {name:35s} [{bar}] {occ_pct:5.1f}%  ({booked_count}B / {avail_count}A)")
        elif data and isinstance(data, list):
            total_booked += len(data)
            print(f"      {name:35s} → {len(data)} date entries")
        else:
            print(f"      {name:35s} → ⚠️  No data")

        time.sleep(0.3)

    print(f"\n   ✅ Calendar Scan Complete.")
    print(f"      Total Booked Nights:    {total_booked}")
    print(f"      Total Available Nights:  {total_available}")
    if total_booked + total_available > 0:
        fleet_occ = (total_booked / (total_booked + total_available)) * 100
        print(f"      Fleet Occupancy (90d):   {fleet_occ:.1f}%")

    conn.close()


# ---------------------------------------------------------------------------
# MODULE 3: HISTORY (Restricted — Fails Gracefully)
# ---------------------------------------------------------------------------
def sync_history():
    print("\n" + "=" * 60)
    print("📜 MODULE 3: HISTORY EXTRACTION (Reservations & Clients)")
    print("   ⚠️  These methods may be restricted on current token.")
    print("=" * 60)

    methods_to_probe = [
        ("GetClientList",      {"page": 1, "page_size": 10}),
        ("GetReservationList",  {"start_date": "01/01/2025", "end_date": "12/31/2025", "page": 1, "page_size": 10}),
        ("GetOwnerStatement",   {"page": 1, "page_size": 10}),
        ("GetTransactionList",  {"page": 1, "page_size": 10}),
        ("GetChargeList",       {"page": 1, "page_size": 10}),
        ("GetInvoiceList",      {"page": 1, "page_size": 10}),
    ]

    accessible = []
    denied = []

    for method, params in methods_to_probe:
        data = call_api(method, params)
        if data is not None:
            count = len(data) if isinstance(data, (list, dict)) else 0
            print(f"   🎉 {method:30s} → ACCESS GRANTED ({count} records)")
            accessible.append(method)
        else:
            print(f"   🔒 {method:30s} → ACCESS DENIED")
            denied.append(method)
        time.sleep(0.5)

    print(f"\n   📊 History Probe Results:")
    print(f"      Accessible: {len(accessible)} methods  {accessible}")
    print(f"      Denied:     {len(denied)} methods  {denied}")

    if denied:
        print("\n   💡 To unlock denied methods, request a token upgrade")
        print("      from Streamline Partner Portal → API → Permissions.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  🚀 FORTRESS PRIME: TOTAL RECALL — FULL EXTRACTION")
    print(f"  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🔑 Token: {TOKEN_KEY[:8]}...{TOKEN_KEY[-4:]}")
    print("=" * 60)

    t0 = time.time()

    sync_assets()      # Module 1 — Should WORK
    sync_calendar()    # Module 2 — Should WORK
    sync_history()     # Module 3 — Will likely FAIL gracefully

    elapsed = time.time() - t0
    print("\n" + "=" * 60)
    print(f"  🏁 TOTAL RECALL COMPLETE in {elapsed:.1f}s")
    print("=" * 60)
