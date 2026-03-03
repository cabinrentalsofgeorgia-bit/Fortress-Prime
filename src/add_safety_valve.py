#!/usr/bin/env python3
"""
Safety Valve Migration: Add CHECK constraint to prevent large expenses
This prevents automated miners from inserting expenses >= $50,000
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    import psycopg2
except ImportError:
    print("❌ Error: psycopg2 required. Install with: pip install psycopg2-binary")
    sys.exit(1)

# Use admin credentials for ALTER TABLE
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
ADMIN_USER = os.getenv("ADMIN_DB_USER", "miner_bot")
ADMIN_PASS = os.getenv("ADMIN_DB_PASS", os.getenv("DB_PASS", ""))

print("🛡️  FORTRESS PRIME - Safety Valve Installation")
print("=" * 80)

try:
    # Connect as admin (requires ALTER TABLE privileges)
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=ADMIN_USER,
        password=ADMIN_PASS,
        port=DB_PORT
    )
    conn.autocommit = False
    cur = conn.cursor()
    
    # Step 1: Verify cleanup - Check if bad expense (id = 286) exists
    print("\n[1/3] Verifying cleanup (checking for id = 286)...")
    cur.execute("SELECT * FROM finance_invoices WHERE id = 286;")
    bad_row = cur.fetchone()
    
    if bad_row:
        print(f"⚠️  WARNING: Bad expense still exists!")
        print(f"   Data: {bad_row}")
        print(f"\n   Deleting bad expense...")
        cur.execute("DELETE FROM finance_invoices WHERE id = 286;")
        conn.commit()
        print("   ✅ Bad expense deleted")
    else:
        print("   ✅ Clean: Bad expense (id = 286) not found")
    
    # Check for other large amounts
    print("\n[2/3] Checking for other large amounts (>= $50,000)...")
    cur.execute("""
        SELECT id, vendor, amount, date 
        FROM finance_invoices 
        WHERE amount >= 50000 
        ORDER BY amount DESC
        LIMIT 10;
    """)
    large_amounts = cur.fetchall()
    
    if large_amounts:
        print(f"   ⚠️  Found {len(large_amounts)} transactions >= $50,000:")
        for row in large_amounts:
            print(f"      ID: {row[0]}, Vendor: {row[1]}, Amount: ${row[2]:,.2f}, Date: {row[3]}")
        print("\n   ⚠️  These will need to be reviewed manually.")
        print("   ⚠️  The constraint will prevent NEW large amounts, but won't affect existing ones.")
    else:
        print("   ✅ No large amounts found")
    
    # Step 2: Check if constraint already exists
    print("\n[3/3] Installing safety valve constraint...")
    cur.execute("""
        SELECT constraint_name 
        FROM information_schema.table_constraints 
        WHERE table_name = 'finance_invoices' 
          AND constraint_name = 'check_sane_amount';
    """)
    
    existing = cur.fetchone()
    
    if existing:
        print("   ℹ️  Constraint 'check_sane_amount' already exists - skipping")
    else:
        print("   Adding CHECK constraint: amount < 50000")
        try:
            cur.execute("""
                ALTER TABLE finance_invoices 
                ADD CONSTRAINT check_sane_amount 
                CHECK (amount < 50000);
            """)
            conn.commit()
            print("   ✅ Safety valve installed successfully!")
            print("\n   What this means:")
            print("   • Any INSERT/UPDATE with amount >= $50,000 will be REJECTED")
            print("   • Database will return: 'ERROR: violated check constraint check_sane_amount'")
            print("   • Forces manual review of large transactions (like asset purchases)")
        except psycopg2.Error as e:
            conn.rollback()
            print(f"   ❌ Error adding constraint: {e}")
            print("   This may fail if there are existing rows with amount >= 50000")
            print("   Review and clean up large amounts first, then rerun this script")
            sys.exit(1)
    
    # Verify constraint
    cur.execute("""
        SELECT constraint_name, check_clause
        FROM information_schema.table_constraints tc
        JOIN information_schema.check_constraints cc ON tc.constraint_name = cc.constraint_name
        WHERE tc.table_name = 'finance_invoices' 
          AND tc.constraint_name = 'check_sane_amount';
    """)
    constraint_info = cur.fetchone()
    
    if constraint_info:
        print(f"\n   ✅ Constraint verified: {constraint_info[0]}")
        print(f"   Rule: {constraint_info[1]}")
    
    # Test constraint with a fake insert (rollback)
    print("\n   Testing constraint (this should fail)...")
    try:
        cur.execute("""
            INSERT INTO finance_invoices (vendor, amount, date) 
            VALUES ('TEST', 100000, CURRENT_DATE);
        """)
        conn.rollback()
        print("   ⚠️  WARNING: Test insert succeeded - constraint may not be working!")
    except psycopg2.IntegrityError as e:
        conn.rollback()
        if 'check_sane_amount' in str(e):
            print("   ✅ Constraint working correctly! (test insert correctly rejected)")
        else:
            print(f"   ℹ️  Test failed for different reason: {e}")
    
    cur.close()
    conn.close()
    
    print("\n" + "=" * 80)
    print("✅ Safety Valve Installation Complete!")
    print("=" * 80)
    
except psycopg2.OperationalError as e:
    print(f"❌ Database connection error: {e}")
    print("   Check your admin credentials in .env file")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
