"""
🛡️ FORTRESS PRIME - Email Mining Rig with Data Router Integration
Combines existing mining logic with SQLAlchemy-based routing system.
"""

import os
import sys
import time
import requests
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

# Import the router
from data_router import route_incoming_data, create_tables

load_dotenv()

# Configuration - Sovereign Cluster Topology
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("ADMIN_DB_USER") or os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))

# Inference Engine: Spark-1 (Ollama)
WORKER_IP = "192.168.0.104"
OLLAMA_API = f"http://{WORKER_IP}:11434/api/generate"
MODEL = "mistral:latest"
API_TIMEOUT = 30

# Hedge Fund Smart Filter - Keyword lists (Spark-2 CPU)
TRADING_SIGNALS = [
    'bought', 'sold', 'filled', 'dividend', 'distribution', 'yield',
    'ticker', 'symbol', 'trade confirmation', 'shares'
]

FINANCIALS = [
    'invoice', 'receipt', 'payment', 'total', 'amount', 'billing'
]

SPAM_SENDER_TERMS = ['enews', 'newsletter', 'offers', 'deals', 'marketing', 'update', 'notification']
SPAM_SUBJECT_TERMS = ['deals', 'blowout', 'sale', '% off']
STRONG_FINANCE_TERMS = ['invoice', 'order #', 'order number', 'confirmation', 'shipped', 'trade', 'dividend', 'ticker']


def get_db_connection():
    """Establish database connection (for email queries only)."""
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )


def mark_email_as_mined(conn, cur, email_id: int):
    """Mark an email as mined to prevent infinite loops."""
    try:
        cur.execute("""
            UPDATE email_archive 
            SET is_mined = TRUE 
            WHERE id = %s
        """, (email_id,))
        conn.commit()
    except Exception as e:
        print(f"   ⚠️  Error marking email as mined: {e}")
        conn.rollback()


def should_process_email(sender: str, subject: str, email_body: str) -> bool:
    """
    Aggressive spam blocking before GPU processing.
    """
    sender_lower = sender.lower() if sender else ""
    subject_lower = subject.lower() if subject else ""
    body_lower = email_body.lower() if email_body else ""

    # First Check: The Blocklist - RETURN FALSE immediately if spam detected
    if any(term in sender_lower for term in SPAM_SENDER_TERMS):
        print(f"   🛑 Spam Blocked: {subject[:30]}... (Sender: {sender[:40]})")
        return False
    if any(term in subject_lower for term in SPAM_SUBJECT_TERMS):
        print(f"   🛑 Spam Blocked: {subject[:30]}...")
        return False

    # Second Check: The Positive Signal - Only return TRUE if body contains strong finance terms
    has_strong_signal = any(term in body_lower for term in STRONG_FINANCE_TERMS)
    if not has_strong_signal:
        return False
    return True


def process_emails_with_router(batch_size: int = 20) -> bool:
    """
    Fetch and process unmined emails using the data router.
    
    Args:
        batch_size: Number of emails to process per run
        
    Returns:
        True if emails were found and processed, False if queue is empty
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch oldest unmined emails
    cur.execute("""
        SELECT id, sender, subject, content, sent_at
        FROM email_archive
        WHERE is_mined = FALSE
        AND content IS NOT NULL
        AND LENGTH(content) > 50
        ORDER BY sent_at ASC
        LIMIT %s
    """, (batch_size,))
    
    emails = cur.fetchall()
    
    if not emails:
        cur.close()
        conn.close()
        return False  # No emails found
    
    print(f"\n📧 Processing {len(emails)} emails with router...\n")
    
    # Initialize router tables
    create_tables()
    
    processed = 0
    routed = {
        'real_estate': 0,
        'finance': 0,
        'market': 0,
        'legal': 0,
        'no_route': 0,
        'errors': 0
    }
    
    for email_id, sender, subject, content, sent_at in emails:
        print(f"[{processed + 1}/{len(emails)}] Processing email #{email_id}")
        print(f"   From: {sender}")
        print(f"   Subject: {subject[:60]}...")
        
        try:
            # Use the router to analyze and route
            email_data = {
                'sender': sender or '',
                'subject': subject or '',
                'content': content or '',
                'date': sent_at.date() if sent_at else datetime.now().date()
            }
            
            result = route_incoming_data(email_data, source_email_id=email_id)
            
            if result['success']:
                route = result['route']
                if route in routed:
                    routed[route] += 1
                    print(f"   ✅ Routed to {route}: Record ID {result['record_id']}")
                else:
                    routed['no_route'] += 1
                    print(f"   ℹ️  Routed to {route} (not tracked)")
            else:
                if result['error']:
                    if 'exceeds $50,000' in result['error']:
                        routed['errors'] += 1
                        print(f"   ⚠️  Safety Valve: {result['error']}")
                    else:
                        routed['errors'] += 1
                        print(f"   ❌ Routing error: {result['error']}")
                else:
                    routed['no_route'] += 1
                    print(f"   ℹ️  No route found for this email")
        
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
            routed['errors'] += 1
        
        finally:
            # Always mark as mined (Zombie Email prevention)
            try:
                mark_email_as_mined(conn, cur, email_id)
            except Exception as e:
                print(f"   ⚠️  Critical: Cannot mark email as mined: {e}")
            
            processed += 1
            print()
    
    # Summary
    print("=" * 60)
    print("✅ BATCH COMPLETE")
    print("=" * 60)
    print(f"📊 Statistics:")
    print(f"   • Emails processed: {processed}")
    print(f"   • Routed to real_estate_intel: {routed['real_estate']}")
    print(f"   • Routed to finance_invoices: {routed['finance']}")
    print(f"   • Routed to market_intel: {routed['market']}")
    print(f"   • Routed to legal_intel: {routed['legal']}")
    print(f"   • No route found: {routed['no_route']}")
    print(f"   • Errors: {routed['errors']}")
    
    cur.close()
    conn.close()
    return True  # Emails were found and processed


if __name__ == "__main__":
    # Startup Banner
    print("🛡️  FORTRESS PRIME - Email Mining Rig with Data Router")
    print("=" * 60)
    print(f"📡 Controller: Spark-2 (localhost)")
    print(f"⚡ Router: SQLAlchemy-based intelligent routing")
    print("=" * 60)
    print("⚙️  Industrial Mode: Continuous Processing Active")
    print("🛑 Press Ctrl+C to stop")
    print("=" * 60)
    
    # Create tables on startup
    print("\n🔧 Initializing database tables...")
    create_tables()
    
    print()  # Blank line before loop starts
    
    # Industrial Mode: Continuous Loop
    batch_count = 0
    try:
        while True:
            batch_count += 1
            
            try:
                # Process emails with router
                emails_found = process_emails_with_router(batch_size=20)
                
                if emails_found:
                    # Emails were processed, immediately fetch next batch (no sleep)
                    continue
                else:
                    # No emails found, sleep before checking again
                    print("💤 Queue empty. Sleeping for 30s...")
                    time.sleep(30)
                    
            except KeyboardInterrupt:
                # Graceful shutdown on Ctrl+C
                print("\n\n" + "=" * 60)
                print("🛑 SHUTDOWN REQUESTED")
                print("=" * 60)
                print(f"📊 Total batches processed: {batch_count - 1}")
                print("✅ Mining rig stopped gracefully.")
                break
                
            except (psycopg2.Error, psycopg2.OperationalError) as e:
                # Database connection error
                print(f"\n❌ Database Error: {e}")
                print("   Retrying in 5 seconds...")
                time.sleep(5)
                
            except Exception as e:
                # Catch-all for any other errors
                print(f"\n❌ Unexpected Error: {e}")
                print("   Retrying in 5 seconds...")
                time.sleep(5)
                
    except KeyboardInterrupt:
        # Final catch for Ctrl+C at top level
        print("\n\n🛑 Shutdown signal received. Exiting...")
