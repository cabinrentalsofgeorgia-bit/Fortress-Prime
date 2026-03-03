#!/usr/bin/env python3
"""
Load all extracted RueBaRue data into fortress_db.
Creates necessary tables and populates them.
"""
import json, os, sys
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values

DATA_DIR = "/home/admin/Fortress-Prime/data/ruebarue"
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


def load_json(name):
    path = os.path.join(DATA_DIR, name)
    with open(path) as f:
        return json.load(f)


def get_conn():
    return psycopg2.connect(DB_URL)


# ── SCHEMA ─────────────────────────────────────────────────────
CREATE_TABLES = """
-- Knowledge base for AI chatbot (FAQs, saved responses, guide content)
CREATE TABLE IF NOT EXISTS ruebarue_knowledge_base (
    id SERIAL PRIMARY KEY,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source VARCHAR(50) NOT NULL,
    property_name VARCHAR(200),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rkb_category ON ruebarue_knowledge_base(category);
CREATE INDEX IF NOT EXISTS idx_rkb_source ON ruebarue_knowledge_base(source);

-- Scheduler message templates
CREATE TABLE IF NOT EXISTS ruebarue_message_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    type VARCHAR(20) NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    schedule VARCHAR(200),
    tags TEXT,
    booking_source VARCHAR(200),
    flags TEXT,
    subject TEXT,
    message_text TEXT,
    full_modal_text TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Contacts directory
CREATE TABLE IF NOT EXISTS ruebarue_contacts (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    phone VARCHAR(50),
    email VARCHAR(200),
    role VARCHAR(50),
    properties TEXT,
    tags TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Area guide places
DROP TABLE IF EXISTS ruebarue_area_guide;
CREATE TABLE IF NOT EXISTS ruebarue_area_guide (
    id SERIAL PRIMARY KEY,
    section VARCHAR(100) NOT NULL,
    entry_number INTEGER,
    place_name TEXT,
    address TEXT,
    distance TEXT,
    phone TEXT,
    rating TEXT,
    tip TEXT,
    raw_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rag_section ON ruebarue_area_guide(section);

-- RueBaRue guest records
CREATE TABLE IF NOT EXISTS ruebarue_guests (
    id SERIAL PRIMARY KEY,
    guest_info TEXT NOT NULL,
    property_info TEXT,
    door_code TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""


def create_tables():
    print("Creating tables...")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(CREATE_TABLES)
    conn.commit()
    conn.close()
    print("  Tables created/verified")


# ── LOADERS ────────────────────────────────────────────────────
def load_faqs():
    print("\n=== Loading AI Chatbot FAQs ===")
    data = load_json("ai_faqs.json")
    conn = get_conn()
    cur = conn.cursor()

    # Clear existing FAQs
    cur.execute("DELETE FROM ruebarue_knowledge_base WHERE source = 'ai_chatbot_faq'")

    faqs = data.get("faqs", [])
    for faq in faqs:
        cur.execute("""
            INSERT INTO ruebarue_knowledge_base (category, title, content, source)
            VALUES ('faq', %s, %s, 'ai_chatbot_faq')
        """, (faq["question"], faq["answer"]))

    conn.commit()
    conn.close()
    print(f"  Loaded {len(faqs)} FAQs")


def load_scheduler():
    print("\n=== Loading Scheduler Templates ===")
    data = load_json("scheduler.json")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM ruebarue_message_templates")

    templates = data.get("templates", [])
    for t in templates:
        cur.execute("""
            INSERT INTO ruebarue_message_templates
            (name, type, active, schedule, tags, booking_source, flags, subject, message_text, full_modal_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            t.get("name", ""), t.get("type", ""), t.get("active", True),
            t.get("schedule", ""), t.get("tags", ""), t.get("booking_source", ""),
            t.get("flags", ""), t.get("subject", ""),
            t.get("message_text", ""), t.get("full_modal_text", ""),
        ))

    conn.commit()
    conn.close()
    print(f"  Loaded {len(templates)} scheduler templates")


def load_saved_responses():
    print("\n=== Loading Saved Responses ===")
    data = load_json("saved_responses.json")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM ruebarue_knowledge_base WHERE source = 'saved_response'")

    responses = data.get("responses", [])
    for r in responses:
        cur.execute("""
            INSERT INTO ruebarue_knowledge_base (category, title, content, source)
            VALUES ('saved_response', %s, %s, 'saved_response')
        """, (r["name"], r.get("text", "")))

    conn.commit()
    conn.close()
    print(f"  Loaded {len(responses)} saved responses")


def load_master_guide():
    print("\n=== Loading Master Home Guide ===")
    data = load_json("master_guide.json")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM ruebarue_knowledge_base WHERE source = 'master_guide'")

    items = data.get("items", [])
    for item in items:
        cur.execute("""
            INSERT INTO ruebarue_knowledge_base (category, subcategory, title, content, source, metadata)
            VALUES ('master_guide', %s, %s, %s, 'master_guide', %s)
        """, (
            item.get("category", ""),
            item.get("title", ""),
            item.get("content", ""),
            json.dumps({"links": item.get("links", [])}),
        ))

    conn.commit()
    conn.close()
    print(f"  Loaded {len(items)} master guide items")


def load_area_guide():
    print("\n=== Loading Area Guide ===")
    data = load_json("area_guide.json")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM ruebarue_area_guide")

    sections = data.get("sections", {})
    total = 0
    for sec_name, sec_data in sections.items():
        entries = sec_data.get("entries", [])
        for idx, entry_text in enumerate(entries):
            if entry_text.strip().startswith("Begin typing"):
                continue
            # Parse the entry text
            lines = entry_text.strip().split("\n")
            entry_num = None
            place_name = ""
            address_line = ""
            distance = ""
            phone_val = ""
            rating_val = ""
            tip_text = ""

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.isdigit():
                    entry_num = int(line)
                elif not place_name and not line.startswith("(") and line[0].isalpha():
                    place_name = line
                elif "mi" in line and any(c.isdigit() for c in line):
                    distance = line
                elif line.startswith("(") and line[1].isdigit():
                    phone_val = line
                elif line.replace(".", "").isdigit() and len(line) <= 4:
                    rating_val = line
                elif "tip" in line.lower() or len(line) > 50:
                    tip_text = line if not tip_text else tip_text + "\n" + line
                elif not address_line and "," in line:
                    address_line = line

            cur.execute("""
                INSERT INTO ruebarue_area_guide
                (section, entry_number, place_name, address, distance, phone, rating, tip, raw_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (sec_name, entry_num, place_name, address_line, distance, phone_val, rating_val, tip_text, entry_text))
            total += 1

    conn.commit()
    conn.close()
    print(f"  Loaded {total} area guide entries across {len(sections)} sections")


def load_contacts():
    print("\n=== Loading Contacts ===")
    data = load_json("contacts.json")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM ruebarue_contacts")

    contacts = data.get("contacts", [])
    for c in contacts:
        cur.execute("""
            INSERT INTO ruebarue_contacts (name, phone, email, role, properties, tags)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            c.get("name", ""), c.get("phone", ""), c.get("email", ""),
            c.get("role", ""), c.get("properties", ""), c.get("tags", ""),
        ))

    conn.commit()
    conn.close()
    print(f"  Loaded {len(contacts)} contacts")


def load_guests():
    print("\n=== Loading Guest Data ===")
    data = load_json("guests.json")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM ruebarue_guests")

    guests = data.get("guests", [])
    for g in guests:
        cur.execute("""
            INSERT INTO ruebarue_guests (guest_info, property_info, door_code)
            VALUES (%s, %s, %s)
        """, (
            g.get("guest_info", ""),
            g.get("property_info", ""),
            g.get("door_code", ""),
        ))

    conn.commit()
    conn.close()
    print(f"  Loaded {len(guests)} guest records")


def load_surveys():
    print("\n=== Loading Survey Data ===")
    data = load_json("surveys.json")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM ruebarue_knowledge_base WHERE source = 'survey'")

    for survey in data.get("surveys", []):
        cur.execute("""
            INSERT INTO ruebarue_knowledge_base (category, title, content, source, metadata)
            VALUES ('survey', %s, %s, 'survey', %s)
        """, (
            survey.get("name", ""),
            survey.get("full_text", "") or survey.get("list_text", ""),
            json.dumps({
                "response_count": survey.get("response_count", ""),
                "questions": survey.get("questions", []),
            }),
        ))

    conn.commit()
    conn.close()
    print(f"  Loaded {len(data.get('surveys', []))} survey records")


def load_home_guides():
    print("\n=== Loading Home Guide Property Data ===")
    data = load_json("home_guides.json")
    conn = get_conn()
    cur = conn.cursor()

    # Update property_sms_config with guide info
    for prop in data.get("properties", []):
        name = prop.get("name", "")
        address = prop.get("address", "")
        rental_url = prop.get("rental_url", "")

        # Check if property exists in config
        cur.execute("SELECT id FROM property_sms_config WHERE property_name = %s", (name,))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE property_sms_config
                SET address = COALESCE(NULLIF(%s, ''), address),
                    updated_at = NOW()
                WHERE property_name = %s
            """, (address, name))
        else:
            # Insert new property config
            cur.execute("""
                INSERT INTO property_sms_config
                (property_id, property_name, cabin_name, assigned_phone_number, address)
                VALUES (
                    (SELECT COALESCE(MAX(property_id), 0) + 1 FROM property_sms_config),
                    %s, %s, '+17065255482', %s
                )
            """, (name, name, address))

        # Also store in knowledge base
        cur.execute("""
            INSERT INTO ruebarue_knowledge_base (category, title, content, source, property_name, metadata)
            VALUES ('home_guide', %s, %s, 'home_guide', %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            name,
            f"Property: {name}\nAddress: {address}\nGuide URL: {rental_url}",
            name,
            json.dumps({"rental_url": rental_url}),
        ))

    conn.commit()
    conn.close()
    print(f"  Loaded {len(data.get('properties', []))} property guide records")


def print_summary():
    print("\n" + "=" * 60)
    print("DATABASE LOAD SUMMARY")
    print("=" * 60)
    conn = get_conn()
    cur = conn.cursor()

    tables = [
        "ruebarue_knowledge_base",
        "ruebarue_message_templates",
        "ruebarue_contacts",
        "ruebarue_area_guide",
        "ruebarue_guests",
        "ai_training_dataset",
        "property_sms_config",
    ]
    for t in tables:
        cur.execute(f"SELECT count(*) FROM {t}")
        cnt = cur.fetchone()[0]
        print(f"  {t:40s} {cnt:>8} rows")

    # Knowledge base breakdown
    cur.execute("""
        SELECT source, count(*) FROM ruebarue_knowledge_base
        GROUP BY source ORDER BY count(*) DESC
    """)
    print("\n  Knowledge Base breakdown:")
    for source, cnt in cur.fetchall():
        print(f"    {source:30s} {cnt:>5} entries")

    # Area guide breakdown
    cur.execute("""
        SELECT section, count(*) FROM ruebarue_area_guide
        GROUP BY section ORDER BY count(*) DESC
    """)
    print("\n  Area Guide breakdown:")
    for section, cnt in cur.fetchall():
        print(f"    {section:35s} {cnt:>5} entries")

    conn.close()


def main():
    print("=" * 60)
    print("Loading RueBaRue Data into fortress_db")
    print("=" * 60)

    create_tables()
    load_faqs()
    load_scheduler()
    load_saved_responses()
    load_master_guide()
    load_area_guide()
    load_contacts()
    load_guests()
    load_surveys()
    load_home_guides()
    print_summary()

    print("\n✓ All data loaded successfully!")


if __name__ == "__main__":
    main()
