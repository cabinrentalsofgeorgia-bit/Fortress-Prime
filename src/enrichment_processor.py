"""
🛡️ FORTRESS PRIME - Automated Enrichment Processor
Continuously monitors database for new records and triggers enrichment automatically.
Can run as a background service or be triggered after inserts.
"""

import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

from enrichment_service import (
    enrich_market_intel,
    enrich_legal_intel,
    process_pending_enrichments,
    SessionLocal,
    MarketIntel,
    LegalIntel
)

load_dotenv()

# Configuration
ENRICHMENT_INTERVAL = int(os.getenv("ENRICHMENT_INTERVAL", "30"))  # Check every 30 seconds
BATCH_SIZE = int(os.getenv("ENRICHMENT_BATCH_SIZE", "10"))  # Process 10 records per batch


def get_unenriched_count() -> dict:
    """Get count of unenriched records."""
    session = SessionLocal()
    try:
        market_count = session.query(MarketIntel).filter(
            (MarketIntel.ticker == None) | (MarketIntel.asset_class == None),
            MarketIntel.content.isnot(None)
        ).count()
        
        legal_count = session.query(LegalIntel).filter(
            (LegalIntel.priority == None) | (LegalIntel.next_deadline == None),
            LegalIntel.content.isnot(None)
        ).count()
        
        return {
            'market': market_count,
            'legal': legal_count,
            'total': market_count + legal_count
        }
    finally:
        session.close()


def continuous_enrichment_loop():
    """
    Continuous loop that processes pending enrichments.
    Runs indefinitely, checking for new records every ENRICHMENT_INTERVAL seconds.
    """
    print("🛡️  FORTRESS PRIME - Automated Enrichment Processor")
    print("=" * 60)
    print("⚙️  Continuous Enrichment Mode Active")
    print(f"📊 Check interval: {ENRICHMENT_INTERVAL} seconds")
    print(f"📦 Batch size: {BATCH_SIZE} records")
    print("🛑 Press Ctrl+C to stop")
    print("=" * 60)
    
    iteration = 0
    
    try:
        while True:
            iteration += 1
            print(f"\n[Iteration {iteration}] Checking for pending enrichments...")
            
            # Get counts
            counts = get_unenriched_count()
            print(f"   📊 Pending: {counts['market']} market, {counts['legal']} legal (total: {counts['total']})")
            
            if counts['total'] > 0:
                print(f"   🔄 Processing batch of {BATCH_SIZE} records...")
                stats = process_pending_enrichments(batch_size=BATCH_SIZE)
                
                print(f"   ✅ Processed: {stats['market_processed']} market, {stats['legal_processed']} legal")
                if stats['market_errors'] > 0 or stats['legal_errors'] > 0:
                    print(f"   ⚠️  Errors: {stats['market_errors']} market, {stats['legal_errors']} legal")
            else:
                print("   💤 No pending enrichments. Waiting...")
            
            # Sleep before next check
            time.sleep(ENRICHMENT_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("🛑 SHUTDOWN REQUESTED")
        print("=" * 60)
        print(f"📊 Total iterations: {iteration}")
        print("✅ Enrichment processor stopped gracefully.")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()


def enrich_new_record(table_name: str, record_id: int) -> dict:
    """
    Enrich a newly inserted record immediately.
    This can be called from triggers or after insert operations.
    
    Args:
        table_name: 'market_intel' or 'legal_intel'
        record_id: ID of the newly inserted record
        
    Returns:
        Enrichment result dictionary
    """
    if table_name == 'market_intel':
        return enrich_market_intel(record_id)
    elif table_name == 'legal_intel':
        return enrich_legal_intel(record_id)
    else:
        return {
            'success': False,
            'error': f'Unknown table: {table_name}'
        }


if __name__ == "__main__":
    # Run continuous enrichment loop
    continuous_enrichment_loop()
