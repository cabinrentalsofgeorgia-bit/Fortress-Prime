# Fortress One: The Unfinished Business Roadmap

Strategic execution order for the four gaps between current state and the Constitution.

---

## 1. The Sovereign Brain (Spark-02 / Spark-04) — **PRIMARY**

**Gap:** The Trader Rig is filling the Alpha Vault with raw signals; nobody is reasoning over them yet.

**Done:**
- **Sovereign Alpha Audit** (`src/sovereign_alpha_audit.py`) — R1 reads a digest of `hedge_fund.market_signals` and produces: SOURCES TO TRUST, SOURCES TO DOWNWEIGHT, RECOMMENDED ACTIONS, DATA QUALITY NOTE. Persists to `hedge_fund.sovereign_audit` and `.../logs/sovereign_alpha_audit_latest.txt`.
- **R1 launch script** — `deepseek_max_launch.sh` brings up DeepSeek-R1-Distill-Llama-70B via NVIDIA NIM on Captain (Spark-02). Optional: run the same container on a dedicated Spark-04 host if you add a fourth node.

**Run the Brain (choose one):**

```bash
# Option A: Use existing Captain (Ollama or NIM already running)
python3 -m src.sovereign_alpha_audit              # Full audit
python3 -m src.sovereign_alpha_audit --dry-run    # Digest only, no R1 call

# Option B: Start the 70B NIM container on Captain (if not already up)
./deepseek_max_launch.sh
# Then run the audit (script will use NIM or Ollama automatically).
```

**Cron (after Trader backfill):**  
`0 7 * * 1-5` — run Sovereign Alpha Audit at 7 AM weekdays.

**If you add Spark-04:**  
Run the same NIM container on the new host, set `BRAIN_NIM_URL` or `CAPTAIN_IP` to that host, and run the audit from Captain so R1 lives on the dedicated node.

---

## 2. The Flagship Interface (CROG API) — **SECONDARY**

**Gap:** The Constitution requires an API backend for the external Next.js developer. Data exists (ops_properties, QuantRevenue, calendar); the “door” was missing.

**Done:**
- **CROG API stubs** — Gateway mounts `/v1/crog` with:
  - `GET /v1/crog/properties/{property_id}/pricing` — property info + pricing hint (delegates to existing ops + quant where applicable).
  - `GET /v1/crog/calendar/availability` — availability placeholder for the frontend to integrate with Streamline/groundskeeper.

**Next:**  
Generate API keys (gateway auth) and hand off the OpenAPI spec (`/docs` at api.crog-ai.com) to the cloud developer.

---

## 3. The Creative Engine (Verses in Bloom) — **TERTIARY**

**Gap:** Division “Verses” (high-margin digital retail, Etsy) is concept-only. Spark-03 (Ocular) and the “Art Director” agent are not deployed.

**Left:**
- Deploy Llama-3.2-Vision (or equivalent) on Spark-03.
- Implement the Art Director agent: scan trends, auto-generate blueprints for the Etsy store.

**Priority:** After Sovereign and CROG API are stable.

---

## 4. The Shield (Legal & Finance) — **UNDEPLOYED**

**Gap:** CFO Agent and “Matlock” (Legal) are in the manifest but not running; no automated challenger for QuickBooks vs bank/email receipts.

**Left:**
- Bank connection: read-only bank feeds (e.g. Plaid already in repo).
- Challenger script: compare every bank transaction to `email_archive` receipts and flag mismatches for human review.

**Priority:** After core revenue (CROG) and Alpha (Sovereign) are in place.

---

## Execution order (summary)

| Order | Target              | Why |
|-------|---------------------|-----|
| 1     | **Sovereign (Alpha Audit)** | Vault is filling; R1 must turn data into Alpha before Monday. |
| 2     | **CROG API**        | Unblocks the Next.js developer and public revenue face. |
| 3     | **Ocular / Verses** | New revenue stream; less critical than core. |
| 4     | **Shield (CFO/Legal)** | Compliance and audit; deploy once core is stable. |

---

## Quick reference

- **Sovereign Alpha Audit:** `python3 -m src.sovereign_alpha_audit`  
- **R1 container (Captain):** `./deepseek_max_launch.sh`  
- **CROG API base:** `https://api.crog-ai.com/v1/crog` (see gateway `/docs`)  
- **Hedge Fund dashboard:** Grafana → Fortress Prime → Hedge Fund Command Center  
