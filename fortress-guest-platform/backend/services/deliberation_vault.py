"""
FORTRESS PRIME — DELIBERATION VAULT
====================================
Cryptographic provenance engine for the Legal Council of 9.

Every deliberation is frozen into an immutable event record:
    1. Context Freezing  — Qdrant vector UUIDs + text chunks
    2. Model Provenance  — Exact model version per seat
    3. Consensus Output   — Full opinions + consensus result
    4. SHA-256 Signature  — Deterministic hash of the canonical payload

The vault writes INSERT-ONLY to legal_cmd.deliberation_events.
UPDATE and DELETE are architecturally forbidden on this table.

Verification: recompute SHA-256 from stored fields and compare
against the sha256_signature column. A single bit change breaks
the hash — proof of non-tampering.
"""

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import psycopg2

try:
    from dotenv import load_dotenv

    _project_root = Path(__file__).resolve().parent.parent.parent.parent
    _fgp_root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(_fgp_root / ".env", override=False)
    load_dotenv(_project_root / ".env", override=False)
except ImportError:
    pass

logger = logging.getLogger("deliberation_vault")

# ═══════════════════════════════════════════════════════════════════════
# Database connection — fortress_db (legal_cmd schema)
# Uses psycopg2 (sync) for atomic INSERT with RETURNING.
# Credentials from environment, never hardcoded (Rule 006).
# ═══════════════════════════════════════════════════════════════════════

_DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
_DB_NAME = "fortress_db"
_DB_USER = os.getenv("DB_USER", os.getenv("FGP_DB_USER", "miner_bot"))
_DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))


def _get_vault_conn():
    """Open a connection to fortress_db for vault writes."""
    return psycopg2.connect(
        host=_DB_HOST,
        dbname=_DB_NAME,
        user=_DB_USER,
        password=_DB_PASS,
    )


def get_vault_connection():
    """Public accessor for read-only queries against the deliberation ledger."""
    return _get_vault_conn()


# ═══════════════════════════════════════════════════════════════════════
# Canonical Hashing
# ═══════════════════════════════════════════════════════════════════════

def compute_signature(
    case_slug: str,
    vector_ids: list[str],
    user_prompt: str,
    roster_snapshot: dict,
    seat_opinions: list[dict],
    counsel_results: dict,
) -> str:
    """
    Compute a deterministic SHA-256 signature over the canonical payload.

    Key-sorting and vector-sorting guarantee that identical inputs always
    produce the same hash, regardless of dict iteration order or list
    ordering of retrieved vectors.
    """
    payload = {
        "case_slug": case_slug,
        "vector_ids": sorted(vector_ids) if vector_ids else [],
        "user_prompt": user_prompt,
        "roster": roster_snapshot,
        "opinions": seat_opinions,
        "results": counsel_results,
    }
    payload_bytes = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()


def verify_signature(
    case_slug: str,
    vector_ids: list[str],
    user_prompt: str,
    roster_snapshot: dict,
    seat_opinions: list[dict],
    counsel_results: dict,
    expected_signature: str,
) -> bool:
    """Recompute the hash and check it against the stored signature."""
    actual = compute_signature(
        case_slug, vector_ids, user_prompt,
        roster_snapshot, seat_opinions, counsel_results,
    )
    return actual == expected_signature


# ═══════════════════════════════════════════════════════════════════════
# Vault Write (INSERT-ONLY)
# ═══════════════════════════════════════════════════════════════════════

_INSERT_SQL = """
    INSERT INTO legal_cmd.deliberation_events (
        case_slug, case_number, trigger_type,
        qdrant_vector_ids, context_chunks, user_prompt,
        moe_roster_snapshot, seat_opinions,
        counsel_results, consensus_signal, consensus_conviction,
        execution_time_ms, sha256_signature
    ) VALUES (
        %s, %s, %s,
        %s, %s, %s,
        %s, %s,
        %s, %s, %s,
        %s, %s
    )
    RETURNING event_id;
"""


def vault_deliberation(
    case_slug: str,
    case_number: Optional[str],
    trigger_type: str,
    vector_ids: list[str],
    context_chunks: list[str],
    user_prompt: str,
    roster_snapshot: dict,
    seat_opinions: list[dict],
    counsel_results: dict,
    execution_time_ms: int,
) -> tuple[str, str]:
    """
    Hash and persist a deliberation event to the immutable ledger.

    Returns (event_id, sha256_signature).

    Raises on duplicate signature (UNIQUE constraint) — which means the
    exact same deliberation was already vaulted. This is expected behavior
    for idempotency; callers should catch psycopg2.errors.UniqueViolation.
    """
    signature = compute_signature(
        case_slug, vector_ids, user_prompt,
        roster_snapshot, seat_opinions, counsel_results,
    )

    consensus_signal = counsel_results.get("consensus_signal")
    consensus_conviction = counsel_results.get("consensus_conviction")

    logger.info(
        "vaulting deliberation  case=%s  trigger=%s  vectors=%d  signature=%s…",
        case_slug, trigger_type, len(vector_ids), signature[:16],
    )

    conn = _get_vault_conn()
    cur = conn.cursor()
    try:
        cur.execute(_INSERT_SQL, (
            case_slug,
            case_number,
            trigger_type,
            vector_ids or None,
            context_chunks or None,
            user_prompt,
            json.dumps(roster_snapshot, sort_keys=True),
            json.dumps(seat_opinions, sort_keys=True),
            json.dumps(counsel_results, sort_keys=True),
            consensus_signal,
            consensus_conviction,
            execution_time_ms,
            signature,
        ))
        event_id = str(cur.fetchone()[0])
        conn.commit()

        logger.info(
            "vault_committed  event_id=%s  signature=%s",
            event_id, signature,
        )
        return event_id, signature

    except Exception:
        conn.rollback()
        logger.exception("vault_failed  case=%s  signature=%s", case_slug, signature)
        raise
    finally:
        cur.close()
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# Roster Loader (NAS-backed dynamic roster)
# ═══════════════════════════════════════════════════════════════════════

_ROSTER_PATH = os.getenv(
    "LEGAL_ROSTER_PATH",
    "/mnt/fortress_nas/sectors/legal/intelligence/active_roster.json",
)


def load_active_roster() -> dict:
    """
    Load the active MoE roster from NAS.

    Falls back to a minimal inline roster if the NAS file is unreachable,
    so deliberation is never blocked by a mount failure.
    """
    try:
        with open(_ROSTER_PATH, "r") as f:
            roster = json.load(f)
        logger.info("roster_loaded  path=%s  version=%s  seats=%d",
                     _ROSTER_PATH, roster.get("roster_version"), len(roster.get("seats", [])))
        return roster
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.warning("roster_fallback  error=%s  using_inline_defaults", exc)
        return _INLINE_FALLBACK_ROSTER


_INLINE_FALLBACK_ROSTER = {
    "roster_version": "1.0.0-fallback",
    "total_seats": 9,
    "seats": [
        {"seat": i, "provider": "HYDRA", "model_id": "deepseek-r1:70b"}
        for i in range(1, 10)
    ],
}
