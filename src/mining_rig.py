"""
🛡️ FORTRESS PRIME - Email Mining Rig (Sovereign Cluster Topology)
High-Frequency Filtering with Hedge Fund Data Extraction.

Spark-2 (The Gatekeeper): Local keyword scanning for pre-filtering.
Spark-1 (The Extractor): AI-powered extraction of trades and invoices.
"""

import os
import json
import time
import re
import psycopg2
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


# Load environment variables
load_dotenv()

# Configuration - Sovereign Cluster Topology
# Controller: Spark-2 (localhost)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
# Use admin credentials for write operations (mining requires INSERT/UPDATE)
DB_USER = os.getenv("ADMIN_DB_USER") or os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("ADMIN_DB_PASS") or os.getenv("DB_PASS", _MINER_BOT_PASSWORD)

# Inference Engine: Spark-1 (Ollama)
WORKER_IP = "192.168.0.104"
OLLAMA_API = f"http://{WORKER_IP}:11434/api/generate"
MODEL = "mistral:latest"
API_TIMEOUT = 30  # 30-second timeout for API calls (local models need time)

# Hedge Fund Smart Filter - Keyword lists (Spark-2 CPU)
TRADING_SIGNALS = [
    'bought', 'sold', 'filled', 'dividend', 'distribution', 'yield',
    'ticker', 'symbol', 'trade confirmation', 'shares'
]

FINANCIALS = [
    'invoice', 'receipt', 'payment', 'total', 'amount', 'billing'
]


def get_db_connection():
    """Establish database connection."""
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )


def mark_email_as_mined(conn, cur, email_id: int):
    """
    Mark an email as mined to prevent infinite loops.
    
    Args:
        conn: Database connection
        cur: Database cursor
        email_id: Email ID to mark as mined
    """
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
    Aggressively block spam (e.g., Buy.com Deals) before GPU processing.
    
    Args:
        sender: Email sender address
        subject: Email subject line
        email_body: Email content
        
    Returns:
        True if should process, False if should block
    """
    sender_lower = sender.lower() if sender else ""
    subject_lower = subject.lower() if subject else ""
    body_lower = email_body.lower() if email_body else ""
    
    # First Check: The Blocklist - RETURN FALSE immediately if spam detected
    spam_sender_terms = ['enews', 'newsletter', 'offers', 'deals', 'marketing', 'update', 'notification']
    spam_subject_terms = ['deals', 'blowout', 'sale', '% off']
    
    # Check sender for spam terms
    if any(term in sender_lower for term in spam_sender_terms):
        print(f"   🛑 Spam Blocked: {subject[:30]}... (Sender: {sender[:40]})")
        return False
    
    # Check subject for spam terms
    if any(term in subject_lower for term in spam_subject_terms):
        print(f"   🛑 Spam Blocked: {subject[:30]}...")
        return False
    
    # Second Check: The Positive Signal - Only return TRUE if body contains strong finance terms
    strong_finance_terms = [
        'invoice', 'order #', 'order number', 'confirmation', 
        'shipped', 'trade', 'dividend', 'ticker'
    ]
    
    has_strong_signal = any(term in body_lower for term in strong_finance_terms)
    
    if not has_strong_signal:
        return False
    
    return True


def clean_and_validate_amount(amount_str: Any) -> Optional[float]:
    """
    Clean and validate amount string, handling edge cases like '1.0 LBS'.
    
    Args:
        amount_str: Amount as string, float, int, or None
        
    Returns:
        Cleaned numeric amount or None if invalid
    """
    if amount_str is None:
        return None
    
    # Convert to string if not already
    if isinstance(amount_str, (int, float)):
        amount_str = str(amount_str)
    
    if not isinstance(amount_str, str):
        return None
    
    amount_str = amount_str.strip().upper()
    
    # Check for invalid units (LBS, KG, etc.) - not currency values
    invalid_units = ['LBS', 'LB', 'KG', 'KGS', 'OZ', 'OUNCES', 'G', 'GRAMS', 'ML', 'L', 'LITERS']
    if any(unit in amount_str for unit in invalid_units):
        return None
    
    # Extract first valid number using regex
    # Pattern matches: optional $, digits with optional decimal point
    pattern = r'[\$]?\s*(\d+(?:\.\d+)?)'
    match = re.search(pattern, amount_str)
    
    if not match:
        return None
    
    try:
        amount_value = float(match.group(1))
        
        # Validate amount is reasonable (greater than 0 and less than 1 billion)
        if amount_value <= 0 or amount_value >= 1e9:
            return None
        
        return amount_value
    except (ValueError, AttributeError):
        return None


def analyze_with_spark1(email_body: str) -> Optional[Dict[str, Any]]:
    """
    The Extraction (Spark-1 GPU).
    Analyzes email for Hedge Fund Intelligence.
    
    Args:
        email_body: Email content to analyze
        
    Returns:
        Parsed JSON dictionary with extracted data, or None on error
    """
    # Truncate email body to reasonable size (8000 chars)
    truncated_body = email_body[:8000]
    
    # System Prompt for Hedge Fund Intelligence
    prompt = f"""Analyze for Hedge Fund Intelligence. Return JSON: {{
    "type": "TRADE" or "INVOICE",
    "ticker": "SYMBOL" (or null),
    "action": "BUY/SELL/DIVIDEND" (or null),
    "price": 0.00 (execution price),
    "vendor": "Name" (if invoice),
    "amount": 0.00 (total value),
    "date": "YYYY-MM-DD"
}}

EMAIL:
{truncated_body}"""
    
    try:
        print("   ⚡ Spark-1 Processing...")
        
        # Call Ollama API with JSON format enforced
        response = requests.post(
            OLLAMA_API,
            json={
                "model": MODEL,
                "prompt": prompt,
                "format": "json",  # Strict JSON mode
                "stream": False
            },
            timeout=API_TIMEOUT
        )
        
        if response.status_code != 200:
            print(f"   ❌ API error: {response.status_code} - {response.text[:100]}")
            return None
        
        # Extract response text
        response_data = response.json()
        response_text = response_data.get("response", "")
        
        if not response_text:
            print(f"   ⚠️  Empty response from Spark-1")
            return None
        
        # Clean response (remove markdown code blocks if present)
        response_text = response_text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.startswith('```'):
            response_text = response_text[3:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        # Parse JSON
        try:
            data = json.loads(response_text)
            return data
        except json.JSONDecodeError as e:
            print(f"   ⚠️  JSON parsing error: {e}")
            print(f"   Response: {response_text[:200]}...")
            return None
        
    except requests.exceptions.Timeout:
        print(f"   ❌ API timeout after {API_TIMEOUT} seconds")
        return None
    except requests.exceptions.ConnectionError:
        print(f"   ❌ Connection error: Cannot reach Spark-1 at {WORKER_IP}")
        return None
    except Exception as e:
        print(f"   ❌ Spark-1 API error: {e}")
        return None


def process_emails(batch_size: int = 20) -> bool:
    """
    Fetch and process unmined emails.
    
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
    
    print(f"\n📧 Processing {len(emails)} emails...\n")
    
    processed = 0
    invoices_created = 0
    signals_created = 0
    errors = 0
    skipped_low_value = 0
    
    for email_id, sender, subject, content, sent_at in emails:
        print(f"[{processed + 1}/{len(emails)}] Processing email #{email_id}")
        print(f"   From: {sender}")
        print(f"   Subject: {subject[:60]}...")
        
        # Use try/finally to ensure email is always marked as mined, even on errors
        try:
            # Aggressive Spam Blocking: Check BEFORE any GPU processing
            if not should_process_email(sender, subject, content):
                skipped_low_value += 1
                # Will be marked as mined in finally block
                continue
            
            # If passed spam check, send to Spark-1 (The Extraction)
            print(f"   ✅ Passed spam filter - Sending to Spark-1 GPU...")
            analysis = analyze_with_spark1(content)
            
            if not analysis:
                print(f"   ❌ Extraction failed, marking as skipped")
                errors += 1
                # Will be marked as mined in finally block (Zombie Email prevention)
                continue
            
            # Process extracted data
            extracted_type = analysis.get("type", "").upper()
            
            # The Router: If type is 'TRADE', insert into market_signals
            if extracted_type == "TRADE":
                ticker = analysis.get("ticker")
                action = analysis.get("action", "").upper()
                price_raw = analysis.get("price")  # Execution price for trades
                date_str = analysis.get("date")
                
                if ticker and action in ("BUY", "SELL", "DIVIDEND"):
                    try:
                        # Clean and validate price (execution price)
                        price_value = None
                        if price_raw:
                            price_value = clean_and_validate_amount(price_raw)
                        
                        # Default confidence score
                        confidence_score = 0.8 if price_value else 0.6
                        
                        # Insert into market_signals (ticker, action, price, source_email_id)
                        cur.execute("""
                            INSERT INTO market_signals
                            (ticker, action, price, confidence_score, source_email_id)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            str(ticker)[:10],  # Limit length
                            action,
                            price_value,
                            confidence_score,
                            email_id
                        ))
                        signals_created += 1
                        price_str = f"${price_value:.2f}" if price_value else "N/A"
                        print(f"   📈 TRADE: {ticker} {action} @ {price_str}")
                    except Exception as e:
                        print(f"   ❌ Trade insert error: {e}")
                        conn.rollback()
            
            # The Router: If type is 'INVOICE', insert into finance_invoices
            elif extracted_type == "INVOICE":
                vendor = analysis.get("vendor")
                amount_raw = analysis.get("amount")  # Total value for invoices
                date_str = analysis.get("date")
                
                # Clean and validate amount
                amount = clean_and_validate_amount(amount_raw)
                
                # Logic: If amount is 0 or None, don't save invoice (likely shipping notification)
                if vendor and amount and amount > 0:
                    try:
                        # Validate and parse date
                        try:
                            if isinstance(date_str, str):
                                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                            else:
                                # Use email sent_at if date parsing fails
                                parsed_date = sent_at.date() if sent_at else datetime.now().date()
                        except (ValueError, TypeError):
                            parsed_date = sent_at.date() if sent_at else datetime.now().date()
                        
                        # Insert into finance_invoices (vendor, amount, date, source_email_id)
                        cur.execute("""
                            INSERT INTO finance_invoices 
                            (vendor, amount, date, category, source_email_id)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            str(vendor)[:255],  # Limit length
                            float(amount),
                            parsed_date,
                            None,  # Category not in prompt
                            email_id
                        ))
                        invoices_created += 1
                        print(f"   💰 INVOICE: {vendor} - ${amount:.2f}")
                    except Exception as e:
                        print(f"   ❌ Invoice insert error: {e}")
                        conn.rollback()
                elif amount is None or amount == 0:
                    print(f"   ℹ️  Skipping invoice with invalid/zero amount")
            
            else:
                print(f"   ℹ️  No extractable data found (type: {extracted_type})")
        
        except Exception as e:
            # Catch any unexpected errors during processing
            print(f"   ❌ Unexpected error: {e}")
            errors += 1
        
        finally:
            # Robustness: Handle "Zombie Emails" - Always mark as mined even on error
            # Prevents infinite loops from stuck emails
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
    print(f"   • Low-value skipped: {skipped_low_value}")
    print(f"   • Finance invoices extracted: {invoices_created}")
    print(f"   • Trades extracted: {signals_created}")
    print(f"   • Errors: {errors}")
    
    cur.close()
    conn.close()
    return True  # Emails were found and processed


if __name__ == "__main__":
    # Startup Banner
    print("🛡️  FORTRESS PRIME - Email Mining Rig (Sovereign Cluster)")
    print("=" * 60)
    print(f"📡 Controller: Spark-2 (localhost)")
    print(f"⚡ Inference: Spark-1 ({WORKER_IP}) - {MODEL}")
    print("=" * 60)
    print("⚙️  Industrial Mode: Continuous Processing Active")
    print("🛑 Press Ctrl+C to stop")
    print("=" * 60)
    
    # Verify Spark-1 connectivity
    try:
        response = requests.get(f"http://{WORKER_IP}:11434/api/tags", timeout=5)
        if response.status_code != 200:
            print(f"⚠️  Warning: Spark-1 connection test failed")
        else:
            models = [m['name'] for m in response.json().get('models', [])]
            if MODEL not in models:
                print(f"⚠️  Warning: Model '{MODEL}' not found on Spark-1")
                print(f"   Available models: {', '.join(models)}")
            else:
                print(f"✅ Spark-1 connection verified. Model '{MODEL}' ready.")
    except Exception as e:
        print(f"⚠️  Warning: Cannot verify Spark-1 connection: {e}")
        print(f"   Continuing anyway...")
    
    print()  # Blank line before loop starts
    
    # Industrial Mode: Continuous Loop
    batch_count = 0
    try:
        while True:
            batch_count += 1
            
            try:
                # Attempt to process emails (batch size increased to 20 with Spark-2 filtering)
                emails_found = process_emails(batch_size=20)
                
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
                
            except requests.exceptions.RequestException as e:
                # Spark-1 connection error
                print(f"\n❌ Spark-1 Connection Error: {e}")
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
