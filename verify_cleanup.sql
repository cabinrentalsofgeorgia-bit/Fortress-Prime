-- Step 1: Verify Cleanup - Check if bad expense (id = 286) is gone
-- Run with: sudo -u postgres psql -d fortress_db -f verify_cleanup.sql
-- Or: psql "postgresql://analyst_reader:PASSWORD@localhost:5432/fortress_db" -f verify_cleanup.sql

-- Check if id 286 exists
SELECT * FROM finance_invoices WHERE id = 286;

-- If above returns a row, run this DELETE:
-- DELETE FROM finance_invoices WHERE id = 286;

-- Also check for any other suspiciously large amounts
SELECT id, vendor, amount, date, category 
FROM finance_invoices 
WHERE amount >= 50000 
ORDER BY amount DESC;
