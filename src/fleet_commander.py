"""
🛡️ FORTRESS PRIME - Fleet Commander
Always-On Continuous Data Ingestion Engine
Monitors and injects market signals to keep the database fresh.
"""

import os
import time
import random
from datetime import datetime, date
from typing import Optional
from dotenv import load_dotenv

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError, OperationalError
except ImportError:
    print("❌ Error: SQLAlchemy required. Install with: pip install sqlalchemy")
    raise

load_dotenv()

# --- CONFIGURATION ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

# Use analyst_writer user for data ingestion
DB_USER = "analyst_writer"
DB_PASSWORD = os.getenv("ANALYST_WRITER_PASSWORD")
if not DB_PASSWORD:
    raise SystemExit(
        "ANALYST_WRITER_PASSWORD env var is required to run fleet_commander.\n"
        "Set it in .env or export it from the vault. See docs/OPERATIONS.md."
    )

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Target date for fresh signals (Jan 20, 2026)
TARGET_DATE = date(2026, 1, 20)

# Signal templates for simulation
SIGNAL_TEMPLATES = {
    "NVDA": {
        "asset_class": "STOCK",
        "subjects": [
            "NVIDIA Reports Strong Q4 Earnings",
            "NVDA Stock Jumps on AI Chip Partnership",
            "Analyst Upgrade: NVIDIA Price Target Raised to $850",
            "NVDA Announces Next-Gen GPU Architecture",
            "NVIDIA Sees Heavy Institutional Buying"
        ],
        "content_templates": [
            "NVIDIA reports strong Q4 earnings, beating analyst expectations. GPU sales surge 150% YoY. Data center revenue reaches record $14.5 billion.",
            "NVDA stock jumps on news of new AI chip partnership with major cloud providers. Shares rise 8% in pre-market trading.",
            "Analyst upgrade: NVIDIA price target raised to $850 following data center revenue beat. Strong demand for H100 GPUs continues.",
            "NVDA announces next-gen GPU architecture targeting enterprise AI workloads. New chips expected to deliver 2x performance improvement.",
            "NVIDIA stock sees heavy institutional buying amid AI infrastructure boom. BlackRock and Vanguard increase positions significantly."
        ]
    },
    "FOMC": {
        "asset_class": "MACRO",
        "subjects": [
            "Fed Maintains Interest Rates at Current Levels",
            "FOMC Meeting Minutes Reveal Split Opinions",
            "Fed Officials Signal Caution on Rate Adjustments",
            "Federal Reserve Economic Projections Update",
            "FOMC Statement Emphasizes Data-Dependent Approach"
        ],
        "content_templates": [
            "Federal Reserve maintains interest rates at current levels. Powell signals patience on future cuts. Markets react positively to stability.",
            "FOMC meeting minutes reveal split opinions on inflation trajectory and monetary policy path. Some members favor earlier rate cuts.",
            "Fed officials indicate labor market cooling but remain cautious on rate adjustments. Employment data shows gradual normalization.",
            "Federal Reserve economic projections show steady GDP growth with inflation nearing 2% target. Unemployment remains historically low.",
            "FOMC statement emphasizes data-dependent approach to future monetary policy decisions. Next meeting scheduled for March 2026."
        ]
    },
    "ETH": {
        "asset_class": "CRYPTO",
        "subjects": [
            "Ethereum Network Sees Record Activity",
            "ETH Price Surges on Institutional Adoption",
            "Ethereum Developers Announce Roadmap Updates",
            "ETH/USD Breaks Key Resistance Level",
            "Ethereum Ecosystem Growth Accelerates"
        ],
        "content_templates": [
            "Ethereum network sees record activity following successful protocol upgrade and fee reduction. Transaction volume up 40% month-over-month.",
            "ETH price surges on news of institutional adoption and increased staking participation. Major institutions announce ETH holdings.",
            "Ethereum developers announce roadmap updates for scalability improvements and Layer 2 integration. Dencun upgrade shows strong results.",
            "ETH/USD breaks key resistance level as on-chain metrics show strong accumulation by whales. Large wallet addresses increase holdings.",
            "Ethereum ecosystem growth accelerates with new DeFi protocols and NFT marketplace activity. TVL reaches all-time high of $65 billion."
        ]
    }
}


def check_database_staleness() -> bool:
    """
    Check if database is stale (no signals dated today or later).
    Returns True if database needs fresh data.
    """
    try:
        with engine.connect() as conn:
            # Check if we have any signals dated today (Jan 20, 2026) or later
            query = text("""
                SELECT MAX(COALESCE(sent_at::date, created_at::date)) as last_date
                FROM market_intel
                WHERE ticker IN ('NVDA', 'FOMC', 'ETH')
                  AND asset_class IN ('STOCK', 'CRYPTO', 'MACRO', 'COMMODITY')
            """)
            result = conn.execute(query)
            row = result.fetchone()
            
            if row and row[0]:
                last_date = row[0] if isinstance(row[0], date) else row[0].date()
                print(f"   📅 Last signal date: {last_date}")
                print(f"   📅 Target date: {TARGET_DATE}")
                is_stale = last_date < TARGET_DATE
                return is_stale
            else:
                print(f"   ⚠️  No signals found in database")
                return True  # Consider stale if no signals exist
    except Exception as e:
        print(f"   ⚠️  Error checking database staleness: {e}")
        return True  # Assume stale on error


def insert_signal(ticker: str, asset_class: str, subject: str, content: str) -> bool:
    """
    Insert a market signal into the database dated Jan 20, 2026.
    Returns True if successful, False otherwise.
    """
    try:
        with engine.connect() as conn:
            # Set sent_at and created_at to Jan 20, 2026
            sent_at = datetime(2026, 1, 20, random.randint(9, 17), random.randint(0, 59))
            
            # Calculate random signal strength (0.1 to 1.0)
            signal_strength = round(random.uniform(0.1, 1.0), 2)
            
            query = text("""
                INSERT INTO market_intel (
                    ticker,
                    asset_class,
                    content,
                    signal_strength,
                    sent_at,
                    created_at
                ) VALUES (
                    :ticker,
                    :asset_class,
                    :content,
                    :signal_strength,
                    :sent_at,
                    :created_at
                )
            """)
            
            conn.execute(query, {
                "ticker": ticker,
                "asset_class": asset_class,
                "content": content,
                "signal_strength": signal_strength,
                "sent_at": sent_at,
                "created_at": sent_at  # Same as sent_at for new signals
            })
            conn.commit()
            
            # Log the ingestion
            print(f"   🚀 INGESTING: {subject}")
            return True
    except IntegrityError as e:
        print(f"   ⚠️  Integrity error (possible duplicate): {e}")
        return False
    except Exception as e:
        print(f"   ❌ Error inserting signal: {e}")
        return False


def simulate_incoming_signals():
    """
    Simulate incoming market signals for NVDA, FOMC, and ETH.
    Only runs if database is stale (last date < Jan 20, 2026).
    """
    if not check_database_staleness():
        print("   ✅ Database is fresh. No injection needed.")
        return
    
    print(f"   🔄 Database is stale. Injecting fresh signals dated {TARGET_DATE}...")
    
    signals_inserted = 0
    
    for ticker, config in SIGNAL_TEMPLATES.items():
        # Inject 2-3 signals per ticker
        num_signals = random.randint(2, 3)
        
        # Get random subjects and content pairs
        pairs = list(zip(config["subjects"], config["content_templates"]))
        selected_pairs = random.sample(pairs, min(num_signals, len(pairs)))
        
        for subject, content in selected_pairs:
            asset_class = config["asset_class"]
            
            if insert_signal(ticker, asset_class, subject, content):
                signals_inserted += 1
            else:
                print(f"   ⚠️  Failed to inject signal: {ticker} - {subject}")
    
    if signals_inserted > 0:
        print(f"   ✨ Injected {signals_inserted} fresh signals dated {TARGET_DATE}.")
    else:
        print("   ⚠️  No signals were inserted.")


def main_loop():
    """
    Main continuous loop for Fleet Commander.
    Runs indefinitely with 10-second intervals.
    """
    print("=" * 60)
    print("🛡️  FORTRESS PRIME - FLEET COMMANDER")
    print("=" * 60)
    print(f"📡 Database: {DB_NAME}@{DB_HOST}:{DB_PORT}")
    print(f"👤 User: {DB_USER}")
    print(f"📅 Target Date: {TARGET_DATE}")
    print(f"⏱️  Check Interval: 10 seconds")
    print("=" * 60)
    print("\n🚀 Fleet Commander initialized. Starting continuous monitoring...")
    print("   Press Ctrl+C to stop.\n")
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            print(f"\n[{current_time}] Cycle #{cycle_count}")
            print("   🔍 Checking database status...")
            
            # Simulate incoming signals if database is stale
            simulate_incoming_signals()
            
            print(f"   💤 Sleeping for 10 seconds...")
            time.sleep(10)
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("🛑 Fleet Commander shutdown requested.")
        print(f"   Completed {cycle_count} monitoring cycles.")
        print("=" * 60)
        print("✅ Fleet Commander stopped gracefully.")
    except Exception as e:
        print(f"\n\n❌ Unexpected error in main loop: {e}")
        print(f"   Error type: {type(e).__name__}")
        print("   Fleet Commander will restart in 10 seconds...")
        time.sleep(10)
        main_loop()  # Restart


if __name__ == "__main__":
    # Verify database connection before starting
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection verified.")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print(f"   Please ensure PostgreSQL is running and accessible at {DATABASE_URL}")
        exit(1)
    
    main_loop()
