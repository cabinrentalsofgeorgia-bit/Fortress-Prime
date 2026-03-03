"""
Universal Triage Router — Enterprise Financial Document Classifier

Consumes ``enterprise.inbox.raw`` from Redpanda, classifies each payload
into a bounded context (WEALTH vs TRUST), and dispatches to the correct
downstream domain:

  WEALTH  → ``development.expenses.logged``  (Wealth Swarm / Division 4)
  TRUST   → CF-04 Iron Dome ledger           (Trust Accounting / CROG-VRS)
  UNKNOWN → ``system.health.alerts``          (Human review queue)

Three-node LangGraph pipeline:
  1. Extractor  (SWARM)  — deterministic JSON from raw text
  2. Classifier (SWARM + Layer 3 pgvector RAG) — bounded context routing
  3. Dispatcher          — stages the routed payload for async publish

The Redpanda consumer loop handles actual event publishing after the
synchronous graph completes, avoiding async-in-sync conflicts.

Usage (daemon):
    python3 src/triage_router_swarm.py
"""

import os
import sys
import json
import asyncio
import logging
from decimal import Decimal
from typing import TypedDict, List, Optional

import time
import httpx
import psycopg2
import psycopg2.extras
from openai import NotFoundError, APIConnectionError, APITimeoutError
from langgraph.graph import StateGraph, END
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_inference_client, get_embeddings_url
from src.event_publisher import EventPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("triage_router")

REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
CONSUMER_GROUP = "triage_router_v11"
EMBED_MODEL = "nomic-embed-text"
LLM_MAX_RETRIES = 8
INFERENCE_DIRECT = "http://192.168.0.106:11434/v1"  # Spark-04 (Sovereign) — qwen2.5:7b + deepseek-r1:70b


def _llm_with_retry(client, **kwargs):
    """Retry OpenAI-compatible calls; falls back to direct Spark-03 after 4 LB misses."""
    from openai import OpenAI as _OpenAI

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            target = client
            if attempt > 4:
                target = _OpenAI(base_url=INFERENCE_DIRECT, api_key="not-needed", timeout=300.0)
                log.info("[LLM] Falling back to direct inference node (attempt %d)", attempt)
            return target.chat.completions.create(**kwargs)
        except (NotFoundError, APIConnectionError, APITimeoutError) as e:
            if attempt == LLM_MAX_RETRIES:
                raise
            log.warning("[LLM] Attempt %d/%d failed (%s), retrying...", attempt, LLM_MAX_RETRIES, type(e).__name__)
            time.sleep(0.5 * attempt)

FORTRESS_DB_DSN = (
    f"host={os.getenv('DB_HOST', 'localhost')} "
    f"port={os.getenv('DB_PORT', '5432')} "
    f"dbname={os.getenv('DB_NAME', 'fortress_db')} "
    f"user={os.getenv('DB_USER', 'miner_bot')} "
    f"password={os.getenv('DB_PASSWORD', '')}"
)

# ---------------------------------------------------------------------------
# Category → Bounded Context mapping
# ---------------------------------------------------------------------------
# Layer 3 uses 18 vendor categories. This maps them to domain boundaries.

TRUST_CATEGORIES = frozenset({
    "MAINTENANCE", "CLEANING", "UTILITIES", "SUPPLIES",
    "INSURANCE", "PROPERTY_TAX", "SUBSCRIPTIONS", "ADVERTISING",
    "PROFESSIONAL_SERVICES", "CROG_INTERNAL", "MORTGAGE_INTEREST",
})

WEALTH_CATEGORIES = frozenset({
    "PERSONAL_EXPENSE", "FAMILY_INTERNAL", "OWNER_PRINCIPAL",
})

LEGAL_CATEGORIES = frozenset({
    "LITIGATION_RECOVERY",
})


def _category_to_domain(category: str) -> str:
    """Map a Layer 3 vendor classification to a bounded context."""
    cat = category.upper().strip()
    if cat in TRUST_CATEGORIES:
        return "TRUST"
    if cat in WEALTH_CATEGORIES:
        return "WEALTH"
    if cat in LEGAL_CATEGORIES:
        return "LEGAL"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------

class TriageState(TypedDict):
    raw_text: str
    vendor: str
    amount: float
    description: str
    domain: str
    rag_category: str
    rag_reasoning: str
    dispatch_topic: str
    dispatch_payload: dict
    audit_trail: List[str]


# ---------------------------------------------------------------------------
# Node 1: Entity Extractor (SWARM)
# ---------------------------------------------------------------------------

def extractor_node(state: TriageState) -> dict:
    """Extract vendor, amount, and description from raw text."""
    log.info("[TRIAGE] Extractor parsing raw payload...")
    client, model = get_inference_client("SWARM")

    prompt = (
        "Extract the vendor name, total dollar amount, and a brief description "
        "of goods or services from this text.\n\n"
        f"TEXT: {state['raw_text']}\n\n"
        'Respond ONLY with valid JSON: '
        '{"vendor": "name", "amount": 0.00, "description": "brief details"}'
    )

    try:
        resp = _llm_with_retry(
            client,
            model=model,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        extracted = json.loads(resp.choices[0].message.content)
    except Exception as e:
        log.error("Extraction failed: %s", e)
        extracted = {"vendor": "PARSE_ERROR", "amount": 0.0, "description": ""}

    vendor = extracted.get("vendor", "UNKNOWN")
    amount = float(extracted.get("amount", 0.0))
    trail = list(state.get("audit_trail", []))
    trail.append(f"extractor: vendor={vendor}, amount=${amount:.2f}")

    return {
        "vendor": vendor,
        "amount": amount,
        "description": extracted.get("description", ""),
        "audit_trail": trail,
    }


# ---------------------------------------------------------------------------
# Node 2: Layer 3 RAG Classifier
# ---------------------------------------------------------------------------

def _embed_sync(text: str) -> list[float]:
    """Generate embedding via nomic-embed-text (sync)."""
    try:
        url = get_embeddings_url()
    except Exception:
        url = "http://localhost:11434/api/embeddings"
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, json={"model": EMBED_MODEL, "prompt": text[:8000]})
        resp.raise_for_status()
        return resp.json().get("embedding", [])


RAG_SIMILARITY_THRESHOLD = 0.65


def _query_layer3_rag(vector: list[float]) -> Optional[tuple[str, str, float]]:
    """Query finance.classification_rules pgvector for nearest vendor match.

    Returns (category, reasoning, similarity) or None.
    """
    try:
        conn = psycopg2.connect(FORTRESS_DB_DSN)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT assigned_category, reasoning, vendor_pattern,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM finance.classification_rules
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT 1
            """,
            (vector, vector),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            sim = row["similarity"]
            log.info("[RAG] Nearest match: vendor_pattern=%s, category=%s, similarity=%.4f (threshold=%.2f)",
                     row.get("vendor_pattern", "?")[:50], row["assigned_category"], sim, RAG_SIMILARITY_THRESHOLD)
            if sim >= RAG_SIMILARITY_THRESHOLD:
                return row["assigned_category"], row.get("reasoning") or row.get("vendor_pattern", ""), sim
            log.info("[RAG] Below threshold — ignoring match.")
    except Exception as e:
        log.error("Layer 3 RAG query failed: %s", e)
    return None


def classifier_node(state: TriageState) -> dict:
    """Classify vendor into bounded context via Layer 3 RAG + LLM fallback."""
    log.info("[TRIAGE] Classifying vendor: %s", state.get("vendor", ""))
    search_text = f"{state.get('vendor', '')} {state.get('description', '')}"
    trail = list(state.get("audit_trail", []))

    domain = "UNKNOWN"
    rag_category = ""
    rag_reasoning = ""

    vector = _embed_sync(search_text)
    if vector:
        result = _query_layer3_rag(vector)
        if result:
            rag_category, rag_reasoning, sim = result
            domain = _category_to_domain(rag_category)
            log.info("[TRIAGE] RAG hit: category=%s, sim=%.4f, reasoning=%s → domain=%s", rag_category, sim, rag_reasoning[:60], domain)
            trail.append(f"classifier_rag: category={rag_category}, sim={sim:.4f}, domain={domain}")

    if domain == "UNKNOWN":
        log.info("[TRIAGE] RAG inconclusive, falling back to LLM classification...")
        client, model = get_inference_client("SWARM")
        prompt = (
            f"Classify this expense for a property management company:\n"
            f"Vendor: {state.get('vendor', '')}\n"
            f"Description: {state.get('description', '')}\n\n"
            f"Is this a property DEVELOPMENT/CONSTRUCTION expense for the owner's "
            f"personal portfolio (respond WEALTH), or a routine property "
            f"MANAGEMENT/MAINTENANCE expense for rental cabins (respond TRUST)?\n\n"
            f"Respond with ONLY the word WEALTH or TRUST."
        )
        try:
            resp = _llm_with_retry(
                client,
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=10,
            )
            llm_answer = resp.choices[0].message.content.strip().upper()
            if "WEALTH" in llm_answer:
                domain = "WEALTH"
            elif "TRUST" in llm_answer:
                domain = "TRUST"
            trail.append(f"classifier_llm_fallback: domain={domain}")
        except Exception as e:
            log.error("LLM fallback failed: %s", e)
            trail.append(f"classifier_llm_fallback: ERROR {e}")

    return {
        "domain": domain,
        "rag_category": rag_category,
        "rag_reasoning": rag_reasoning,
        "audit_trail": trail,
    }


# ---------------------------------------------------------------------------
# Routing Logic
# ---------------------------------------------------------------------------

def route_to_domain(state: TriageState) -> str:
    domain = state.get("domain", "UNKNOWN")
    if domain == "WEALTH":
        return "dispatch_wealth"
    if domain == "TRUST":
        return "dispatch_trust"
    if domain == "LEGAL":
        return "dispatch_legal"
    return "dispatch_unknown"


# ---------------------------------------------------------------------------
# Node 3A: Wealth Dispatcher
# ---------------------------------------------------------------------------

def dispatch_wealth(state: TriageState) -> dict:
    """Stage payload for the Wealth Swarm (development.expenses.logged)."""
    log.info("[TRIAGE] Routing to Sovereign Wealth Swarm.")
    trail = list(state.get("audit_trail", []))
    payload = {
        "receipt_text": state["raw_text"],
        "triage_vendor": state.get("vendor", ""),
        "triage_amount": state.get("amount", 0.0),
        "triage_category": state.get("rag_category", ""),
        "audit_trail": trail,
    }
    trail.append("dispatch: development.expenses.logged (STAGED)")
    return {
        "dispatch_topic": "development.expenses.logged",
        "dispatch_payload": payload,
        "audit_trail": trail,
    }


# ---------------------------------------------------------------------------
# Node 3B: Trust Ledger Dispatcher
# ---------------------------------------------------------------------------

def dispatch_trust(state: TriageState) -> dict:
    """Stage payload for CF-04 Iron Dome trust accounting."""
    log.info("[TRIAGE] Routing to CF-04 Trust Accounting Ledger.")
    trail = list(state.get("audit_trail", []))
    payload = {
        "vendor": state.get("vendor", ""),
        "amount": state.get("amount", 0.0),
        "description": state.get("description", ""),
        "rag_category": state.get("rag_category", ""),
        "rag_reasoning": state.get("rag_reasoning", ""),
        "audit_trail": trail,
    }
    trail.append("dispatch: trust.accounting.staged (STAGED)")
    return {
        "dispatch_topic": "trust.accounting.staged",
        "dispatch_payload": payload,
        "audit_trail": trail,
    }


# ---------------------------------------------------------------------------
# Node 3C: Unknown / Human Review
# ---------------------------------------------------------------------------

def dispatch_legal(state: TriageState) -> dict:
    """Stage payload for the Legal Command Center."""
    log.info("[TRIAGE] Routing to Legal Command Center.")
    trail = list(state.get("audit_trail", []))
    payload = {
        "vendor": state.get("vendor", ""),
        "amount": state.get("amount", 0.0),
        "description": state.get("description", ""),
        "rag_category": state.get("rag_category", ""),
        "rag_reasoning": state.get("rag_reasoning", ""),
        "audit_trail": trail,
    }
    trail.append("dispatch: legal.intake.staged (STAGED)")
    return {
        "dispatch_topic": "legal.intake.staged",
        "dispatch_payload": payload,
        "audit_trail": trail,
    }


def dispatch_unknown(state: TriageState) -> dict:
    """Route unclassifiable payloads to the human review queue."""
    log.warning("[TRIAGE] Unclassifiable payload — routing to human review.")
    trail = list(state.get("audit_trail", []))
    payload = {
        "type": "triage_unclassified",
        "vendor": state.get("vendor", ""),
        "amount": state.get("amount", 0.0),
        "raw_text": state["raw_text"][:500],
        "audit_trail": trail,
    }
    trail.append("dispatch: system.health.alerts (HUMAN REVIEW)")
    return {
        "dispatch_topic": "system.health.alerts",
        "dispatch_payload": payload,
        "audit_trail": trail,
    }


# ---------------------------------------------------------------------------
# Graph Assembly
# ---------------------------------------------------------------------------

workflow = StateGraph(TriageState)
workflow.add_node("extractor", extractor_node)
workflow.add_node("classifier", classifier_node)
workflow.add_node("dispatch_wealth", dispatch_wealth)
workflow.add_node("dispatch_trust", dispatch_trust)
workflow.add_node("dispatch_legal", dispatch_legal)
workflow.add_node("dispatch_unknown", dispatch_unknown)

workflow.set_entry_point("extractor")
workflow.add_edge("extractor", "classifier")
workflow.add_conditional_edges("classifier", route_to_domain)
workflow.add_edge("dispatch_wealth", END)
workflow.add_edge("dispatch_trust", END)
workflow.add_edge("dispatch_legal", END)
workflow.add_edge("dispatch_unknown", END)

triage_swarm = workflow.compile()


# ---------------------------------------------------------------------------
# Redpanda Consumer Daemon
# ---------------------------------------------------------------------------

async def consume_inbox():
    """Long-running consumer: enterprise.inbox.raw -> triage_swarm -> publish."""
    consumer = AIOKafkaConsumer(
        "enterprise.inbox.raw",
        bootstrap_servers=REDPANDA_BROKER,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        max_poll_interval_ms=600_000,
        session_timeout_ms=60_000,
    )
    await consumer.start()
    log.info("Universal Triage Router online — consuming enterprise.inbox.raw")

    try:
        async for msg in consumer:
            raw_text = msg.value.get("text", "")
            if not raw_text.strip():
                continue

            initial_state: TriageState = {
                "raw_text": raw_text,
                "vendor": "",
                "amount": 0.0,
                "description": "",
                "domain": "",
                "rag_category": "",
                "rag_reasoning": "",
                "dispatch_topic": "",
                "dispatch_payload": {},
                "audit_trail": ["INIT: Received from enterprise.inbox.raw"],
            }

            try:
                final = await asyncio.to_thread(triage_swarm.invoke, initial_state)
            except Exception as e:
                log.error("Swarm execution failed: %s", e)
                continue

            topic = final.get("dispatch_topic")
            payload = final.get("dispatch_payload", {})
            if topic and payload:
                try:
                    await EventPublisher.publish(
                        topic=topic,
                        payload=payload,
                        key=final.get("vendor", "unknown"),
                    )
                    log.info(
                        "Dispatched to %s (vendor=%s, amount=$%.2f, domain=%s)",
                        topic,
                        final.get("vendor", "?"),
                        final.get("amount", 0),
                        final.get("domain", "?"),
                    )
                except Exception as e:
                    log.error("Redpanda publish failed for %s: %s", topic, e)

    except asyncio.CancelledError:
        log.info("Triage Router shutdown initiated.")
    finally:
        await consumer.stop()
        log.info("Consumer stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(consume_inbox())
    except KeyboardInterrupt:
        log.info("FORTRESS PROTOCOL: Manual shutdown of Triage Router.")
