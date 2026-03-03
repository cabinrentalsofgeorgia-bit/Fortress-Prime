# Enterprise Audit Report — Physical vs Digital vs Wolfpack

**Run date:** 2026-02-12  
**Purpose:** Reconcile NAS (physical) with `email_archive` (digital) and miner/Trader behavior.

---

## Step 1: Physical Audit (NAS)

| Check | Result |
|-------|--------|
| **NAS root** | `/mnt/fortress_nas` |
| **PST files** | **0** (no `.pst` in top 5 levels) |
| **Total NAS size** | Not run (avoid long `du` on full volume) |

**Interpretation:** This Fortress setup does **not** use PST files on NAS for email. Email is ingested via **IMAP** (e.g. `ingest_taylor_imap.py`, `ingest_market_imap.py`) into `email_archive`. So “physical” email volume is determined by what’s in the mailboxes the feeders pull from, not by a NAS email folder. If you have a separate NAS path for PSTs (e.g. `/mnt/nas/emails`), run locally:

```bash
du -sh /mnt/nas/emails
find /mnt/nas/emails -name "*.pst" | wc -l
```

---

## Step 2: Digital Audit (Database)

| Metric | Value |
|--------|--------|
| **total_ingested** | **55,579** |
| **marked_mined** | **55,562** |
| **actual_backlog** | **17** |

**Interpretation:** The database considers the main mining job **effectively complete**: only 17 rows with `is_mined = FALSE`. So you are **not** in “tip of the iceberg” for the current ingested set — the 55k emails are what the system has, and almost all are marked mined.

**Division B (Hedge Fund) separately:**

| Table | Count |
|-------|--------|
| `hedge_fund.extraction_log` | 1,602 (emails processed by Trader) |
| `hedge_fund.market_signals` | 1,112 (signals extracted) |

The Trader rig is processing Division B emails (remine) and has written 1,602 extraction logs and 1,112 signals. Remaining Division B emails not yet in `extraction_log` are the Trader’s backlog, not the general `email_archive` backlog.

---

## Step 3: Wolfpack / Miner Logs

| Check | Result |
|-------|--------|
| **Log** | `trader_rig_remine.log` |
| **“Skipping”** | 0 (no skip pattern in that log) |
| **“Extracted” / “signal(s)”** | Counts present (Trader is extracting) |
| **“ERROR”** | Many (e.g. 1435) — **Worker exception: 'error'** |

**Interpretation:** The Trader is **not** “skipping” work. It is calling the model and writing signals. The high ERROR count is from a **stats key bug**: the worker returns `result["errors"]` but the main thread once expected `result["error"]`, so it raised when updating stats. That is a logging/stats bug, not “crashing and marking done.” Fix: ensure all code paths use `result["errors"]` (and that the worker sets it). After that, re-run the audit; ERROR count from this cause should drop.

---

## Verdict

| Scenario | Your situation |
|----------|----------------|
| **Tip of the iceberg** (NAS huge, DB small) | **No** — You have no PST-based NAS email path in use; 55k is the current ingested set from IMAP. |
| **Phantom completion** (flags set without real mining) | **No** — Backlog is 17; the rest were mined by the main rig. Division B is being re-mined by the Trader (1,602 so far). |
| **Wolfpack skipping** | **No** — Logs show extraction and signals; errors are from the stats key bug, not “skip and mark done.” |

**Recommended actions:**

1. **Re-run audit anytime:**  
   `bash tools/enterprise_audit.sh`  
   (Uses `timeout 60` for NAS `du` so it doesn’t hang.)

2. **If you add PST ingestion later:**  
   Run Step 1 against the PST mount (e.g. `/mnt/nas/emails`). If that volume is large and `email_archive` stays ~55k, then the PST feeder is the bottleneck.

3. **Fix Trader stats bug:**  
   Ensure worker and main thread both use `result["errors"]` so “Worker exception: 'error'” disappears and logs reflect real failures only.

4. **Optional: reset flags for re-mine**  
   Only if you want to re-run mining on already-mined emails (e.g. after prompt changes):  
   `UPDATE email_archive SET is_mined = FALSE WHERE ...` (with a safe WHERE clause). Not required for current state.
