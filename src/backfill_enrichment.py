import os
import pandas as pd
from sqlalchemy import create_engine, text
import re

# --- CONFIGURATION ---
DB_URL = os.getenv("DATABASE_URL", "")
if not DB_URL:
    raise RuntimeError("DATABASE_URL env var required")
engine = create_engine(DB_URL)

def get_stats():
    with engine.connect() as conn:
        market_exists = conn.execute(text("SELECT to_regclass('public.market_intel')")).scalar()
        market_pending = 0
        if market_exists:
            market_pending = conn.execute(text("SELECT COUNT(*) FROM market_intel WHERE ticker IS NULL")).scalar()
    return market_pending

def mock_llm_enrich(content, type="market"):
    if not content: return None, None
    content = str(content).upper()
    
    if type == "market":
        # 1. MACRO / FED / ECON (Expanded!)
        if any(x in content for x in ["FEDERAL OPEN MARKET", "FEDERAL RESERVE", "FOMC", "FED OFFICIALS"]):
            return "FOMC", "MACRO"
        if any(x in content for x in ["TREASURY", "YIELD", "BOND MARKETS", "10-YEAR"]):
            return "US_TREASURY", "MACRO"
        if any(x in content for x in ["INFLATION", "CPI", "PCE", "POLICY RATE", "INTEREST RATE"]):
            return "ECON_DATA", "MACRO"
        if any(x in content for x in ["UNEMPLOYMENT", "JOB OPENINGS", "LABOR MARKET", "PAYROLL"]):
            return "LABOR", "MACRO"

        # 2. CRYPTO
        if any(x in content for x in ["BTC", "BITCOIN"]): return "BTC", "CRYPTO"
        if any(x in content for x in ["ETH", "ETHEREUM"]): return "ETH", "CRYPTO"

        # 3. STOCKS
        if any(x in content for x in ["NVDA", "NVIDIA"]): return "NVDA", "STOCK"
        if any(x in content for x in ["TSLA", "TESLA"]): return "TSLA", "STOCK"
        if any(x in content for x in ["AAPL", "APPLE"]): return "AAPL", "STOCK"
        if any(x in content for x in ["MSFT", "MICROSOFT"]): return "MSFT", "STOCK"
        
        return "UNKNOWN", "OTHER"

    return None, None

def run_backfill(dry_run=False):
    print(f"🛡️  FORTRESS PRIME - Backfill Agent {'(DRY RUN)' if dry_run else ''}")
    print("="*60)
    
    mp = get_stats()
    print(f"📊 Pending: {mp} Market signals\n")

    if mp > 0:
        print("📈 Processing Market Intel...")
        with engine.connect() as conn:
            # INCREASED LIMIT FOR LIVE RUN
            limit = 20 if dry_run else 10000 
            rows = pd.read_sql(f"SELECT id, content FROM market_intel WHERE ticker IS NULL LIMIT {limit}", conn)
            
            count = 0
            for _, row in rows.iterrows():
                ticker, asset = mock_llm_enrich(row['content'], "market")
                
                # Only print updates or dry run info
                if dry_run or count % 100 == 0:
                     print(f"   [ID {row['id']}] -> {ticker} ({asset})")
                
                if not dry_run and ticker != "UNKNOWN":
                    conn.execute(text("UPDATE market_intel SET ticker=:t, asset_class=:a WHERE id=:id"), 
                               {"t": ticker, "a": asset, "id": row['id']})
                    conn.commit()
                    count += 1
            
            if not dry_run:
                print(f"\n✅ Automatically enriched {count} records.")

if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    run_backfill(dry_run=dry_run)
