# M3 — Spark-1 Mirror Activation Runbook

**Phase:** M3 Trilateral Write (Spark-1 Catchup)  
**Target:** Deploy M3 code with flag OFF, then activate dual-write to spark-1 fortress_prod  
**Prerequisites:** M3 PR merged, fortress-arq-worker has M3 code deployed  
**Risk Level:** LOW (additive only, existing bilateral pattern unchanged)  

---

## Overview

M3 introduces additive trilateral writes:
- **Existing:** spark-2 fortress_db ↔ spark-2 fortress_prod (bilateral, unchanged)
- **NEW:** spark-2 fortress_db ↔ spark-2 fortress_prod ↔ spark-1 fortress_prod (trilateral)

Spark-1 writes are fire-and-forget: failures log warnings but do not block operations. Reads still come from spark-2 fortress_prod during the migration window.

---

## Activation Steps

### Step 1: Verify Spark-1 Postgres Availability

```bash
# From spark-2, test connectivity to spark-1 Postgres
psql -h spark-node-1 -U fortress_admin -l

# Expected: Connection succeeds, lists available databases
# If connection fails: verify spark-1 is online, check firewall rules
```

### Step 2: Create fortress_prod Database on Spark-1

```bash
# Connect as fortress_admin on spark-1
psql -h spark-node-1 -U fortress_admin postgres

# Create database (if not exists)
CREATE DATABASE fortress_prod;

# Create application role (if not exists)  
CREATE USER fortress_app WITH PASSWORD 'SECURE_PASSWORD_HERE';
GRANT CONNECT ON DATABASE fortress_prod TO fortress_app;
GRANT USAGE ON SCHEMA public TO fortress_app;
GRANT USAGE ON SCHEMA legal TO fortress_app;
GRANT CREATE ON SCHEMA public TO fortress_app;

\q
```

### Step 3: Run Schema Migration on Spark-1

```bash
# From spark-2, migrate spark-1 to current schema state
cd ~/Fortress-Prime/fortress-guest-platform/backend

# Set temporary migration URL
export TEMP_SPARK1_URL="postgresql://fortress_admin:SECURE_PASSWORD@spark-node-1:5432/fortress_prod"

# Run migrations to bring spark-1 schema current with spark-2
alembic -c alembic.ini -x dburl=$TEMP_SPARK1_URL upgrade head

# Verify schema migration succeeded
unset TEMP_SPARK1_URL
```

### Step 4: Set Spark-1 Connection Environment

```bash
# Add to fortress-arq-worker environment
sudo systemctl edit fortress-arq-worker.service

# Add these lines under [Service]:
# Environment="SPARK1_DATABASE_URL=postgresql+asyncpg://fortress_app:SECURE_PASSWORD@spark-node-1:5432/fortress_prod"

# Apply changes
sudo systemctl daemon-reload
```

### Step 5: Restart Worker with Spark-1 Connection

```bash
# Restart to pick up SPARK1_DATABASE_URL
sudo systemctl restart fortress-arq-worker.service

# Verify startup with no spark-1 connection errors
sudo journalctl -u fortress-arq-worker.service -f --since "2 minutes ago"

# Look for: successful startup without "SPARK1_DATABASE_URL not set" errors
# If errors: check connection string, spark-1 availability, credentials
```

### Step 6: Activation Gate — Enable M3 Mirror

```bash
# Add the activation flag
sudo systemctl edit fortress-arq-worker.service

# Add under [Service]:
# Environment="LEGAL_M3_SPARK1_MIRROR_ENABLED=true"

# Apply and restart
sudo systemctl daemon-reload
sudo systemctl restart fortress-arq-worker.service
```

### Step 7: Monitor Activation

```bash
# Monitor for spark1_mirror_write_failed warnings (should be zero)
sudo journalctl -u fortress-arq-worker.service -f | grep -i spark1

# Expected: no "spark1_mirror_write_failed" log lines
# If warnings appear: check spark-1 connectivity, schema parity, constraints

# Monitor general worker health
sudo journalctl -u fortress-arq-worker.service --since "5 minutes ago" | grep ERROR

# Expected: no new ERRORs related to legal pipeline or database writes
```

---

## Verification Queries

### Verify Bilateral→Trilateral Transition

```sql
-- On spark-2 fortress_db (canonical)
SELECT COUNT(*) FROM email_archive WHERE created_at > NOW() - INTERVAL '10 minutes';
SELECT COUNT(*) FROM legal.event_log WHERE emitted_at > NOW() - INTERVAL '10 minutes';

-- On spark-2 fortress_prod (existing mirror)  
SELECT COUNT(*) FROM email_archive WHERE created_at > NOW() - INTERVAL '10 minutes';
SELECT COUNT(*) FROM legal.event_log WHERE emitted_at > NOW() - INTERVAL '10 minutes';

-- On spark-1 fortress_prod (NEW catchup mirror)
SELECT COUNT(*) FROM email_archive WHERE created_at > NOW() - INTERVAL '10 minutes';
SELECT COUNT(*) FROM legal.event_log WHERE emitted_at > NOW() - INTERVAL '10 minutes';

-- All three counts should be approximately equal (within minutes of each other)
```

### Check for Mirror Drift

```bash
# Look for trilateral write failures
sudo journalctl -u fortress-arq-worker.service --since "1 hour ago" | grep "spark1_mirror_write_failed" | wc -l

# Expected: 0 (zero failures in steady state)
# If >0: investigate spark-1 connectivity, capacity, or schema issues
```

---

## Rollback Procedure

If activation causes issues, rollback is simple and safe:

```bash
# Step 1: Disable M3 flag (reverts to bilateral writes)
sudo systemctl edit fortress-arq-worker.service

# Remove or comment out:
# Environment="LEGAL_M3_SPARK1_MIRROR_ENABLED=true"

# Step 2: Apply rollback
sudo systemctl daemon-reload
sudo systemctl restart fortress-arq-worker.service

# Step 3: Verify bilateral operation restored
sudo journalctl -u fortress-arq-worker.service --since "2 minutes ago" | grep -i spark1
# Expected: no spark1-related log lines (back to bilateral mode)
```

**Important:** Rollback does NOT affect existing bilateral writes (spark-2 ↔ spark-2). Only the spark-1 catchup writes are disabled.

---

## Next Phase

After M3 activation is stable (24h+ runtime):
- **M4:** Parity verification tooling between spark-2 and spark-1  
- **M5:** Read cutover (switch reads from spark-2 fortress_prod to spark-1 fortress_prod)
- **M6:** Write retirement (remove spark-2 fortress_prod writes, keep spark-1 only)

**Do not proceed to M4 until M3 trilateral writes are confirmed stable.**

---

## Troubleshooting

### "SPARK1_DATABASE_URL not set" Error
- **Cause:** Environment variable missing or worker not restarted
- **Fix:** Verify Step 4-5, ensure `systemctl daemon-reload` + `systemctl restart`

### "spark1_mirror_write_failed" Warnings  
- **Cause:** Spark-1 connectivity, schema mismatch, or constraint violations
- **Fix:** Check spark-1 status, verify schema migration (Step 3), check network

### High spark1_mirror_write_failed Rate
- **Cause:** Spark-1 overloaded, network issues, or schema drift
- **Fix:** Consider rolling back, investigate spark-1 capacity and connectivity

### Worker Startup Failures After M3
- **Cause:** Invalid connection string or spark-1 unreachable during startup
- **Fix:** Verify Step 1-2, test connection manually, check credentials