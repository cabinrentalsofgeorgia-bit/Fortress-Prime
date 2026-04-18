# 🛡️ FORTRESS PRIME - Codebase Overview

**Last Updated:** January 2026  
**Status:** Active Development  
**Owner:** Gary Knight / Cabin Rentals of Georgia

---

## 📋 Table of Contents

1. [Project Architecture](#project-architecture)
2. [Directory Structure](#directory-structure)
3. [Core Components](#core-components)
4. [Services & Agents](#services--agents)
5. [Data Pipeline](#data-pipeline)
6. [Infrastructure](#infrastructure)
7. [Key Scripts & Commands](#key-scripts--commands)

---

## 🏗️ Project Architecture

### Tier Architecture (Hybrid Sovereign Cloud)
- **Tier 1 (Cloud):** Next.js 14 (Vercel), Supabase (PostgreSQL), Cloudflare R2
- **Tier 2 (HQ Edge):** NVIDIA DGX Spark (AI/Docker), Synology DS1825+ (Storage/Backup)
- **Tier 3 (Vault):** Synology DS923+ (Off-site Disaster Recovery)
- **Connectivity:** Tailscale Mesh VPN

### Layer Architecture
1. **Layer 1: The Data Lake (Ingestion)** ✅
   - 68,000+ Emails indexed in PostgreSQL
   - Sectors: Construction, Real Estate, Market Intel, Financials

2. **Layer 2: The Vault (Physical Assets)** ✅
   - Location: `/mnt/fortress_data/invoices`
   - 26 PDF Invoices extracted

3. **Layer 3: The Intelligence (Analysis)** ✅
   - Financials: $27k spend identified
   - Real Estate: Territory mapped
   - Market Signals: "Operation Retina" active

---

## 📂 Directory Structure

```
fortress-prime/
├── app/                          # Streamlit application
│   ├── modules/
│   │   └── database.py          # Database connection module
│   └── views/
│       └── data_explorer.py     # Data exploration views
├── src/                          # Core services and scripts
│   ├── pulse_agent.py           # Hardware telemetry monitor (GPU/CPU)
│   ├── telemetry_agent.py       # System telemetry agent
│   ├── watcher_service.py       # File watcher for market input
│   ├── init_db.py               # Database initialization
│   ├── dashboard*.py            # Dashboard variations (v2, v3)
│   ├── analyze_spend.py         # Financial audit tool
│   ├── extract_trade_signals*.py # Market signal extraction
│   ├── map_real_estate.py       # Real estate territory mapper
│   ├── indexer_service.py       # Document indexing service
│   ├── ingest_*.py              # Data ingestion scripts
│   └── find_intel.py            # Intelligence search tool
├── docs/                         # Documentation
│   └── README.md                # Docs directory info
├── logs/                         # Application logs
├── uploads/                      # Uploaded files
├── config/                       # Configuration files
├── backup-*/                     # Backup archives
├── app.py                        # Main Streamlit application
├── docker-compose.local.yml      # Legacy local dev compose, never production
├── Dockerfile.pulse-agent        # Pulse Agent container image
├── requirements.txt              # Python dependencies
├── PROJECT_MANIFEST.md           # Project status and objectives
└── COMMAND_CODES.md              # Quick reference commands
```

---

## 🔧 Core Components

### 1. Database Layer
- **Database:** PostgreSQL (`fortress_db`)
- **User:** `miner_bot`
- **Key Tables:**
  - `market_intel` - Email intelligence with vector embeddings
  - `email_archive` - Full text email archive with GIN index
  - `node_telemetry` - Hardware telemetry (GPU temp, load, VRAM)
  - `system_telemetry` - System metrics (CPU, RAM, disk)

### 2. AI/Embedding Layer
- **Embedding Model:** `nomic-embed-text` (via Ollama)
- **Chat Model:** `llama3.2` / `mistral` (via Ollama)
- **Worker IP:** `192.168.0.104:11434`
- **Vector Search:** PostgreSQL pgvector extension

### 3. Frontend Application
- **Framework:** Streamlit
- **Port:** 8503 (Dashboard)
- **Features:**
  - Intelligence search with vector similarity
  - Financial audit visualization
  - Real estate mapping
  - RAG chatbot interface

---

## 🚀 Services & Agents

### Pulse Agent (`src/pulse_agent.py`)
**Purpose:** Hardware telemetry monitoring for Tier 2 HQ Edge (NVIDIA DGX)
- Monitors GPU temperature, utilization, and VRAM usage
- Falls back to CPU monitoring if GPU unavailable
- Updates database every 5 seconds (configurable)
- **Container:** `fortress-pulse-agent` (Docker)

### Telemetry Agent (`src/telemetry_agent.py`)
**Purpose:** System-level metrics collection
- Monitors CPU, RAM, and disk usage
- Persistent database connection
- Records to `system_telemetry` table

### Watcher Service (`src/watcher_service.py`)
**Purpose:** File system monitoring for market intelligence
- Watches `/mnt/fortress_data/market_input`
- Processes PDFs and text files automatically
- Extracts market signals (BUY/SELL indicators)
- Vectorizes and stores in `market_intel` table

### Indexer Service (`src/indexer_service.py`)
**Purpose:** Document indexing with vector embeddings
- Processes folders of documents (PDFs, text files)
- Extracts text and creates embeddings
- Categorizes by folder structure

---

## 📊 Data Pipeline

### Email Ingestion Flow

1. **Source Extraction**
   - `email_miner.py` - Processes .mbox files
   - `email_miner_maildir.py` - Processes Maildir format
   - `miner_cpanel.py` - cPanel mail directories
   - `miner_work.py` - Specific .Work folder

2. **Content Processing**
   - HTML cleaning and text extraction
   - Chunking (1000-4000 character chunks)
   - Metadata extraction (sender, subject, date)

3. **Vectorization**
   - Embeddings via Ollama API (`nomic-embed-text`)
   - Stored in PostgreSQL with pgvector

4. **Storage**
   - `market_intel` table (with embeddings)
   - `email_archive` table (full text with GIN index)

### Document Ingestion Flow

1. **File Detection**
   - Watcher service monitors `/mnt/fortress_data/market_input`
   - Processes new files automatically

2. **Text Extraction**
   - PDF: `pypdf` library
   - Text/HTML: Direct reading

3. **Market Signal Extraction**
   - Pattern matching for BUY/SELL indicators
   - Signal strength and direction analysis

4. **Vectorization & Storage**
   - Chunked embedding creation
   - Insertion into `market_intel` with signal metadata

---

## 🐳 Infrastructure

### Legacy Local Compose (`docker-compose.local.yml`)
**Dev-only configuration for non-production machines:**

1. **Legacy PostgreSQL Container**
   - Image: `postgres:15-alpine`
   - Container: `fortress-postgres`
   - Data Persistence: `/mnt/fortress_data/postgres` (Synology DS1825+)
   - Port: 5432
   - Health checks enabled

2. **Pulse Agent Container**
   - Built from: `Dockerfile.pulse-agent`
   - Container: `fortress-pulse-agent`
   - GPU access via NVIDIA runtime
   - System hardware monitoring enabled

### Network
- **Network:** `fortress-network` (bridge)
- **Internal Communication:** Container-to-container via service names

---

## ⌨️ Key Scripts & Commands

### Service Management
```bash
# Dashboard (Streamlit)
sudo systemctl restart fortress-dashboard
# URL: http://192.168.0.100:8503

# Docker Services (Tier 2 HQ Edge)
docker-compose up -d
docker-compose logs -f pulse-agent
docker-compose down
```

### Data Processing
```bash
# Financial Audit
python ~/fortress-prime/src/analyze_spend.py

# Market Signals (Operation Retina)
python ~/fortress-prime/src/extract_trade_signals_v2.py

# Real Estate Mapping
python ~/fortress-prime/src/map_real_estate.py

# Email Ingestion
python ~/fortress-prime/src/ingest_market.py
python ~/fortress-prime/src/ingest_deep_archive.py
```

### Intelligence Search
```bash
# Titan Brain (RAG Chatbot)
python titan_brain.py

# Find Intel
python ~/fortress-prime/src/find_intel.py
```

---

## 🔐 Configuration

### Database Credentials
- **Host:** `localhost` (local) / `postgres` (Docker network)
- **Database:** `fortress_db`
- **User:** `miner_bot`
- **Password:** `<see MINER_BOT_DB_PASSWORD env var>` (Tier 2) / `secure_password` (some configs)

### Storage Mounts
- **PostgreSQL Data:** `/mnt/fortress_data/postgres`
- **Market Input:** `/mnt/fortress_data/market_input`
- **Invoices:** `/mnt/fortress_data/invoices`

### AI Configuration
- **Ollama API:** `http://192.168.0.104:11434/api`
- **Embed Model:** `nomic-embed-text`
- **Chat Model:** `llama3.2` / `mistral`

---

## 📝 Development Notes

### Recent Additions
- ✅ Docker Compose setup for Tier 2 HQ Edge
- ✅ Pulse Agent containerization
- ✅ PostgreSQL persistent storage to Synology DS1825+
- ✅ Environment variable configuration for Pulse Agent

### Pending Objectives
- [ ] Daily Briefing (Combine Maestro + Epoch Times)
- [ ] Deep Search UI (Search by Contractor)
- [ ] SOW Milestone 1: Infrastructure & The "Vault"
- [ ] SOW Milestone 2: Data Sync Engine
- [ ] SOW Milestone 3: Frontend & Legal Protection

---

## 🔗 Related Documentation

- `PROJECT_MANIFEST.md` - Project status and objectives
- `COMMAND_CODES.md` - Quick command reference
- `docs/README.md` - Documentation directory
- `docs/statement-of-work.pdf` - Full SOW document (when added)

---

**Note:** This is a living document. Update as the codebase evolves.
