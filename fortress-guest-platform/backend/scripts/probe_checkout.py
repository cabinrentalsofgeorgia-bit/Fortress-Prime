"""
Focused checkout-path probe for local VRS quote endpoints.
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Iterable

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


API_BASE = "http://127.0.0.1:8100"
REQUEST_TIMEOUT_SECONDS = 20.0


def sync_url_candidates(db_url: str) -> Iterable[str]:
    if not db_url:
        return []
    urls = [db_url]
    if "postgresql+asyncpg://" in db_url:
        urls.append(db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1))
        urls.append(db_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if "postgres://" in db_url:
        urls.append(db_url.replace("postgres://", "postgresql://", 1))

    deduped = []
    seen = set()
    for url in urls:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def build_sync_engine():
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL is missing. Set it in .env.")

    last_error = None
    for candidate in sync_url_candidates(db_url):
        try:
            engine = create_engine(candidate, future=True)
            with engine.connect():
                pass
            print(f"[db] connected via: {candidate}")
            return engine
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"Unable to connect to Postgres. Last error: {last_error}")


def get_active_property_id() -> str:
    engine = build_sync_engine()
    with engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'properties'
                    """
                )
            )
        }

        where_clauses = []
        if "is_active" in columns:
            where_clauses.append("is_active = true")
        if "active" in columns:
            where_clauses.append("active = true")
        if "status" in columns:
            where_clauses.append("status IN ('active', 'published', 'live')")

        where_sql = f"WHERE ({' OR '.join(where_clauses)})" if where_clauses else ""
        order_sql = "ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST"
        query = text(f"SELECT id::text FROM properties {where_sql} {order_sql} LIMIT 1")
        row = conn.execute(query).first()
        if not row:
            row = conn.execute(
                text(
                    """
                    SELECT id::text
                    FROM properties
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                    LIMIT 1
                    """
                )
            ).first()

        if not row:
            raise RuntimeError("No properties found in database.")

        return row[0]


def timed_request(client: httpx.Client, method: str, url: str, **kwargs):
    started = time.monotonic()
    response = client.request(method, url, **kwargs)
    elapsed_ms = (time.monotonic() - started) * 1000.0
    return response, elapsed_ms


def main() -> int:
    load_dotenv()

    property_id = get_active_property_id()
    check_in = date.today() + timedelta(days=30)
    check_out = date.today() + timedelta(days=35)

    payload = {
        "property_id": property_id,
        "guest_name": "Checkout Probe",
        "guest_email": "probe@example.com",
        "guest_phone": "+17065550100",
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "adults": 2,
    }

    print("[probe] checkout path probe starting")
    print(f"[probe] property_id={property_id}")
    print(f"[probe] check_in={payload['check_in']} check_out={payload['check_out']} adults=2")

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        try:
            generate_url = f"{API_BASE}/api/quotes/generate"
            gen_resp, gen_ms = timed_request(client, "POST", generate_url, json=payload)
            print(f"[probe] POST /api/quotes/generate -> status={gen_resp.status_code} time_ms={gen_ms:.2f}")
            if gen_resp.status_code != 200:
                print("[error] non-200 response body:")
                print(gen_resp.text)
                raise SystemExit(1)

            gen_json = gen_resp.json()
            quote_id = gen_json.get("id") or gen_json.get("quote_id")
            if not quote_id:
                print("[error] quote identifier missing in generate response:")
                print(gen_resp.text)
                raise SystemExit(1)
            print(f"[probe] quote_id={quote_id}")

            checkout_url = f"{API_BASE}/api/quotes/{quote_id}/checkout"
            chk_resp, chk_ms = timed_request(client, "GET", checkout_url)
            print(f"[probe] GET /api/quotes/{quote_id}/checkout -> status={chk_resp.status_code} time_ms={chk_ms:.2f}")
            if chk_resp.status_code != 200:
                print("[error] non-200 response body:")
                print(chk_resp.text)
                raise SystemExit(1)

            print("[probe] SUCCESS")
            print(
                f"[probe] summary: generate_status={gen_resp.status_code} generate_time_ms={gen_ms:.2f} "
                f"checkout_status={chk_resp.status_code} checkout_time_ms={chk_ms:.2f}"
            )
            return 0

        except httpx.TimeoutException as exc:
            print(f"[error] timeout during probe: {exc}")
            raise SystemExit(1)
        except httpx.RequestError as exc:
            print(f"[error] request failed: {exc}")
            raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
