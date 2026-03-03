#!/usr/bin/env python3
"""
FORTRESS PRIME — Legal Headhunter Engine
=========================================
Scrape, ingest, and AI-score Georgia commercial litigators for the
Generali v. CROG defense (SUV2026000013, Fannin County Superior Court).

Data Sources:
  - SerpAPI (Google Search + Maps) for attorney discovery
  - Manual CSV import for direct entry
  - Existing legal_cmd.attorneys table (UUID PKs)

AI Scoring (HYDRA R1-70B preferred, SWARM qwen2.5:7b fallback):
  - Fannin Jurisdiction: +30 pts
  - Boutique Commercial Litigator: +30 pts
  - The Eckles Match (LLC/Corporate/Contract): +40 pts

Usage:
  python3 -m src.legal_headhunter scrape              # SerpAPI search + ingest
  python3 -m src.legal_headhunter score               # AI-score all unscored
  python3 -m src.legal_headhunter import --csv f.csv   # manual CSV ingest
  python3 -m src.legal_headhunter report              # ranked top-10 report
  python3 -m src.legal_headhunter full                # scrape + score + report
"""

import os
import sys
import csv
import json
import argparse
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] fortress.legal_headhunter — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fortress.legal_headhunter")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

SEARCH_QUERIES = [
    '"commercial litigation attorney" "Blue Ridge" OR "Ellijay" Georgia',
    '"contract dispute lawyer" "Fannin County" Georgia',
    '"LLC defense attorney" Atlanta Georgia "Appalachian Judicial Circuit"',
    '"breach of contract" lawyer Georgia "boutique firm"',
    '"corporate litigation" attorney "North Georgia"',
    '"business litigation" attorney "Blue Ridge" Georgia',
    'Georgia attorney "contract disputes" "LLC representation"',
]

SOTA_SCORING_PROMPT = """You are an elite legal headhunter for Cabin Rentals of Georgia (CROG), an enterprise-grade LLC. You are evaluating a Georgia attorney for a breach of contract defense in Fannin County Superior Court.

Case Context: Generali Global Assistance v. CROG (SUV2026000013). Generali claims $7,500 in unpaid travel insurance commissions. CROG's defense relies on Eckles v. Atlanta Technology Group, Inc. (267 Ga. 801, 1997) — Generali's collection agent (RTS Financial) is a non-lawyer entity that cannot represent Generali in a court of record.

Scoring Rules:

Fannin Jurisdiction (+30 pts): Reward attorneys physically located in Blue Ridge, Ellijay, or Atlanta attorneys who specifically list Appalachian Judicial Circuit experience. Penalize attorneys with no Georgia mountain region presence.

Boutique Commercial Litigator (+30 pts): Reward solo practitioners or boutique firm partners (1-20 attorneys). Penalize 'Big Law' mega-firms (too expensive for a $7,500 dispute) and 'Ambulance Chasers' (personal injury focus, wrong specialty).

The Eckles Match (+40 pts): Reward attorneys who explicitly list 'Corporate Litigation', 'LLC Representation', 'Contract Disputes', 'Business Law', or 'Collections Defense'. Penalize attorneys whose practice is entirely unrelated (family law, criminal defense, immigration).

ATTORNEY PROFILE TO EVALUATE:
{profile}

Return ONLY a strict JSON object (no markdown, no explanation outside JSON):
{{"sota_match_score": <0-100>, "eckles_competency": <true/false>, "commercial_litigation_focus": <true/false>, "fannin_jurisdiction_match": <true/false>, "ai_rationale": "<concise 2-sentence explanation>"}}"""


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db_conn():
    db_user = os.getenv("LEGAL_DB_USER", os.getenv("DB_USER_OVERRIDE", os.getenv("DB_USER", "admin")))
    db_name = os.getenv("DB_NAME", "fortress_db")
    db_pass = (
        os.getenv("LEGAL_DB_PASS")
        or os.getenv("DB_PASS")
        or os.getenv("DB_PASSWORD")
        or os.getenv("ADMIN_DB_PASS")
        or ""
    )
    params = {"dbname": db_name, "user": db_user}
    explicit_host = os.getenv("LEGAL_DB_HOST", os.getenv("DB_HOST", ""))
    if explicit_host:
        params["host"] = explicit_host
        params["port"] = os.getenv("LEGAL_DB_PORT", os.getenv("DB_PORT", "5432"))
    if db_pass:
        params["password"] = db_pass
    return psycopg2.connect(**params)


# ---------------------------------------------------------------------------
# SerpAPI scraping
# ---------------------------------------------------------------------------
def scrape_attorneys() -> List[Dict]:
    if not SERPAPI_KEY:
        logger.error("SERPAPI_KEY not set in .env. Cannot scrape. Use --csv for manual import.")
        return []

    try:
        from serpapi import GoogleSearch
    except ImportError:
        logger.error("serpapi package not installed. Run: pip3 install google-search-results")
        return []

    profiles: List[Dict] = []
    seen_names = set()

    for query in SEARCH_QUERIES:
        logger.info("SerpAPI query: %s", query[:80])
        try:
            search = GoogleSearch({
                "q": query,
                "location": "Georgia, United States",
                "hl": "en",
                "gl": "us",
                "num": 20,
                "api_key": SERPAPI_KEY,
            })
            results = search.get_dict()
        except Exception as e:
            logger.error("SerpAPI error for query '%s': %s", query[:50], e)
            continue

        for result in results.get("organic_results", []):
            profile = _parse_organic_result(result)
            if profile and profile["full_name"] not in seen_names:
                seen_names.add(profile["full_name"])
                profiles.append(profile)

        local = results.get("local_results", [])
        if isinstance(local, dict):
            local = local.get("places", local.get("results", []))
        if isinstance(local, list):
            for result in local:
                if not isinstance(result, dict):
                    continue
                profile = _parse_local_result(result)
                if profile and profile["full_name"] not in seen_names:
                    seen_names.add(profile["full_name"])
                    profiles.append(profile)

        for result in results.get("knowledge_graph", {}).get("people_also_search_for", []):
            if "attorney" in (result.get("description") or "").lower():
                name = result.get("name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    profiles.append({
                        "full_name": name,
                        "firm_name": "",
                        "location": "Georgia",
                        "practice_areas": ["Commercial Litigation"],
                        "profile_url": result.get("link", ""),
                        "contact_phone": "",
                        "contact_email": "",
                        "source": "serpapi_knowledge_graph",
                    })

    logger.info("Scraped %d unique attorney profiles from SerpAPI", len(profiles))
    return profiles


def _parse_organic_result(result: Dict) -> Optional[Dict]:
    title = result.get("title", "")
    snippet = result.get("snippet", "")
    link = result.get("link", "")

    name = _extract_name_from_title(title)
    if not name:
        return None

    firm = _extract_firm(title, snippet)
    location = _extract_location(snippet)
    practice = _extract_practice_areas(title + " " + snippet)

    return {
        "full_name": name,
        "firm_name": firm,
        "location": location,
        "practice_areas": practice,
        "profile_url": link,
        "contact_phone": _extract_phone(snippet),
        "contact_email": "",
        "source": "serpapi_organic",
    }


def _parse_local_result(result: Dict) -> Optional[Dict]:
    title = result.get("title", "")
    address = result.get("address", "")
    phone = result.get("phone", "")

    name = _extract_name_from_title(title)
    if not name:
        name = title

    return {
        "full_name": name,
        "firm_name": title if name != title else "",
        "location": address or "Georgia",
        "practice_areas": ["Commercial Litigation"],
        "profile_url": result.get("website", result.get("link", "")),
        "contact_phone": phone,
        "contact_email": "",
        "source": "serpapi_local",
    }


def _extract_name_from_title(title: str) -> str:
    title = re.sub(r'\s*[-–|·:,].*$', '', title)
    title = re.sub(r'\b(attorney|lawyer|esq\.?|law\s*(firm|office|group)|llc|pllc|pc|p\.c\.)\b', '', title, flags=re.IGNORECASE)
    title = title.strip(" -–|·:,")
    parts = title.split()
    if 2 <= len(parts) <= 5 and all(p[0].isupper() for p in parts if p):
        return title
    return ""


def _extract_firm(title: str, snippet: str) -> str:
    for pattern in [r'(?:at|with|of)\s+([A-Z][A-Za-z\s&,]+(?:LLC|LLP|P\.C\.|PLLC|Law|Firm|Group))', r'([A-Z][A-Za-z]+(?:\s+&\s+[A-Z][A-Za-z]+)+)']:
        m = re.search(pattern, title + " " + snippet)
        if m:
            return m.group(1).strip()
    return ""


def _extract_location(text: str) -> str:
    for pattern in [r'(Blue Ridge|Ellijay|Jasper|Blairsville|McCaysville|Dahlonega|Canton|Atlanta|Marietta|Dalton|Gainesville)[,\s]+(?:GA|Georgia)', r'([\w\s]+),\s*(?:GA|Georgia)']:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return f"{m.group(1).strip()}, Georgia"
    return "Georgia"


def _extract_practice_areas(text: str) -> List[str]:
    areas = []
    keywords = {
        "Commercial Litigation": ["commercial litigation", "business litigation", "corporate litigation"],
        "Contract Disputes": ["contract dispute", "breach of contract", "contract law"],
        "LLC Representation": ["llc", "limited liability", "corporate representation", "business entity"],
        "Collections Defense": ["collections defense", "debt defense", "creditor rights"],
        "Real Estate": ["real estate", "property law", "land use"],
        "Business Law": ["business law", "corporate law", "business formation"],
    }
    text_lower = text.lower()
    for area, kws in keywords.items():
        if any(kw in text_lower for kw in kws):
            areas.append(area)
    return areas or ["General Practice"]


def _extract_phone(text: str) -> str:
    m = re.search(r'(\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4})', text)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------
def import_csv(csv_path: str) -> List[Dict]:
    profiles = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("full_name") or row.get("name") or f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
                if not name:
                    continue
                practice = row.get("practice_areas", "")
                profiles.append({
                    "full_name": name,
                    "firm_name": row.get("firm_name", row.get("firm", "")),
                    "location": row.get("location", row.get("address", "Georgia")),
                    "practice_areas": [a.strip() for a in practice.split(",")] if practice else ["General Practice"],
                    "profile_url": row.get("profile_url", row.get("website", row.get("url", ""))),
                    "contact_phone": row.get("contact_phone", row.get("phone", "")),
                    "contact_email": row.get("contact_email", row.get("email", "")),
                    "bar_number": row.get("bar_number", ""),
                    "source": "csv_import",
                })
    except Exception as e:
        logger.error("CSV import failed: %s", e)
    logger.info("Imported %d profiles from CSV: %s", len(profiles), csv_path)
    return profiles


# ---------------------------------------------------------------------------
# Database ingestion
# ---------------------------------------------------------------------------
def ingest_profiles(profiles: List[Dict]) -> int:
    if not profiles:
        return 0

    conn = get_db_conn()
    cur = conn.cursor()
    ingested = 0

    for p in profiles:
        name_parts = p["full_name"].split(maxsplit=1)
        first_name = name_parts[0] if name_parts else p["full_name"]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        bar_num = p.get("bar_number") or None

        if bar_num:
            cur.execute("SELECT id FROM legal_cmd.attorneys WHERE bar_number = %s", (bar_num,))
            if cur.fetchone():
                logger.info("  Skipped (dupe bar#): %s", p["full_name"])
                continue

        cur.execute(
            "SELECT id FROM legal_cmd.attorneys WHERE first_name ILIKE %s AND last_name ILIKE %s AND firm_name ILIKE %s",
            (first_name, last_name, p.get("firm_name") or "%"),
        )
        if cur.fetchone():
            logger.info("  Skipped (dupe name+firm): %s", p["full_name"])
            continue

        try:
            cur.execute("""
                INSERT INTO legal_cmd.attorneys (
                    first_name, last_name, firm_name, address, phone, email,
                    website, bar_number, practice_areas, jurisdiction,
                    source, source_url, status, outreach_status, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', 'prospect', %s)
                RETURNING id
            """, (
                first_name,
                last_name,
                p.get("firm_name", ""),
                p.get("location", ""),
                p.get("contact_phone", ""),
                p.get("contact_email", ""),
                p.get("profile_url", ""),
                bar_num,
                p.get("practice_areas", []),
                ["Georgia", "Fannin County"],
                p.get("source", "manual"),
                p.get("profile_url", ""),
                f"Ingested by Legal Headhunter Engine on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            ))
            row = cur.fetchone()
            conn.commit()
            ingested += 1
            logger.info("  Ingested: %s (%s) -> %s", p["full_name"], p.get("firm_name", ""), row[0] if row else "?")
        except Exception as e:
            logger.error("  Failed to ingest %s: %s", p["full_name"], e)
            conn.rollback()

    cur.close()
    conn.close()
    logger.info("Ingestion complete: %d/%d profiles stored", ingested, len(profiles))
    return ingested


# ---------------------------------------------------------------------------
# AI Scoring
# ---------------------------------------------------------------------------
def score_unscored_attorneys():
    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.id, a.first_name, a.last_name, a.firm_name, a.address,
               a.practice_areas, a.jurisdiction, a.specialty, a.notes, a.website
        FROM legal_cmd.attorneys a
        LEFT JOIN legal_cmd.attorney_scoring s ON s.attorney_id = a.id
        WHERE s.id IS NULL AND a.status = 'active'
        ORDER BY a.created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        logger.info("No unscored attorneys found.")
        return 0

    logger.info("Scoring %d unscored attorneys...", len(rows))

    clients = _get_scoring_clients()
    scored = 0
    active_client, active_model, active_mode = clients[0]
    logger.info("Primary scoring model: %s (%s)", active_mode, active_model)

    for row in rows:
        atty_id, first, last, firm, address, practice, jurisdiction, specialty, notes, website = row
        profile_text = (
            f"Name: {first} {last}\n"
            f"Firm: {firm or 'Unknown'}\n"
            f"Location: {address or 'Unknown'}\n"
            f"Practice Areas: {', '.join(practice) if practice else specialty or 'Unknown'}\n"
            f"Jurisdiction: {', '.join(jurisdiction) if jurisdiction else 'Unknown'}\n"
            f"Website: {website or 'N/A'}\n"
            f"Notes: {(notes or '')[:500]}"
        )

        score_data = None
        for client, model, mode in clients:
            score_data = _call_scoring_model(client, model, profile_text)
            if score_data:
                active_model = model
                break
            logger.warning("  %s (%s) failed for %s %s, trying next model...", mode, model, first, last)

        if score_data:
            _save_score(atty_id, score_data, active_model)
            scored += 1
            logger.info(
                "  Scored %s %s: %d/100 (Eckles=%s, Comm=%s, Fannin=%s)",
                first, last, score_data.get("sota_match_score", 0),
                score_data.get("eckles_competency"),
                score_data.get("commercial_litigation_focus"),
                score_data.get("fannin_jurisdiction_match"),
            )
        else:
            logger.warning(
                "  Failed to score %s %s with all available models. "
                "Ensure an inference model is loaded on the cluster.",
                first, last,
            )

    logger.info("Scoring complete: %d/%d attorneys scored", scored, len(rows))
    return scored


def _get_scoring_clients() -> List[tuple]:
    """Return a prioritized list of (client, model, mode_name) tuples to try.

    Tries HYDRA and SWARM via config.py, then falls back to direct
    Ollama on Captain (port 11434) which bypasses the Nginx LB that
    may route to nodes without the model loaded.
    """
    from openai import OpenAI
    try:
        from config import get_inference_client, SPARK_01_IP, SWARM_MODEL, HYDRA_MODEL
    except ImportError as e:
        logger.error("Could not import config: %s", e)
        sys.exit(1)

    clients = []

    direct_client = OpenAI(
        base_url=f"http://{SPARK_01_IP}:11434/v1",
        api_key="not-needed",
        timeout=60,
    )
    clients.append((direct_client, SWARM_MODEL, "SWARM-DIRECT"))

    for mode in ("HYDRA", "SWARM"):
        try:
            client, model = get_inference_client(mode)
            clients.append((client, model, mode))
        except Exception as e:
            logger.warning("%s unavailable: %s", mode, e)

    if not clients:
        logger.error("No inference clients configured.")
        sys.exit(1)

    return clients


def _call_scoring_model(client, model: str, profile_text: str) -> Optional[Dict]:
    prompt = SOTA_SCORING_PROMPT.format(profile=profile_text)

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a legal headhunter AI. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=500,
                timeout=120,
            )
            content = response.choices[0].message.content.strip()

            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)

            think_match = re.search(r'</think>\s*', content)
            if think_match:
                content = content[think_match.end():]

            json_match = re.search(r'\{[^{}]*"sota_match_score"[^{}]*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)

            data = json.loads(content)

            required = ["sota_match_score", "eckles_competency", "commercial_litigation_focus", "fannin_jurisdiction_match", "ai_rationale"]
            if all(k in data for k in required):
                data["sota_match_score"] = max(0, min(100, int(data["sota_match_score"])))
                return data
            else:
                logger.warning("  Missing keys in response: %s", [k for k in required if k not in data])

        except json.JSONDecodeError as e:
            logger.warning("  JSON parse error (attempt %d): %s — raw: %s", attempt + 1, e, content[:200])
        except Exception as e:
            err_str = str(e)
            if "404" in err_str and "not found" in err_str.lower():
                logger.warning("  Model '%s' not found (404). Skipping retries for this model.", model)
                return None
            logger.warning("  Scoring API error (attempt %d): %s", attempt + 1, e)

    return None


def _save_score(attorney_id, score_data: Dict, model: str):
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO legal_cmd.attorney_scoring (
                attorney_id, sota_match_score, eckles_competency,
                commercial_litigation_focus, fannin_jurisdiction_match,
                ai_rationale, scored_by_model
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            attorney_id,
            score_data["sota_match_score"],
            score_data["eckles_competency"],
            score_data["commercial_litigation_focus"],
            score_data["fannin_jurisdiction_match"],
            score_data["ai_rationale"],
            model,
        ))

        cur.execute("""
            UPDATE legal_cmd.attorneys
            SET ai_score = %s, ai_score_reasoning = %s
            WHERE id = %s
        """, (
            score_data["sota_match_score"] / 10.0,
            score_data["ai_rationale"],
            attorney_id,
        ))

        conn.commit()
    except Exception as e:
        logger.error("  Error saving score for %s: %s", attorney_id, e)
        conn.rollback()
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Ranked report
# ---------------------------------------------------------------------------
def print_report(top_n: int = 10):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.first_name, a.last_name, a.firm_name, a.address, a.phone,
               a.website, a.practice_areas, a.outreach_status,
               s.sota_match_score, s.eckles_competency,
               s.commercial_litigation_focus, s.fannin_jurisdiction_match,
               s.ai_rationale, s.scored_by_model
        FROM legal_cmd.attorneys a
        JOIN legal_cmd.attorney_scoring s ON s.attorney_id = a.id
        ORDER BY s.sota_match_score DESC
        LIMIT %s
    """, (top_n,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        logger.info("No scored attorneys found. Run 'scrape' then 'score' first.")
        return

    print("\n" + "=" * 80)
    print("  FORTRESS LEGAL HEADHUNTER — TOP %d RANKED ATTORNEYS" % len(rows))
    print("  Case: Generali v. CROG (SUV2026000013, Fannin County)")
    print("=" * 80)

    for i, row in enumerate(rows, 1):
        first, last, firm, addr, phone, website, practice, outreach, score, eckles, comm, fannin, rationale, model = row
        flags = []
        if eckles:
            flags.append("ECKLES")
        if comm:
            flags.append("COMM-LIT")
        if fannin:
            flags.append("FANNIN")

        print(f"\n  #{i}  {first} {last}  [{score}/100]  {'  '.join(f'[{f}]' for f in flags)}")
        print(f"      Firm: {firm or 'Solo/Unknown'}")
        print(f"      Location: {addr or 'N/A'}")
        print(f"      Phone: {phone or 'N/A'}")
        if website:
            print(f"      Web: {website}")
        if practice:
            print(f"      Practice: {', '.join(practice)}")
        print(f"      Status: {outreach}")
        print(f"      AI: {rationale or 'N/A'}")
        print(f"      Model: {model}")

    print("\n" + "=" * 80)

    unscored_conn = get_db_conn()
    unscored_cur = unscored_conn.cursor()
    unscored_cur.execute("""
        SELECT COUNT(*) FROM legal_cmd.attorneys a
        LEFT JOIN legal_cmd.attorney_scoring s ON s.attorney_id = a.id
        WHERE s.id IS NULL AND a.status = 'active'
    """)
    unscored = unscored_cur.fetchone()[0]
    unscored_cur.close()
    unscored_conn.close()

    total_conn = get_db_conn()
    total_cur = total_conn.cursor()
    total_cur.execute("SELECT COUNT(*) FROM legal_cmd.attorneys WHERE status = 'active'")
    total = total_cur.fetchone()[0]
    total_cur.close()
    total_conn.close()

    print(f"  Total attorneys: {total}  |  Scored: {total - unscored}  |  Unscored: {unscored}")
    print("=" * 80 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Fortress Legal Headhunter Engine — Find and rank Georgia litigators",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  scrape     Search SerpAPI for Georgia commercial litigation attorneys
  score      AI-score all unscored attorneys (HYDRA R1-70B / SWARM fallback)
  import     Import attorneys from CSV file
  report     Print ranked top-N report
  full       Run scrape + score + report in sequence
        """,
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("scrape", help="Search SerpAPI for attorneys")

    subparsers.add_parser("score", help="AI-score all unscored attorneys")

    import_parser = subparsers.add_parser("import", help="Import from CSV")
    import_parser.add_argument("--csv", required=True, help="Path to CSV file")

    report_parser = subparsers.add_parser("report", help="Print ranked report")
    report_parser.add_argument("--top", type=int, default=10, help="Number of results (default: 10)")

    full_parser = subparsers.add_parser("full", help="Scrape + score + report")
    full_parser.add_argument("--top", type=int, default=10, help="Number of results (default: 10)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "scrape":
        profiles = scrape_attorneys()
        if profiles:
            ingest_profiles(profiles)
        else:
            logger.warning("No profiles scraped. Check SERPAPI_KEY in .env.")

    elif args.command == "score":
        score_unscored_attorneys()

    elif args.command == "import":
        profiles = import_csv(args.csv)
        if profiles:
            ingest_profiles(profiles)

    elif args.command == "report":
        print_report(top_n=args.top)

    elif args.command == "full":
        logger.info("=== FULL PIPELINE: Scrape -> Score -> Report ===")
        profiles = scrape_attorneys()
        if profiles:
            ingest_profiles(profiles)
        score_unscored_attorneys()
        print_report(top_n=args.top)


if __name__ == "__main__":
    main()
