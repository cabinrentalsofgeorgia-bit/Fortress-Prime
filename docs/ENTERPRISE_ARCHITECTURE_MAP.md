# Fortress-Prime Enterprise Architecture Map

Physical layer (Fleet) + Chinese Wall (logic) + script inventory + feeder target from Recon.

---

## 🏛️ Infrastructure (Physical Layer)

| Asset | Host / Path | Role |
|-------|-------------|------|
| **The Vault** | Synology NAS `/mnt/fortress_nas` | Cold storage. **EML:** 7,263 files (540 MB) in MailPlus Data Lake. PST: not found on fortress_nas in recon (optional: scan `/mnt/vol1_source` if mounted). |
| **Captain** | Spark-01 / 192.168.0.100 | Command & control, PostgreSQL (`fortress_db`), Feeder, Auditor. |
| **Wolfpack** | Spark-03 (.107), Spark-04 (.108) | Heavy compute (mining). Run `mining_rig_trader.py` in containers; pull raw text, extract signals, push to Captain. |

---

## 🧱 Chinese Wall (Logic Layer)

| Side | Data | Agents | Access | Output |
|------|------|--------|--------|--------|
| **A – Mining (raw)** | `public.email_archive` (raw lake) | Wolfpack (Spark-03/04) | Read-only raw emails | Propose signals only; **no trade execution** |
| **B – Sovereign (clean)** | `hedge_fund.market_signals` (alpha vault) | Sovereign (DeepSeek R1), Executioner | **No** raw email access; structured signals only | Audit → verify confidence → approve → execution layer |

---

## 📜 Script Inventory (Playbook)

| Script | Location | Role | Status |
|--------|----------|------|--------|
| **ingest_pst.py** | Captain | Feeder: open PSTs from NAS → `email_archive` | 🛑 Not in repo; **idle (needs target)**. |
| **ingest_eml.py** | Captain | Feeder: read EML from NAS Data Lake → `email_archive` | ⏸️ **Recon found target;** can be added to point at EML path below. |
| **deploy_wolfpack.sh** | Captain | Launcher: push code to workers, restart mining containers | ✅ Active |
| **mining_rig_trader.py** | Workers | Miner: read email → Qwen → write signal | ✅ Hunting (waiting for data) |
| **agent_sovereign_audit.py** | Captain | Auditor: DeepSeek R1 grades Wolfpack output | ⏸️ Standby (`src/sovereign_alpha_audit.py` exists) |
| **enterprise_audit.sh** | Captain | Watchdog: file counts vs DB | ✅ Available |
| **recon_nas_email.sh** | Captain | Recon: find PST/EML paths for Feeder | ✅ Available |

---

## 🚦 Feeder Target (from Recon)

**EML cold storage (ready now):**

```
/mnt/fortress_nas/Communications/System_MailPlus_Server/ENTERPRISE_DATA_LAKE/01_LANDING_ZONE/GMAIL_ARCHIVE
```

- **~7,263 .eml files**, **~540 MB**
- Point an **EML ingester** at this path to fill `email_archive`; then the Wolfpack can mine them.

**PST:** Recon did not find `.pst` under `/mnt/fortress_nas` in the sampled depth. If you have Outlook PSTs elsewhere (e.g. `/mnt/vol1_source` or another share), run:

```bash
find /mnt/vol1_source -name "*.pst" -type f 2>/dev/null | head -50
```

Then point `ingest_pst.py` at that directory when the script is added.

---

## Guest Communication Architecture (CROG Gateway vs Fortress Guest Platform)

Two systems handle guest communication. They are **not competitors** — they serve different lifecycle stages:

| System | Port | Purpose | Status |
|--------|------|---------|--------|
| **CROG Gateway** | 8001 | Strangler Fig migration proxy. Routes SMS between legacy (RueBaRue/Streamline) and AI. | Migration tool — use during legacy cutover |
| **Fortress Guest Platform** | 8100 | Full enterprise guest management: reservations, messaging, work orders, analytics, portals. | Production system |

**Nginx Routing (wolfpack_ai.conf):**
- `crog-ai.com/api/(messages|reservations)/` -> CROG Gateway (8001)
- `crog-ai.com/platform/` -> Fortress Guest Platform (8100)
- `crog-ai.com/` -> Command Center (9800)
- `192.168.0.100/v1/`, `/api/`, `/hydra/`, `/nim/` -> Ollama Cluster (11434)
- `192.168.0.100/` -> Command Center (9800)

**Consolidation Path:**
1. CROG Gateway's `TrafficRouter` validates AI responses in shadow mode
2. Once validated, Fortress Guest Platform handles all SMS directly
3. CROG Gateway is deprecated after full cutover
4. Nginx routes update to point `/api/(messages|reservations)/` to port 8100

---

## DB Schema Reference

### `finance` schema (public.finance_invoices)
AI-extracted invoice data from email archive. **WARNING**: Totals are inflated by AI extraction of dollar amounts from non-invoice emails. Always filter by vendor category.

| Column | Type | Notes |
|--------|------|-------|
| vendor | text | Vendor name (extracted) |
| amount | numeric(10,2) | Dollar amount |
| date | date | Invoice date |
| category | text | Vendor category |
| source_email_id | int | FK -> email_archive.id |

### `division_a` schema (Holding Company / Comptroller)

| Table | Purpose |
|-------|---------|
| `transactions` | Plaid-imported bank transactions. Columns: vendor, amount, category, confidence, roi_impact, method |
| `chart_of_accounts` | Double-entry COA. Types: asset, liability, equity, revenue, expense, cogs |
| `journal_entries` | Journal entries tied to transactions. Double-entry with debit/credit lines |
| `general_ledger` | Ledger postings derived from journal entries |
| `account_mappings` | Maps vendor categories to debit/credit accounts |
| `audit_log` | Change audit trail |
| `predictions` | AI-generated financial predictions |

### `hedge_fund` schema (Market Intelligence)

| Table | Purpose |
|-------|---------|
| `market_signals` | Extracted trading signals. Columns: ticker, signal_type, confidence, source_email_id |
| `watchlist` | Tracked tickers and assets |
| `active_strategies` | Currently running trading strategies |
| `extraction_log` | Signal extraction audit trail |

### `intelligence` schema (Knowledge Graph)

| Table | Purpose |
|-------|---------|
| `entities` | Named entities (people, companies, properties). Columns: entity_key, entity_type, display_name, metadata |
| `relationships` | Entity-to-entity links. Columns: from_entity_id, to_entity_id, relationship_type, confidence |
| `golden_reasoning` | Human-verified corrections to AI reasoning. Types: FACTUAL, CLASSIFICATION, MISSING_LINK, LOGIC_ERROR |
| `titan_traces` | TITAN mode session logs. Columns: session_type, defcon_mode, thinking_trace, response, latency_ms |

---

## ⚔️ Next move

1. **Run recon anytime:**  
   `bash tools/recon_nas_email.sh`

2. **Open the floodgates (EML):**  
   Implement or run an EML Feeder that:
   - Reads `.eml` from `GMAIL_ARCHIVE` above.
   - Parses each file (e.g. `email.parser` or `mail-parser`).
   - Inserts into `email_archive` (sender, subject, body, date; respect `sender_registry` if you want Traffic Control).
   - Marks new rows as `is_mined = FALSE` so the Wolfpack picks them up.

3. **PST later:**  
   When `ingest_pst.py` exists and a PST path is confirmed, point it at that path and run the Feeder there as well.
