#!/usr/bin/env python3
"""
Quick inspection script for Zillow expense data
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    import psycopg2
    import pandas as pd
except ImportError:
    print("❌ Error: psycopg2 and pandas required. Install with: pip install psycopg2-binary pandas")
    sys.exit(1)

# Database connection
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "analyst_reader")
DB_PASSWORD = os.getenv("DB_PASSWORD", "6652201a")

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=int(DB_PORT)
    )
    
    print("=" * 80)
    print("ZILLOW TRANSACTIONS (Raw Data)")
    print("=" * 80)
    
    # Query 1: Raw Zillow transactions
    df = pd.read_sql("SELECT * FROM finance_invoices WHERE vendor = 'Zillow' ORDER BY date DESC LIMIT 10;", conn)
    
    if df.empty:
        print("No Zillow transactions found.")
    else:
        print(f"\nFound {len(df)} Zillow transactions (showing 10 most recent):\n")
        print(df.to_string(index=False))
        
        # Summary stats
        print("\n" + "=" * 80)
        print("SUMMARY STATISTICS")
        print("=" * 80)
        print(f"Total Amount: ${df['amount'].sum():,.2f}")
        print(f"Average Amount: ${df['amount'].mean():,.2f}")
        print(f"Largest Transaction: ${df['amount'].max():,.2f}")
        print(f"Smallest Transaction: ${df['amount'].min():,.2f}")
        print(f"Date Range: {df['date'].min()} to {df['date'].max()}")
        
        # Category breakdown if available
        if 'category' in df.columns and df['category'].notna().any():
            print("\n" + "=" * 80)
            print("CATEGORY BREAKDOWN")
            print("=" * 80)
            category_summary = df.groupby('category').agg({
                'amount': ['count', 'sum', 'mean']
            }).round(2)
            print(category_summary.to_string())
    
    print("\n" + "=" * 80)
    print("TABLE STRUCTURE")
    print("=" * 80)
    
    # Query 2: Table structure
    df_structure = pd.read_sql("""
        SELECT column_name, data_type, is_nullable 
        FROM information_schema.columns 
        WHERE table_name = 'finance_invoices' 
        ORDER BY ordinal_position;
    """, conn)
    print(df_structure.to_string(index=False))
    
    # Query 3: Source email content if available
    print("\n" + "=" * 80)
    print("SOURCE EMAIL CONTENT (First 3 Zillow transactions)")
    print("=" * 80)
    
    cur = conn.cursor()
    cur.execute("""
        SELECT fi.source_email_id, fi.amount, fi.date
        FROM finance_invoices fi
        WHERE fi.vendor = 'Zillow' AND fi.source_email_id IS NOT NULL
        ORDER BY fi.date DESC
        LIMIT 3;
    """)
    
    source_records = cur.fetchall()
    if source_records:
        for source_email_id, amount, date in source_records:
            cur.execute("""
                SELECT sender, subject, LEFT(content, 800) as content_preview 
                FROM email_archive 
                WHERE id = %s
            """, (source_email_id,))
            email_data = cur.fetchone()
            
            if email_data:
                print(f"\n{'=' * 80}")
                print(f"Transaction: ${amount:,.2f} on {date}")
                print(f"Email ID: {source_email_id}")
                print(f"{'=' * 80}")
                print(f"Sender: {email_data[0]}")
                print(f"Subject: {email_data[1]}")
                print(f"\nContent Preview:\n{email_data[2]}")
                print(f"\n{'-' * 80}")
    else:
        print("No source email IDs found for Zillow transactions.")
    
    cur.close()
    conn.close()
    
    print("\n✅ Inspection complete!")
    
except psycopg2.OperationalError as e:
    print(f"❌ Database connection error: {e}")
    print("   Please check your database credentials in .env file")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
