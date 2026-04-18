"""
🛡️ FORTRESS PRIME - Gold Database Upgrade Script
Adds structured tables for finance_invoices and market_signals.
Upgrades email_archive with is_mined tracking column.
"""

import psycopg2
import os
from dotenv import load_dotenv

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


# Load environment variables
load_dotenv()

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASS", _MINER_BOT_PASSWORD)

def get_db_connection():
    """Establish database connection."""
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

def upgrade_database():
    """Execute database schema upgrades."""
    print("🛡️  FORTRESS PRIME - Gold Database Upgrade")
    print("=" * 60)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Add is_mined column to email_archive (if not exists)
        print("\n[1/4] Adding is_mined column to email_archive...")
        cur.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'email_archive' AND column_name = 'is_mined'
                ) THEN
                    ALTER TABLE email_archive 
                    ADD COLUMN is_mined BOOLEAN DEFAULT FALSE;
                END IF;
            END $$;
        """)
        conn.commit()
        print("   ✅ Column 'is_mined' added/verified")
        
        # 2. Create finance_invoices table
        print("\n[2/4] Creating finance_invoices table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS finance_invoices (
                id SERIAL PRIMARY KEY,
                vendor TEXT NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                date DATE NOT NULL,
                category TEXT,
                source_email_id INTEGER REFERENCES email_archive(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create index on source_email_id for faster lookups
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_finance_source_email 
            ON finance_invoices(source_email_id);
        """)
        
        # Create index on vendor for reporting
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_finance_vendor 
            ON finance_invoices(vendor);
        """)
        
        # Create index on date for time-based queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_finance_date 
            ON finance_invoices(date);
        """)
        
        conn.commit()
        print("   ✅ Table 'finance_invoices' created with indexes")
        
        # 3. Create market_signals table
        print("\n[3/4] Creating market_signals table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_signals (
                id SERIAL PRIMARY KEY,
                ticker TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('BUY', 'SELL')),
                price DECIMAL(10, 4),
                confidence_score DECIMAL(3, 2) CHECK (confidence_score >= 0 AND confidence_score <= 1),
                source_email_id INTEGER REFERENCES email_archive(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create index on source_email_id
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_source_email 
            ON market_signals(source_email_id);
        """)
        
        # Create index on ticker for symbol lookups
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_ticker 
            ON market_signals(ticker);
        """)
        
        # Create index on action for BUY/SELL filtering
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_action 
            ON market_signals(action);
        """)
        
        conn.commit()
        print("   ✅ Table 'market_signals' created with indexes")
        
        # 4. Update existing emails to set is_mined = FALSE (if NULL)
        print("\n[4/4] Updating existing emails (setting is_mined = FALSE if NULL)...")
        cur.execute("""
            UPDATE email_archive 
            SET is_mined = FALSE 
            WHERE is_mined IS NULL;
        """)
        updated_count = cur.rowcount
        conn.commit()
        print(f"   ✅ Updated {updated_count} existing email records")
        
        # Summary
        print("\n" + "=" * 60)
        print("✅ DATABASE UPGRADE COMPLETE")
        print("=" * 60)
        
        # Show table statistics
        cur.execute("SELECT COUNT(*) FROM email_archive WHERE is_mined = FALSE")
        unmined = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM finance_invoices")
        invoices = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM market_signals")
        signals = cur.fetchone()[0]
        
        print(f"\n📊 Database Statistics:")
        print(f"   • Unmined emails: {unmined:,}")
        print(f"   • Finance invoices: {invoices:,}")
        print(f"   • Market signals: {signals:,}")
        
        cur.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error during database upgrade: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    success = upgrade_database()
    exit(0 if success else 1)
