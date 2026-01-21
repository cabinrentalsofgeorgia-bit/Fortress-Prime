-- Step 2: Install Safety Valve - Add CHECK constraint to prevent large expenses
-- Run with: sudo -u postgres psql -d fortress_db -f add_safety_valve.sql
-- Or as admin user: psql -U miner_bot -d fortress_db -f add_safety_valve.sql

-- Check if constraint already exists
SELECT constraint_name, constraint_type 
FROM information_schema.table_constraints 
WHERE table_name = 'finance_invoices' 
  AND constraint_name = 'check_sane_amount';

-- If above returns nothing, add the constraint:
-- This prevents any invoice >= $50,000 from being inserted
ALTER TABLE finance_invoices 
ADD CONSTRAINT check_sane_amount 
CHECK (amount < 50000);

-- Verify the constraint was added
SELECT constraint_name, constraint_type, check_clause
FROM information_schema.table_constraints tc
JOIN information_schema.check_constraints cc ON tc.constraint_name = cc.constraint_name
WHERE tc.table_name = 'finance_invoices' 
  AND tc.constraint_name = 'check_sane_amount';
