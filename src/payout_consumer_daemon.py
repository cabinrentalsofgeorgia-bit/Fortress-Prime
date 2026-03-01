"""
Payout Consumer Daemon — Continuous Liquidity Pipeline (Production Hardened)

Consumes ``trust.payout.staged`` events emitted by the Revenue Consumer after
the 65/35 split is journaled. For each event:

  1. Idempotency gate — skip if already processed or in-flight
  2. Stripe Connect account lookup
  3. Threshold gate — hold sub-$25 payouts for accumulation
  4. Batch release — when held payouts for a property exceed threshold
  5. Circuit breaker — pause on consecutive Stripe failures
  6. Retry with exponential backoff (3 attempts via tenacity)
  7. DLQ routing on unrecoverable errors
  8. Manual Kafka offset commit (at-least-once delivery)

Transfer creation sets status='processing'. The Stripe Connect webhook
handler advances to 'completed' on transfer.paid and journals the
liability-clearing entry. This daemon never marks a transfer 'completed'.

Usage:
    python3 src/payout_consumer_daemon.py
"""

import os
import sys
import json
import time
import asyncio
import logging
import hashlib
from decimal import Decimal, ROUND_HALF_UP

import psycopg2
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("payout_consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
TOPIC = "trust.payout.staged"
DLQ_TOPIC = "trust.payout.dlq"
GROUP_ID = "fortress-payout-consumer"

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "fortress_guest"
DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
MINIMUM_PAYOUT_AMOUNT = float(os.getenv("MINIMUM_PAYOUT_AMOUNT", "25.00"))

TWO = Decimal("0.01")


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------
class CircuitBreaker:
    """Trips after N consecutive Stripe failures; resets after cooldown."""

    def __init__(self, threshold: int = 3, cooldown_seconds: int = 300):
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._consecutive_failures = 0
        self._tripped_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._tripped_at is None:
            return False
        elapsed = time.monotonic() - self._tripped_at
        if elapsed >= self._cooldown:
            log.info("CIRCUIT BREAKER: Cooldown elapsed (%.0fs). Resetting to CLOSED.", elapsed)
            self._tripped_at = None
            self._consecutive_failures = 0
            return False
        return True

    def record_success(self):
        self._consecutive_failures = 0
        if self._tripped_at is not None:
            log.info("CIRCUIT BREAKER: Probe succeeded. Resetting to CLOSED.")
            self._tripped_at = None

    def record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold and self._tripped_at is None:
            self._tripped_at = time.monotonic()
            log.error(
                "CIRCUIT BREAKER TRIPPED: %d consecutive Stripe failures. "
                "Pausing payout execution for %ds.",
                self._consecutive_failures,
                self._cooldown,
            )


circuit = CircuitBreaker(threshold=3, cooldown_seconds=300)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def _get_conn():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def _lookup_stripe_account(conn, property_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT stripe_account_id, account_status FROM owner_payout_accounts WHERE property_id = %s",
            (property_id,),
        )
        row = cur.fetchone()
        if row:
            return row[0], row[1]
    return None, None


def _already_paid(conn, confirmation_code: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM payout_ledger WHERE confirmation_code = %s "
            "AND status IN ('completed', 'processing', 'settled') LIMIT 1",
            (confirmation_code,),
        )
        return cur.fetchone() is not None


def _idempotency_key(confirmation_code: str) -> str:
    """Deterministic idempotency key derived from confirmation code."""
    return hashlib.sha256(f"crog-payout-{confirmation_code}".encode()).hexdigest()[:32]


def _get_held_total(conn, property_id: str) -> float:
    """Sum of all held payouts for this property."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(owner_amount), 0) FROM payout_ledger "
            "WHERE property_id = %s AND status = 'held'",
            (property_id,),
        )
        return float(cur.fetchone()[0])


def _release_held_payouts(conn, property_id: str, batch_id: str) -> list[dict]:
    """Mark all held payouts for a property as processing under a batch ID.

    Returns the list of held rows for logging.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE payout_ledger
            SET status = 'processing', batch_id = %s, initiated_at = NOW()
            WHERE property_id = %s AND status = 'held'
            RETURNING id, confirmation_code, owner_amount
            """,
            (batch_id, property_id),
        )
        return [
            {"id": r[0], "confirmation_code": r[1], "owner_amount": float(r[2])}
            for r in cur.fetchall()
        ]


# ---------------------------------------------------------------------------
# Stripe Transfer with retry
# ---------------------------------------------------------------------------
def _create_stripe_transfer(
    stripe_acct: str,
    amount: float,
    confirmation_code: str,
    property_id: str,
    payout_id: int,
    batch_id: str | None = None,
):
    """Execute a Stripe Transfer with tenacity retry and idempotency key."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    idem_key = _idempotency_key(
        f"{confirmation_code}-{batch_id}" if batch_id else confirmation_code
    )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=32),
        retry=retry_if_exception_type((
            stripe.error.APIConnectionError,
            stripe.error.RateLimitError,
            stripe.error.APIError,
        )),
        reraise=True,
    )
    def _do_transfer():
        desc = f"CROG Payout: {confirmation_code}"
        if batch_id:
            desc = f"CROG Batch Payout: {batch_id}"
        return stripe.Transfer.create(
            amount=int(amount * 100),
            currency="usd",
            destination=stripe_acct,
            description=desc,
            idempotency_key=idem_key,
            metadata={
                "property_id": property_id,
                "confirmation_code": confirmation_code,
                "payout_ledger_id": str(payout_id),
                "batch_id": batch_id or "",
            },
        )

    return _do_transfer()


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
def process_payout(payload: dict) -> str:
    """Execute payout or stage for manual/held processing.

    Returns a status string: 'skipped', 'manual', 'held', 'processing',
    'batch_processing', 'failed', or 'circuit_open'.
    """
    property_id = payload.get("property_id", "")
    confirmation_code = payload.get("confirmation_code", "")
    journal_entry_id = payload.get("journal_entry_id")
    gross_amount = float(payload.get("gross_amount", 0))
    owner_amount = float(payload.get("owner_amount", 0))

    if owner_amount <= 0:
        log.info("Skipping zero-amount payout for %s", confirmation_code)
        return "skipped"

    conn = _get_conn()
    try:
        if _already_paid(conn, confirmation_code):
            log.info("IDEMPOTENT SKIP: Payout for %s already processed", confirmation_code)
            return "skipped"

        stripe_acct, acct_status = _lookup_stripe_account(conn, property_id)

        # --- No Stripe account: manual fallback ---
        if not stripe_acct or acct_status != "active" or not STRIPE_SECRET_KEY:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO payout_ledger
                            (property_id, confirmation_code, journal_entry_id,
                             gross_amount, owner_amount, status, idempotency_key)
                        VALUES (%s, %s, %s, %s, %s, 'manual', %s)
                        """,
                        (property_id, confirmation_code, journal_entry_id,
                         gross_amount, owner_amount,
                         _idempotency_key(confirmation_code)),
                    )
            log.info(
                "MANUAL PAYOUT STAGED: %s | $%.2f (no active Stripe account)",
                confirmation_code, owner_amount,
            )
            return "manual"

        # --- Threshold gate: hold small payouts ---
        if owner_amount < MINIMUM_PAYOUT_AMOUNT:
            held_total = _get_held_total(conn, property_id)
            new_total = held_total + owner_amount

            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO payout_ledger
                            (property_id, confirmation_code, journal_entry_id,
                             gross_amount, owner_amount, status, idempotency_key)
                        VALUES (%s, %s, %s, %s, %s, 'held', %s)
                        """,
                        (property_id, confirmation_code, journal_entry_id,
                         gross_amount, owner_amount,
                         _idempotency_key(confirmation_code)),
                    )

            log.info(
                "PAYOUT HELD (below $%.2f threshold): %s | $%.2f | held_total=$%.2f",
                MINIMUM_PAYOUT_AMOUNT, confirmation_code, owner_amount, new_total,
            )

            if new_total >= MINIMUM_PAYOUT_AMOUNT:
                return _release_batch(conn, property_id, stripe_acct)

            return "held"

        # --- Circuit breaker check ---
        if circuit.is_open:
            log.warning(
                "CIRCUIT OPEN: Deferring payout for %s ($%.2f) — Stripe cooldown active",
                confirmation_code, owner_amount,
            )
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO payout_ledger
                            (property_id, confirmation_code, journal_entry_id,
                             gross_amount, owner_amount, status, idempotency_key)
                        VALUES (%s, %s, %s, %s, %s, 'held', %s)
                        """,
                        (property_id, confirmation_code, journal_entry_id,
                         gross_amount, owner_amount,
                         _idempotency_key(confirmation_code)),
                    )
            return "circuit_open"

        # --- Execute Stripe Transfer ---
        return _execute_transfer(
            conn, stripe_acct, property_id, confirmation_code,
            journal_entry_id, gross_amount, owner_amount,
        )

    except Exception as e:
        log.error("PAYOUT PROCESSING ERROR: %s — %s", confirmation_code, e)
        raise
    finally:
        conn.close()


def _execute_transfer(
    conn, stripe_acct: str, property_id: str, confirmation_code: str,
    journal_entry_id, gross_amount: float, owner_amount: float,
    batch_id: str | None = None,
) -> str:
    """Insert ledger row as 'processing' and call Stripe."""
    import stripe as stripe_mod

    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO payout_ledger
                    (property_id, confirmation_code, journal_entry_id,
                     gross_amount, owner_amount, status, initiated_at,
                     idempotency_key, batch_id)
                VALUES (%s, %s, %s, %s, %s, 'processing', NOW(), %s, %s)
                RETURNING id
                """,
                (property_id, confirmation_code, journal_entry_id,
                 gross_amount, owner_amount,
                 _idempotency_key(
                     f"{confirmation_code}-{batch_id}" if batch_id else confirmation_code
                 ),
                 batch_id),
            )
            payout_id = cur.fetchone()[0]

    try:
        transfer = _create_stripe_transfer(
            stripe_acct, owner_amount, confirmation_code,
            property_id, payout_id, batch_id,
        )

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payout_ledger
                    SET stripe_transfer_id = %s,
                        retry_count = 0
                    WHERE id = %s
                    """,
                    (transfer.id, payout_id),
                )

        circuit.record_success()

        log.info(
            "STRIPE TRANSFER INITIATED: %s | $%.2f → %s | Transfer %s (status=processing)",
            confirmation_code, owner_amount, stripe_acct[:12] + "...", transfer.id,
        )
        return "batch_processing" if batch_id else "processing"

    except stripe_mod.StripeError as e:
        circuit.record_failure()

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payout_ledger
                    SET status = 'failed',
                        failure_reason = %s,
                        retry_count = retry_count + 1
                    WHERE id = %s
                    """,
                    (str(e)[:500], payout_id),
                )
        log.error(
            "STRIPE TRANSFER FAILED (after retries): %s | $%.2f — %s",
            confirmation_code, owner_amount, e,
        )
        return "failed"


def _release_batch(conn, property_id: str, stripe_acct: str) -> str:
    """Release accumulated held payouts as a single batch transfer."""
    batch_id = f"BATCH-{property_id}-{int(time.time())}"

    with conn:
        released = _release_held_payouts(conn, property_id, batch_id)

    if not released:
        return "held"

    batch_total = sum(r["owner_amount"] for r in released)
    codes = [r["confirmation_code"] for r in released]

    log.info(
        "BATCH RELEASE: %s | %d payouts | $%.2f | codes=%s",
        batch_id, len(released), batch_total, ",".join(codes[:5]),
    )

    if circuit.is_open:
        log.warning("CIRCUIT OPEN during batch release — batch %s deferred", batch_id)
        return "circuit_open"

    import stripe as stripe_mod

    idem_key = _idempotency_key(batch_id)

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=32),
            retry=retry_if_exception_type((
                stripe_mod.error.APIConnectionError,
                stripe_mod.error.RateLimitError,
                stripe_mod.error.APIError,
            )),
            reraise=True,
        )
        def _do_batch_transfer():
            return stripe.Transfer.create(
                amount=int(batch_total * 100),
                currency="usd",
                destination=stripe_acct,
                description=f"CROG Batch Payout: {batch_id} ({len(released)} reservations)",
                idempotency_key=idem_key,
                metadata={
                    "property_id": property_id,
                    "batch_id": batch_id,
                    "payout_count": str(len(released)),
                    "confirmation_codes": ",".join(codes[:10]),
                },
            )

        transfer = _do_batch_transfer()

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payout_ledger
                    SET stripe_transfer_id = %s
                    WHERE batch_id = %s AND status = 'processing'
                    """,
                    (transfer.id, batch_id),
                )

        circuit.record_success()

        log.info(
            "BATCH TRANSFER INITIATED: %s | $%.2f → %s | Transfer %s",
            batch_id, batch_total, stripe_acct[:12] + "...", transfer.id,
        )
        return "batch_processing"

    except stripe_mod.StripeError as e:
        circuit.record_failure()

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE payout_ledger
                    SET status = 'failed', failure_reason = %s
                    WHERE batch_id = %s AND status = 'processing'
                    """,
                    (str(e)[:500], batch_id),
                )

        log.error("BATCH TRANSFER FAILED: %s | $%.2f — %s", batch_id, batch_total, e)
        return "failed"


# ---------------------------------------------------------------------------
# DLQ publisher
# ---------------------------------------------------------------------------
_dlq_producer: AIOKafkaProducer | None = None


async def _get_dlq_producer() -> AIOKafkaProducer:
    global _dlq_producer
    if _dlq_producer is None:
        _dlq_producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await _dlq_producer.start()
    return _dlq_producer


async def _send_to_dlq(payload: dict, error: str):
    """Route an unprocessable event to the dead-letter queue."""
    try:
        producer = await _get_dlq_producer()
        dlq_event = {
            "original_payload": payload,
            "error": error[:1000],
            "timestamp": time.time(),
            "daemon": "payout_consumer",
        }
        await producer.send_and_wait(DLQ_TOPIC, dlq_event)
        log.warning(
            "DLQ ROUTED: %s — %s",
            payload.get("confirmation_code", "UNKNOWN"),
            error[:200],
        )
    except Exception as dlq_err:
        log.error(
            "DLQ PUBLISH FAILED: %s — %s (original error: %s)",
            payload.get("confirmation_code", "UNKNOWN"),
            dlq_err,
            error[:200],
        )


# ---------------------------------------------------------------------------
# Main event loop
# ---------------------------------------------------------------------------
async def consume_payout_events():
    """Main event loop: consume trust.payout.staged from Redpanda."""
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )

    log.info(
        "Starting Payout Consumer Daemon (hardened) on topic: %s "
        "(min_payout=$%.2f, manual_commit=True)",
        TOPIC, MINIMUM_PAYOUT_AMOUNT,
    )
    await consumer.start()

    try:
        async for msg in consumer:
            payload = msg.value
            conf_code = payload.get("confirmation_code", "UNKNOWN")
            log.info(
                "Payout event received: %s | owner_amount=$%s",
                conf_code,
                payload.get("owner_amount"),
            )

            try:
                status = await asyncio.to_thread(process_payout, payload)
                log.info("Payout result: %s → %s", conf_code, status)
            except Exception as e:
                log.error("Payout processing failed for %s: %s", conf_code, e)
                await _send_to_dlq(payload, str(e))

            try:
                await consumer.commit()
            except Exception as commit_err:
                log.error("Kafka offset commit failed: %s", commit_err)

    finally:
        await consumer.stop()
        if _dlq_producer:
            await _dlq_producer.stop()
        log.info("Payout Consumer Daemon stopped.")


if __name__ == "__main__":
    asyncio.run(consume_payout_events())
