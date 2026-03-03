"""
FORTRESS PRIME — INTELLIGENCE ENGINE
======================================
Backend engine for the Council of Giants intelligence platform.
Handles vote orchestration, database persistence, persona queries,
debate execution, and SSE streaming — called by master_console.py API.

Architecture:
    master_console.py (API) → intelligence_engine.py (engine) → persona_template.py (core)
                                                                → PostgreSQL (tracking)
                                                                → Redis (live streams)
                                                                → Qdrant (vectors)
"""

import os
import sys
import json
import uuid
import time
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

import psycopg2
import psycopg2.extras
import requests

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from persona_template import Persona, Council, Signal, Opinion

log = logging.getLogger("intelligence")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _get_db():
    return psycopg2.connect(
        database=os.getenv("DB_NAME", "fortress_db"),
        user="admin",
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


# ---------------------------------------------------------------------------
# Redis (optional — gracefully degrade to in-memory)
# ---------------------------------------------------------------------------

_vote_streams: Dict[str, Dict] = {}

try:
    import redis
    REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
    _redis = redis.Redis(host="localhost", port=6379, db=2, password=REDIS_PASS,
                         decode_responses=True)
    _redis.ping()
    _HAS_REDIS = True
    log.info("Redis connected for vote streaming")
except Exception:
    _HAS_REDIS = False
    log.info("Redis unavailable — using in-memory vote streams")


def _stream_set(vote_id: str, data: dict):
    payload = json.dumps(data)
    if _HAS_REDIS:
        _redis.hset(f"fortress:vote:{vote_id}", mapping={"state": payload})
        _redis.expire(f"fortress:vote:{vote_id}", 3600)
    _vote_streams[vote_id] = data


def _stream_get(vote_id: str) -> Optional[dict]:
    if _HAS_REDIS:
        raw = _redis.hget(f"fortress:vote:{vote_id}", "state")
        if raw:
            return json.loads(raw)
    return _vote_streams.get(vote_id)


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
if not QDRANT_API_KEY:
    import logging
    logging.warning("FORTRESS PROTOCOL: QDRANT_API_KEY not set — vector search may fail.")


def _get_collection_count(collection: str) -> int:
    try:
        r = requests.get(
            f"{QDRANT_URL}/collections/{collection}",
            headers={"api-key": QDRANT_API_KEY},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json().get("result", {}).get("points_count", 0)
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Persona listing
# ---------------------------------------------------------------------------

def list_personas() -> List[Dict]:
    """Return all 9 personas with metadata and scores."""
    slugs = Persona.list_all()
    conn = _get_db()
    cur = conn.cursor()

    personas = []
    for slug in sorted(slugs):
        try:
            p = Persona.load(slug)
        except Exception:
            continue

        vectors = _get_collection_count(p.vector_collection)

        cur.execute(
            "SELECT * FROM persona_scores WHERE persona_slug = %s", (slug,)
        )
        score_row = cur.fetchone() or {}

        personas.append({
            "slug": slug,
            "name": p.name,
            "archetype": p.archetype.value if hasattr(p.archetype, "value") else str(p.archetype),
            "worldview": p.worldview[:200],
            "bias": p.bias,
            "vector_collection": p.vector_collection,
            "vectors": vectors,
            "total_votes": score_row.get("total_votes", 0),
            "correct_votes": score_row.get("correct_votes", 0),
            "brier_score": score_row.get("brier_score", 0.0),
            "streak": score_row.get("streak", 0),
            "last_signal": score_row.get("last_signal"),
            "last_conviction": score_row.get("last_conviction"),
            "last_voted_at": score_row.get("last_voted_at", "").isoformat() if score_row.get("last_voted_at") else None,
        })

    conn.close()
    return personas


def get_persona_detail(slug: str) -> Dict:
    """Return full detail for a single persona + recent opinions."""
    p = Persona.load(slug)
    vectors = _get_collection_count(p.vector_collection)

    conn = _get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM persona_scores WHERE persona_slug = %s", (slug,))
    score_row = cur.fetchone() or {}

    cur.execute("""
        SELECT id, event, consensus_signal, created_at, opinions
        FROM council_votes
        ORDER BY created_at DESC
        LIMIT 20
    """)
    recent_opinions = []
    for row in cur.fetchall():
        for op in row.get("opinions", []):
            if op.get("persona", "").lower().replace("the ", "") == slug.replace("_", " "):
                recent_opinions.append({
                    "vote_id": str(row["id"]),
                    "event": row["event"][:100],
                    "signal": op.get("signal"),
                    "conviction": op.get("conviction"),
                    "reasoning": op.get("reasoning", "")[:150],
                    "date": row["created_at"].isoformat() if row.get("created_at") else None,
                })
            if len(recent_opinions) >= 10:
                break

    conn.close()

    return {
        "slug": slug,
        "name": p.name,
        "archetype": p.archetype.value if hasattr(p.archetype, "value") else str(p.archetype),
        "worldview": p.worldview,
        "bias": p.bias,
        "data_sources": p.data_sources,
        "trigger_events": p.trigger_events,
        "vector_collection": p.vector_collection,
        "vectors": vectors,
        "godhead_prompt": p.godhead_prompt[:300] + "..." if len(p.godhead_prompt) > 300 else p.godhead_prompt,
        "scores": {
            "total_votes": score_row.get("total_votes", 0),
            "correct_votes": score_row.get("correct_votes", 0),
            "brier_score": round(score_row.get("brier_score", 0.0), 3),
            "streak": score_row.get("streak", 0),
        },
        "recent_opinions": recent_opinions,
    }


# ---------------------------------------------------------------------------
# Council Vote (async with streaming)
# ---------------------------------------------------------------------------

def start_vote(event: str, context: Optional[str] = None,
               model: str = "qwen2.5:7b") -> str:
    """
    Start a Council vote in a background thread. Returns vote_id.
    Progress is streamed via _stream_set so SSE clients can poll.
    """
    vote_id = str(uuid.uuid4())

    _stream_set(vote_id, {
        "status": "starting",
        "event": event,
        "model": model,
        "personas_completed": 0,
        "personas_total": 9,
        "opinions": [],
    })

    thread = threading.Thread(
        target=_run_vote, args=(vote_id, event, context, model), daemon=True
    )
    thread.start()
    return vote_id


def _run_vote(vote_id: str, event: str, context: Optional[str], model: str):
    """Execute the Council vote in background, streaming progress."""
    try:
        slugs = sorted(Persona.list_all())
        personas = [Persona.load(s) for s in slugs]
        council = Council(personas)

        # Monkey-patch to capture per-persona progress
        completed = []
        original_analyze = Persona.analyze_event

        def tracked_analyze(self, ev, **kwargs):
            opinion = original_analyze(self, ev, **kwargs)
            completed.append(opinion.to_dict())
            _stream_set(vote_id, {
                "status": "voting",
                "event": event,
                "model": model,
                "personas_completed": len(completed),
                "personas_total": len(personas),
                "opinions": completed.copy(),
            })
            return opinion

        Persona.analyze_event = tracked_analyze

        try:
            result = council.vote_on(event, context=context, model=model)
        finally:
            Persona.analyze_event = original_analyze

        # Persist to database
        db_id = _persist_vote(vote_id, result, model)

        _stream_set(vote_id, {
            "status": "complete",
            "vote_id": vote_id,
            "db_id": db_id,
            **result,
        })

    except Exception as e:
        log.error("Vote %s failed: %s", vote_id, e)
        _stream_set(vote_id, {
            "status": "error",
            "event": event,
            "error": str(e),
        })


def _persist_vote(vote_id: str, result: dict, model: str) -> str:
    """Persist a completed Council vote to PostgreSQL and update persona_scores."""
    conn = _get_db()
    cur = conn.cursor()

    db_id = vote_id

    cur.execute("""
        INSERT INTO council_votes (
            id, event, model_used, consensus_signal, consensus_conviction,
            agreement_rate, bullish_count, bearish_count, neutral_count,
            total_voters, opinions, signal_breakdown, mode, elapsed_seconds
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
    """, (
        db_id, result["event"], model,
        result["consensus_signal"], result["consensus_conviction"],
        result["agreement_rate"],
        result["bullish_count"], result["bearish_count"], result["neutral_count"],
        result["total_voters"],
        json.dumps(result["opinions"]),
        json.dumps(result["signal_breakdown"]),
        result.get("mode"), result.get("elapsed_seconds"),
    ))

    # Update persona_scores with latest signal
    now = datetime.now()
    for op in result.get("opinions", []):
        persona_name = op.get("persona", "")
        # Map persona display name to slug
        slug = _name_to_slug(persona_name)
        if slug:
            cur.execute("""
                UPDATE persona_scores SET
                    total_votes = total_votes + 1,
                    last_signal = %s,
                    last_conviction = %s,
                    last_voted_at = %s,
                    last_updated = %s
                WHERE persona_slug = %s
            """, (op.get("signal"), op.get("conviction"), now, now, slug))

    conn.commit()
    conn.close()
    log.info("Vote %s persisted to database", db_id)
    return db_id


_SLUG_MAP = {
    "the jordi": "jordi", "the raoul": "raoul", "the lyn": "lyn",
    "the vol trader": "vol_trader", "the fed watcher": "fed_watcher",
    "the sound money hardliner": "sound_money",
    "the real estate mogul": "real_estate",
    "the permabear": "permabear", "the black swan hunter": "black_swan",
}


def _name_to_slug(name: str) -> Optional[str]:
    return _SLUG_MAP.get(name.lower().strip())


# ---------------------------------------------------------------------------
# Vote stream (for SSE)
# ---------------------------------------------------------------------------

def get_vote_stream(vote_id: str) -> Optional[dict]:
    return _stream_get(vote_id)


# ---------------------------------------------------------------------------
# Vote history
# ---------------------------------------------------------------------------

def get_vote_history(limit: int = 50, offset: int = 0) -> Dict:
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("SELECT count(*) as total FROM council_votes")
    total = cur.fetchone()["total"]

    cur.execute("""
        SELECT id, event, model_used, consensus_signal, consensus_conviction,
               agreement_rate, bullish_count, bearish_count, neutral_count,
               total_voters, signal_breakdown, mode, elapsed_seconds,
               created_at, resolved_at, actual_outcome, resolution_notes
        FROM council_votes
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, (limit, offset))

    votes = []
    for row in cur.fetchall():
        votes.append({
            "id": str(row["id"]),
            "event": row["event"],
            "model": row["model_used"],
            "consensus_signal": row["consensus_signal"],
            "conviction": round(row["consensus_conviction"], 2),
            "agreement_rate": round(row["agreement_rate"], 2),
            "bullish": row["bullish_count"],
            "bearish": row["bearish_count"],
            "neutral": row["neutral_count"],
            "voters": row["total_voters"],
            "signal_breakdown": row["signal_breakdown"],
            "mode": row["mode"],
            "elapsed": row["elapsed_seconds"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "resolved_at": row["resolved_at"].isoformat() if row.get("resolved_at") else None,
            "actual_outcome": row.get("actual_outcome"),
            "resolution_notes": row.get("resolution_notes"),
        })

    conn.close()
    return {"total": total, "votes": votes}


def get_vote_detail(vote_id: str) -> Optional[Dict]:
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM council_votes WHERE id = %s", (vote_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": str(row["id"]),
        "event": row["event"],
        "context": row.get("context"),
        "model": row["model_used"],
        "consensus_signal": row["consensus_signal"],
        "conviction": round(row["consensus_conviction"], 2),
        "agreement_rate": round(row["agreement_rate"], 2),
        "bullish": row["bullish_count"],
        "bearish": row["bearish_count"],
        "neutral": row["neutral_count"],
        "voters": row["total_voters"],
        "opinions": row.get("opinions", []),
        "signal_breakdown": row.get("signal_breakdown", {}),
        "mode": row.get("mode"),
        "elapsed": row.get("elapsed_seconds"),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "resolved_at": row["resolved_at"].isoformat() if row.get("resolved_at") else None,
        "actual_outcome": row.get("actual_outcome"),
        "resolution_notes": row.get("resolution_notes"),
    }


# ---------------------------------------------------------------------------
# Vote Resolution (Tier 2B)
# ---------------------------------------------------------------------------

def resolve_vote(vote_id: str, actual_outcome: str, notes: str = "") -> Dict:
    """
    Resolve a Council vote with the actual market outcome.
    Updates persona accuracy scores.
    """
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM council_votes WHERE id = %s", (vote_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": "Vote not found"}

    now = datetime.now()

    cur.execute("""
        UPDATE council_votes
        SET resolved_at = %s, actual_outcome = %s, resolution_notes = %s
        WHERE id = %s
    """, (now, actual_outcome, notes, vote_id))

    # Score each persona's prediction
    outcome_map = {
        "BULLISH": {"STRONG_BUY", "BUY"},
        "BEARISH": {"STRONG_SELL", "SELL"},
        "NEUTRAL": {"NEUTRAL"},
    }
    correct_signals = outcome_map.get(actual_outcome.upper(), set())

    for op in row.get("opinions", []):
        slug = _name_to_slug(op.get("persona", ""))
        if not slug:
            continue

        is_correct = op.get("signal", "") in correct_signals

        if is_correct:
            cur.execute("""
                UPDATE persona_scores SET
                    correct_votes = correct_votes + 1,
                    streak = CASE WHEN streak >= 0 THEN streak + 1 ELSE 1 END,
                    last_updated = %s
                WHERE persona_slug = %s
            """, (now, slug))
        else:
            cur.execute("""
                UPDATE persona_scores SET
                    streak = CASE WHEN streak <= 0 THEN streak - 1 ELSE -1 END,
                    last_updated = %s
                WHERE persona_slug = %s
            """, (now, slug))

        # Update Brier score (running average)
        conviction = op.get("conviction", 0.5)
        actual_val = 1.0 if is_correct else 0.0
        brier_component = (conviction - actual_val) ** 2

        cur.execute("""
            UPDATE persona_scores SET
                brier_score = (brier_score * (total_votes - 1) + %s) / total_votes
            WHERE persona_slug = %s AND total_votes > 0
        """, (brier_component, slug))

    conn.commit()
    conn.close()

    return {"status": "resolved", "vote_id": vote_id, "outcome": actual_outcome}


# ---------------------------------------------------------------------------
# Debate
# ---------------------------------------------------------------------------

def run_debate(persona_a_slug: str, persona_b_slug: str, topic: str,
               model: str = "qwen2.5:7b") -> Dict:
    """Run a debate between two personas."""
    pa = Persona.load(persona_a_slug)
    pb = Persona.load(persona_b_slug)

    debate = pa.debate_with(pb, topic)

    return {
        "topic": topic,
        "persona_a": {
            "name": debate.persona_a,
            "slug": persona_a_slug,
            "signal": debate.opinion_a.signal.value,
            "conviction": debate.opinion_a.conviction,
            "reasoning": debate.opinion_a.reasoning,
            "assets": debate.opinion_a.assets,
            "risk_factors": debate.opinion_a.risk_factors,
            "catalysts": debate.opinion_a.catalysts,
        },
        "persona_b": {
            "name": debate.persona_b,
            "slug": persona_b_slug,
            "signal": debate.opinion_b.signal.value,
            "conviction": debate.opinion_b.conviction,
            "reasoning": debate.opinion_b.reasoning,
            "assets": debate.opinion_b.assets,
            "risk_factors": debate.opinion_b.risk_factors,
            "catalysts": debate.opinion_b.catalysts,
        },
        "agreement_score": round(debate.agreement_score(), 2),
        "timestamp": debate.timestamp,
    }


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def get_leaderboard() -> List[Dict]:
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT persona_slug, persona_name, total_votes, correct_votes,
               brier_score, streak, last_signal, last_conviction, last_voted_at
        FROM persona_scores
        ORDER BY
            CASE WHEN total_votes > 0
                 THEN correct_votes::float / total_votes
                 ELSE 0 END DESC,
            total_votes DESC
    """)

    board = []
    for row in cur.fetchall():
        tv = row["total_votes"]
        cv = row["correct_votes"]
        accuracy = round(cv / tv * 100, 1) if tv > 0 else 0.0
        board.append({
            "slug": row["persona_slug"],
            "name": row["persona_name"],
            "total_votes": tv,
            "correct_votes": cv,
            "accuracy_pct": accuracy,
            "brier_score": round(row["brier_score"], 3),
            "streak": row["streak"],
            "last_signal": row["last_signal"],
            "last_conviction": row["last_conviction"],
            "last_voted_at": row["last_voted_at"].isoformat() if row.get("last_voted_at") else None,
        })

    conn.close()
    return board
