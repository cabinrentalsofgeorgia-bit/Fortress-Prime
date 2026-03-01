# Continuous Liquidity — Operational Runbook

## Stripe Connect Webhook Registration

The payout lifecycle tracking requires a Stripe Connect webhook endpoint.
Register it in the Stripe Dashboard:

### Steps

1. Go to **Stripe Dashboard** > **Developers** > **Webhooks**
2. Click **Add endpoint**
3. Set the endpoint URL:
   ```
   https://crog-ai.com/api/webhooks/stripe-connect
   ```
   (Cloudflare Tunnel -> Nginx -> FGP Backend port 8100)

4. Under **Listen to**, select **Events on Connected accounts**
5. Select these events:
   - `transfer.paid`
   - `transfer.failed`
   - `payout.paid`
   - `payout.failed`
   - `account.updated`

6. Click **Add endpoint**
7. Copy the **Signing secret** (starts with `whsec_`)
8. Add to `fortress-guest-platform/.env`:
   ```
   STRIPE_CONNECT_WEBHOOK_SECRET=whsec_XXXXXXXXXXXXXXXX
   ```
9. Restart the FGP backend for the new secret to take effect

### Verification

```bash
# Confirm the endpoint responds (should return 400 — no signature)
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://crog-ai.com/api/webhooks/stripe-connect

# Should return 400 (expected — no valid Stripe signature)
```

In Stripe Dashboard > Webhooks, the endpoint should show a green "Active" status
after the first successful event delivery.

## Database Migration

Before first use, apply the hardening migration:

```bash
psql -h localhost -U fgp_app -d fortress_guest \
  -f database/migrations/016_payout_hardening.sql
```

This adds:
- `held` and `settled` statuses to `payout_ledger`
- `retry_count`, `batch_id`, `idempotency_key` columns
- `stripe_connect_events` audit table

## Payout Consumer Daemon

### Start (Docker)

```bash
docker compose up -d payout-consumer
docker compose logs -f payout-consumer
```

### Start (Manual)

```bash
nohup python3 src/payout_consumer_daemon.py > /tmp/payout_consumer.log 2>&1 &
```

### Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `KAFKA_BROKER_URL` | `192.168.0.100:19092` | Redpanda broker |
| `STRIPE_SECRET_KEY` | (required) | Stripe platform secret key |
| `MINIMUM_PAYOUT_AMOUNT` | `25.00` | Threshold below which payouts accumulate |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `FGP_DB_USER` | `fgp_app` | Database user |
| `FGP_DB_PASS` | (required) | Database password |

### Circuit Breaker

- Trips after 3 consecutive Stripe API failures
- 5-minute cooldown before retrying
- During cooldown, new payouts are held (not lost)
- Resets automatically on first successful Transfer after cooldown

### Payout Status Lifecycle

```
trust.payout.staged event arrives
  |
  +--> owner_amount < $25?  --> status: 'held'
  |      (accumulates until batch exceeds threshold)
  |
  +--> No Stripe Connect account? --> status: 'manual'
  |      (end-of-month ACH batch)
  |
  +--> stripe.Transfer.create()
         |
         +--> success --> status: 'processing'
         |     |
         |     +--> Webhook: transfer.paid   --> status: 'completed'
         |     |     (journal entry written)
         |     |
         |     +--> Webhook: payout.paid     --> status: 'settled'
         |           (funds in owner's bank)
         |
         +--> failure --> status: 'failed'
               (reconciler retries next day, up to 5 attempts)
```

## DLQ Operations

### Inspect dead-lettered events

```bash
python tools/replay_payout_dlq.py --inspect
```

### Replay all DLQ events

```bash
python tools/replay_payout_dlq.py --replay
```

### Replay a specific event

```bash
python tools/replay_payout_dlq.py --replay --code CROG-12345
```

## Daily Reconciliation

Runs automatically via cron at 4:00 AM ET. Manual run:

```bash
# Dry run (report only)
python tools/reconcile_payouts.py --dry-run

# Live reconciliation
python tools/reconcile_payouts.py
```

Reconciliation handles:
- Stale `processing` entries older than 48 hours (checks Stripe Transfer status)
- Failed entries eligible for retry (retry_count < 5, active Stripe account)
- Summary report of all payout statuses and amounts

## Event Bus Topics

| Topic | Partitions | Purpose |
|-------|------------|---------|
| `trust.payout.staged` | 3 | Payout events from Revenue Consumer |
| `trust.payout.dlq` | 1 | Dead-lettered events for manual review |

Create topics (idempotent):

```bash
python tools/init_event_bus.py
```
