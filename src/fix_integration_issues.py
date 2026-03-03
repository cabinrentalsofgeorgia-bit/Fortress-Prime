#!/usr/bin/env python3
"""
Fix all Streamline + RueBaRue integration issues identified in the audit.
1. Sync Streamline property data into property_sms_config
2. Normalize dirty cabin names in message_archive
3. Improve property linkage for unlinked messages
4. Load scheduler/master guide into property_sms_config templates
5. Clean up orphaned/retired properties
"""
import json, os, re
import psycopg2
from datetime import datetime

DB_URL = os.getenv("DATABASE_URL", "")
if not DB_URL:
    _db_host = os.getenv("DB_HOST", "localhost")
    _db_port = os.getenv("DB_PORT", "5432")
    _db_name = os.getenv("DB_NAME", "fortress_db")
    _db_user = os.getenv("DB_USER", "miner_bot")
    _db_pass = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))
    if _db_pass:
        DB_URL = f"postgresql://{_db_user}:{_db_pass}@{_db_host}:{_db_port}/{_db_name}"
    else:
        DB_URL = f"postgresql://{_db_user}@{_db_host}:{_db_port}/{_db_name}"
DATA_DIR = "/home/admin/Fortress-Prime/data/ruebarue"


def get_conn():
    return psycopg2.connect(DB_URL)


# ═══════════════════════════════════════════════════════════════
# FIX 1: Sync Streamline property data -> property_sms_config
# ═══════════════════════════════════════════════════════════════
def fix_sync_streamline_properties():
    print("=" * 70)
    print("FIX 1: Sync Streamline property data -> property_sms_config")
    print("=" * 70)
    conn = get_conn()
    cur = conn.cursor()

    # Get all active Streamline properties with their rich data
    cur.execute("""
        SELECT name, internal_name, address, city, state_name, zip,
               access_code_wifi, access_code_door, bedrooms, bathrooms,
               max_occupants, max_adults, max_pets, description_short,
               latitude, longitude, location_area_name, flyer_url,
               streamline_id
        FROM ops_properties
        WHERE status_name = 'Active'
    """)
    sl_props = cur.fetchall()
    print(f"  Found {len(sl_props)} active Streamline properties")

    updated = 0
    for row in sl_props:
        (name, iname, addr, city, state, zipcode,
         wifi, door, beds, baths, max_occ, max_adults, max_pets,
         desc, lat, lon, area, flyer_url, sl_id) = row

        # Build full address
        full_addr = addr or ""
        if city:
            full_addr += f", {city}"
        if state:
            full_addr += f", {state}"
        if zipcode:
            full_addr += f" {zipcode}"

        # Parse door code (strip "Code: " prefix)
        door_code = ""
        if door:
            door_code = door.replace("Code: ", "").replace("Code:", "").strip()

        # Build check-in instructions from scheduler templates
        checkin_text = f"Check-in is at 3:30 PM. Your door code will be texted at 3:15 PM along with the WiFi password."
        if door_code:
            checkin_text += f"\nDoor Code: {door_code}"
        if wifi:
            checkin_text += f"\nWiFi Password: {wifi}"

        # Build house rules from master guide
        house_rules = "Check-out is at 10:00 AM.\nNo smoking inside the property.\n"
        if max_occ:
            house_rules += f"Maximum occupancy: {int(max_occ)} guests.\n"
        if max_pets:
            house_rules += f"Maximum pets: {int(max_pets)}.\n"
        else:
            house_rules += "No pets allowed.\n"
        house_rules += "Parking on the right of way of any road or street overnight is prohibited."

        # Build description
        property_desc = desc or ""
        if beds:
            property_desc += f"\n{int(beds)} bedrooms, {baths} bathrooms"
        if max_occ:
            property_desc += f", sleeps {int(max_occ)}"

        # Match to property_sms_config by name
        match_name = iname or name
        cur.execute("SELECT id FROM property_sms_config WHERE property_name = %s", (match_name,))
        row = cur.fetchone()

        if row:
            cur.execute("""
                UPDATE property_sms_config SET
                    address = %s,
                    wifi_password = COALESCE(NULLIF(%s, ''), wifi_password),
                    door_code = COALESCE(NULLIF(%s, ''), door_code),
                    checkin_instructions = %s,
                    house_rules = %s,
                    updated_at = NOW()
                WHERE property_name = %s
            """, (full_addr, wifi, door_code, checkin_text, house_rules, match_name))
            updated += 1
            print(f"  Updated: {match_name}")
        else:
            print(f"  SKIP (no SMS config): {match_name}")

    conn.commit()
    conn.close()
    print(f"  -> {updated} properties synced")


# ═══════════════════════════════════════════════════════════════
# FIX 2: Normalize dirty cabin names in message_archive
# ═══════════════════════════════════════════════════════════════
def fix_dirty_cabin_names():
    print()
    print("=" * 70)
    print("FIX 2: Normalize dirty cabin names in message_archive")
    print("=" * 70)
    conn = get_conn()
    cur = conn.cursor()

    # Canonical property names
    canonical = [
        "Above the Timberline", "Aska Escape Lodge", "Blue Ridge Lake Sanctuary",
        "Chase Mountain Dreams", "Cherokee Sunrise on Noontootla Creek",
        "Cohutta Sunset", "Creekside Green", "Fallen Timber Lodge",
        "High Hopes", "Riverview Lodge", "Serendipity on Noontootla Creek",
        "Skyfall", "The Rivers Edge",
    ]

    # Get all distinct dirty cabin names
    cur.execute("""
        SELECT DISTINCT cabin_name FROM message_archive
        WHERE cabin_name IS NOT NULL AND cabin_name != ''
        ORDER BY cabin_name
    """)
    all_names = [r[0] for r in cur.fetchall()]
    print(f"  Found {len(all_names)} distinct cabin_name values")

    fixes = {}
    for name in all_names:
        original = name
        cleaned = name

        # Strip array notation: "['Skyfall']" -> "Skyfall"
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned.strip("[]")
            # Remove quotes
            cleaned = cleaned.replace("'", "").replace('"', '')
            # If multiple properties in array, take the first one
            if "," in cleaned:
                parts = [p.strip() for p in cleaned.split(",")]
                cleaned = parts[0]

        # Strip hashtags: "#422076" -> skip (reservation ID, not property)
        if cleaned.startswith("#") and cleaned[1:].isdigit():
            cleaned = None

        # Match to canonical names (case-insensitive, partial match)
        if cleaned:
            matched = None
            for canon in canonical:
                if cleaned.lower() == canon.lower():
                    matched = canon
                    break
                if cleaned.lower() in canon.lower() or canon.lower() in cleaned.lower():
                    matched = canon
                    break
            # Handle special cases
            if not matched:
                lower = cleaned.lower()
                if "cherokee" in lower:
                    matched = "Cherokee Sunrise on Noontootla Creek"
                elif "serendipity" in lower:
                    matched = "Serendipity on Noontootla Creek"
                elif "timberline" in lower:
                    matched = "Above the Timberline"
                elif "sanctuary" in lower or "blue ridge lake" in lower:
                    matched = "Blue Ridge Lake Sanctuary"
                elif "5 bedroom" in lower and "fallen" in lower:
                    matched = "Fallen Timber Lodge"
                elif "441 king" in lower or "skyfall 441" in lower:
                    matched = "Skyfall"

            if matched and matched != original:
                fixes[original] = matched
            elif cleaned != original:
                fixes[original] = cleaned

    print(f"  Fixes to apply:")
    total_fixed = 0
    for old, new in sorted(fixes.items()):
        cur.execute("SELECT count(*) FROM message_archive WHERE cabin_name = %s", (old,))
        cnt = cur.fetchone()[0]
        print(f"    {old:55s} -> {new} ({cnt} rows)")
        cur.execute("""
            UPDATE message_archive SET cabin_name = %s, updated_at = NOW()
            WHERE cabin_name = %s
        """, (new, old))
        total_fixed += cur.rowcount

    # Also fix NULL cabin_name entries that reference reservation IDs
    cur.execute("""
        UPDATE message_archive SET cabin_name = NULL
        WHERE cabin_name LIKE '#%' AND cabin_name ~ '^#[0-9]+$'
    """)
    nulled = cur.rowcount

    conn.commit()
    conn.close()
    print(f"  -> {total_fixed} rows normalized, {nulled} reservation-ID entries cleared")


# ═══════════════════════════════════════════════════════════════
# FIX 3: Match unlinked messages to properties
# ═══════════════════════════════════════════════════════════════
def fix_property_linkage():
    print()
    print("=" * 70)
    print("FIX 3: Match unlinked messages to properties")
    print("=" * 70)
    conn = get_conn()
    cur = conn.cursor()

    # Count unlinked before
    cur.execute("SELECT count(*) FROM message_archive WHERE cabin_name IS NULL OR cabin_name = ''")
    before = cur.fetchone()[0]
    print(f"  Unlinked messages before: {before}")

    # Strategy 1: Match by guest phone number
    # If a guest sent messages linked to a property, their other messages are likely about the same property
    cur.execute("""
        WITH linked AS (
            SELECT phone_number, cabin_name, count(*) as cnt
            FROM message_archive
            WHERE cabin_name IS NOT NULL AND cabin_name != ''
            GROUP BY phone_number, cabin_name
        ),
        best_match AS (
            SELECT DISTINCT ON (phone_number)
                phone_number, cabin_name
            FROM linked
            ORDER BY phone_number, cnt DESC
        )
        UPDATE message_archive m
        SET cabin_name = bm.cabin_name, updated_at = NOW()
        FROM best_match bm
        WHERE m.phone_number = bm.phone_number
          AND (m.cabin_name IS NULL OR m.cabin_name = '')
    """)
    by_phone = cur.rowcount
    print(f"  Strategy 1 (phone match): {by_phone} rows linked")

    # Strategy 2: Match by guest name
    cur.execute("""
        WITH linked AS (
            SELECT guest_name, cabin_name, count(*) as cnt
            FROM message_archive
            WHERE cabin_name IS NOT NULL AND cabin_name != ''
              AND guest_name IS NOT NULL AND guest_name != ''
            GROUP BY guest_name, cabin_name
        ),
        best_match AS (
            SELECT DISTINCT ON (guest_name)
                guest_name, cabin_name
            FROM linked
            ORDER BY guest_name, cnt DESC
        )
        UPDATE message_archive m
        SET cabin_name = bm.cabin_name, updated_at = NOW()
        FROM best_match bm
        WHERE m.guest_name = bm.guest_name
          AND (m.cabin_name IS NULL OR m.cabin_name = '')
          AND m.guest_name IS NOT NULL AND m.guest_name != ''
    """)
    by_name = cur.rowcount
    print(f"  Strategy 2 (guest name match): {by_name} rows linked")

    # Strategy 3: Match by email subject/body containing property name
    canonical = [
        "Above the Timberline", "Aska Escape Lodge", "Blue Ridge Lake Sanctuary",
        "Chase Mountain Dreams", "Cherokee Sunrise", "Cohutta Sunset",
        "Creekside Green", "Fallen Timber Lodge", "High Hopes",
        "Riverview Lodge", "Serendipity", "Skyfall", "The Rivers Edge",
    ]
    full_names = {
        "Cherokee Sunrise": "Cherokee Sunrise on Noontootla Creek",
        "Serendipity": "Serendipity on Noontootla Creek",
    }

    by_body = 0
    for prop in canonical:
        full_name = full_names.get(prop, prop)
        cur.execute("""
            UPDATE message_archive
            SET cabin_name = %s, updated_at = NOW()
            WHERE (cabin_name IS NULL OR cabin_name = '')
              AND (message_body ILIKE %s OR message_body ILIKE %s)
        """, (full_name, f"%{prop}%", f"%{prop.lower()}%"))
        by_body += cur.rowcount
    print(f"  Strategy 3 (message body scan): {by_body} rows linked")

    # Strategy 4: Match by reservation_id -> fin_reservations -> property
    cur.execute("""
        UPDATE message_archive m
        SET cabin_name = fr.property_name, updated_at = NOW()
        FROM fin_reservations fr
        WHERE m.reservation_id = fr.res_id
          AND (m.cabin_name IS NULL OR m.cabin_name = '')
          AND fr.property_name IS NOT NULL
    """)
    by_res = cur.rowcount
    print(f"  Strategy 4 (reservation_id match): {by_res} rows linked")

    # Strategy 5: Match by conversation thread -> guest_name -> fin_reservations
    cur.execute("""
        UPDATE message_archive m
        SET cabin_name = fr.property_name, updated_at = NOW()
        FROM fin_reservations fr
        WHERE m.guest_name = fr.guest_name
          AND (m.cabin_name IS NULL OR m.cabin_name = '')
          AND fr.property_name IS NOT NULL
          AND m.guest_name IS NOT NULL AND m.guest_name != ''
    """)
    by_gl = cur.rowcount
    print(f"  Strategy 5 (fin_reservations guest_name): {by_gl} rows linked")

    # Count unlinked after
    cur.execute("SELECT count(*) FROM message_archive WHERE cabin_name IS NULL OR cabin_name = ''")
    after = cur.fetchone()[0]
    total = before - after
    print(f"  -> Total linked: {total} ({before} -> {after} unlinked)")

    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
# FIX 4: Load scheduler/master guide into property_sms_config
# ═══════════════════════════════════════════════════════════════
def fix_load_templates():
    print()
    print("=" * 70)
    print("FIX 4: Populate property_sms_config template columns")
    print("=" * 70)
    conn = get_conn()
    cur = conn.cursor()

    # Load scheduler templates
    sched = json.load(open(os.path.join(DATA_DIR, "scheduler.json")))
    templates = sched.get("templates", [])

    # Build welcome message from the "Welcome" email template
    welcome_tmpl = next((t for t in templates if "Welcome" in t.get("name", "")), None)
    welcome_text = welcome_tmpl.get("message_text", "") if welcome_tmpl else ""

    # Build checkout reminder from master guide "Check-out Procedures"
    master = json.load(open(os.path.join(DATA_DIR, "master_guide.json")))
    checkout_items = [i for i in master.get("items", []) if i.get("category") == "Check-out Procedures"]
    checkout_text = "\n\n".join(f"{i['title']}\n{i['content']}" for i in checkout_items if i.get("content"))

    # Build house rules from master guide "Rental Rules"
    rules_items = [i for i in master.get("items", []) if i.get("category") == "Rental Rules"]
    rules_text = "\n\n".join(f"{i['title']}\n{i['content']}" for i in rules_items if i.get("content"))

    # Build emergency info
    emergency_items = [i for i in master.get("items", []) if i.get("category") == "Emergency Info"]
    emergency_text = "\n\n".join(f"{i['title']}\n{i['content']}" for i in emergency_items if i.get("content"))

    # Build checkin template from "Your Stay" items
    stay_items = [i for i in master.get("items", []) if i.get("category") == "Your Stay"]
    checkin_text = "\n\n".join(f"{i['title']}\n{i['content']}" for i in stay_items if i.get("content"))

    # Get follow-up template
    followup_tmpl = next((t for t in templates if "Follow-Up" in t.get("name", "")), None)
    followup_text = followup_tmpl.get("message_text", "") if followup_tmpl else ""

    # Get review request template
    review_tmpl = next((t for t in templates if "Review" in t.get("name", "")), None)
    review_text = review_tmpl.get("message_text", "") if review_tmpl else ""

    # Update all properties with shared templates
    cur.execute("""
        UPDATE property_sms_config SET
            welcome_message_template = COALESCE(NULLIF(welcome_message_template, ''), %s),
            checkout_reminder_template = COALESCE(NULLIF(checkout_reminder_template, ''), %s),
            house_rules = CASE
                WHEN house_rules IS NOT NULL AND house_rules != '' THEN house_rules || E'\n\n--- Master Guide Rules ---\n' || %s
                ELSE %s
            END,
            checkin_instructions = CASE
                WHEN checkin_instructions IS NOT NULL AND checkin_instructions != '' THEN checkin_instructions || E'\n\n--- Master Guide Details ---\n' || %s
                ELSE %s
            END,
            updated_at = NOW()
    """, (welcome_text, checkout_text, rules_text, rules_text, checkin_text, checkin_text))
    updated = cur.rowcount
    print(f"  Updated {updated} properties with shared templates")
    print(f"  Welcome template: {len(welcome_text)} chars")
    print(f"  Checkout reminder: {len(checkout_text)} chars")
    print(f"  House rules: {len(rules_text)} chars")
    print(f"  Check-in instructions: {len(checkin_text)} chars")

    # Now set per-property door code + WiFi templates from scheduler
    for tmpl in templates:
        name = tmpl.get("name", "")
        msg = tmpl.get("message_text", "")
        if "Door Code" in name and "WIFI" in name.upper():
            # Extract property name from template name
            prop_name = (name
                .replace("Door Code & WIFI ", "")
                .replace("Door Code & Wifi ", "")
                .replace("Door Code and Wifi ", "")
                .replace("Door Code & WiFi ", "")
                .strip())
            if prop_name:
                cur.execute("""
                    UPDATE property_sms_config
                    SET wifi_info_template = %s, checkin_info_template = %s, updated_at = NOW()
                    WHERE property_name = %s
                """, (msg, msg, prop_name))
                if cur.rowcount:
                    print(f"  Set door code/WiFi template for: {prop_name}")

    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
# FIX 5: Clean up orphaned/retired properties
# ═══════════════════════════════════════════════════════════════
def fix_orphan_properties():
    print()
    print("=" * 70)
    print("FIX 5: Clean up orphaned/retired properties")
    print("=" * 70)
    conn = get_conn()
    cur = conn.cursor()

    # List orphans
    cur.execute("""
        SELECT property_id, name, internal_name, status_name, address
        FROM ops_properties
        WHERE status_name != 'Active'
        ORDER BY name
    """)
    orphans = cur.fetchall()
    print(f"  Found {len(orphans)} retired/orphan properties:")
    for pid, name, iname, status, addr in orphans:
        print(f"    {pid:20s} {name:35s} ({iname}) — {status}")

    # Don't delete — mark them clearly and fix naming
    for pid, name, iname, status, addr in orphans:
        if name.startswith("ORPHAN-"):
            # Already marked as orphan, ensure internal_name is preserved
            print(f"    Already marked: {name}")
        else:
            new_name = f"RETIRED-{name}"
            cur.execute("""
                UPDATE ops_properties SET name = %s, status_name = 'Retired', updated_at = NOW()
                WHERE property_id = %s
            """, (new_name, pid))
            print(f"    Renamed: {name} -> {new_name}")

    # Fix the duplicate Rivers Edge
    cur.execute("""
        SELECT property_id, name, streamline_id FROM ops_properties
        WHERE internal_name = 'The Rivers Edge'
        ORDER BY streamline_id
    """)
    rivers = cur.fetchall()
    if len(rivers) > 1:
        print(f"\n  Duplicate 'The Rivers Edge' entries: {len(rivers)}")
        for pid, name, slid in rivers:
            print(f"    {pid}: {name} (SL#{slid})")
        # Keep the active one, mark the orphan
        for pid, name, slid in rivers:
            if name.startswith("ORPHAN"):
                cur.execute("""
                    UPDATE ops_properties SET status_name = 'Retired', updated_at = NOW()
                    WHERE property_id = %s
                """, (pid,))
                print(f"    Marked retired: {pid}")

    conn.commit()
    conn.close()
    print(f"  -> {len(orphans)} orphan properties handled")


# ═══════════════════════════════════════════════════════════════
# VERIFICATION
# ═══════════════════════════════════════════════════════════════
def verify_all():
    print()
    print("=" * 70)
    print("VERIFICATION — POST-FIX STATUS")
    print("=" * 70)
    conn = get_conn()
    cur = conn.cursor()

    # 1. Property SMS config completeness
    cur.execute("""
        SELECT property_name,
            CASE WHEN wifi_password IS NOT NULL AND wifi_password != '' THEN 'Y' ELSE 'N' END,
            CASE WHEN door_code IS NOT NULL AND door_code != '' THEN 'Y' ELSE 'N' END,
            CASE WHEN address IS NOT NULL AND address != 'Address' AND address != '' THEN 'Y' ELSE 'N' END,
            CASE WHEN checkin_instructions IS NOT NULL AND checkin_instructions != '' THEN 'Y' ELSE 'N' END,
            CASE WHEN house_rules IS NOT NULL AND house_rules != '' THEN 'Y' ELSE 'N' END,
            CASE WHEN welcome_message_template IS NOT NULL AND welcome_message_template != '' THEN 'Y' ELSE 'N' END,
            CASE WHEN checkout_reminder_template IS NOT NULL AND checkout_reminder_template != '' THEN 'Y' ELSE 'N' END,
            CASE WHEN wifi_info_template IS NOT NULL AND wifi_info_template != '' THEN 'Y' ELSE 'N' END
        FROM property_sms_config ORDER BY property_name
    """)
    print("\n  Property SMS Config completeness:")
    print(f"  {'Property':42s} WiFi Door Addr CkIn Rules Welc CkOut DCode")
    for name, wifi, door, addr, ckin, rules, welc, ckout, dcode in cur.fetchall():
        print(f"  {name:42s}  {wifi}     {door}    {addr}    {ckin}    {rules}    {welc}    {ckout}    {dcode}")

    # 2. Dirty cabin names
    cur.execute("""
        SELECT count(*) FROM message_archive
        WHERE cabin_name LIKE '%[%' OR cabin_name LIKE '%#%'
    """)
    dirty = cur.fetchone()[0]
    print(f"\n  Dirty cabin names remaining: {dirty}")

    # 3. Property linkage
    cur.execute("SELECT count(*) FROM message_archive WHERE cabin_name IS NULL OR cabin_name = ''")
    unlinked = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM message_archive")
    total = cur.fetchone()[0]
    pct = 100 * unlinked / total if total else 0
    print(f"  Unlinked messages: {unlinked}/{total} ({pct:.1f}%)")

    # 4. Message distribution by property
    cur.execute("""
        SELECT COALESCE(cabin_name, '<UNLINKED>'), count(*)
        FROM message_archive
        GROUP BY cabin_name
        ORDER BY count(*) DESC
        LIMIT 20
    """)
    print(f"\n  Message distribution by property:")
    for name, cnt in cur.fetchall():
        print(f"    {name:45s} {cnt:>5} messages")

    # 5. Orphan status
    cur.execute("SELECT count(*) FROM ops_properties WHERE status_name = 'Active'")
    active = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM ops_properties WHERE status_name != 'Active'")
    retired = cur.fetchone()[0]
    print(f"\n  Properties: {active} active, {retired} retired")

    conn.close()


def main():
    print("=" * 70)
    print("FORTRESS INTEGRATION FIX — ALL ISSUES")
    print(f"Started: {datetime.now()}")
    print("=" * 70)

    fix_sync_streamline_properties()
    fix_dirty_cabin_names()
    fix_property_linkage()
    fix_load_templates()
    fix_orphan_properties()
    verify_all()

    print(f"\n{'=' * 70}")
    print(f"ALL FIXES COMPLETE — {datetime.now()}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
