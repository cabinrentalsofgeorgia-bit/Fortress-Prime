-- Inspection queries for Zillow expense data
-- Run these with: psql "postgresql://analyst_reader:PASSWORD@localhost:5432/fortress_db" -f inspect_zillow.sql

-- 1. Raw Zillow transactions (First 5 rows)
SELECT * FROM finance_invoices WHERE vendor = 'Zillow' LIMIT 5;

-- 2. Table structure - see all available columns
SELECT 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'finance_invoices' 
ORDER BY ordinal_position;

-- 3. All Zillow transactions with summary
SELECT 
    id,
    vendor,
    amount,
    date,
    category,
    source_email_id,
    extracted_at
FROM finance_invoices 
WHERE vendor = 'Zillow'
ORDER BY date DESC;

-- 4. Zillow summary statistics
SELECT 
    COUNT(*) as transaction_count,
    SUM(amount) as total_amount,
    AVG(amount) as avg_amount,
    MIN(amount) as min_amount,
    MAX(amount) as max_amount,
    MIN(date) as earliest_date,
    MAX(date) as latest_date,
    COUNT(DISTINCT category) as unique_categories
FROM finance_invoices 
WHERE vendor = 'Zillow';

-- 5. Zillow transactions by category (if category column exists)
SELECT 
    category,
    COUNT(*) as count,
    SUM(amount) as total,
    AVG(amount) as average
FROM finance_invoices 
WHERE vendor = 'Zillow'
GROUP BY category
ORDER BY total DESC;

-- 6. Source email content for Zillow transactions (first 500 chars)
SELECT 
    fi.id,
    fi.vendor,
    fi.amount,
    fi.date,
    fi.category,
    ea.sender,
    ea.subject,
    LEFT(ea.content, 500) as email_content_preview
FROM finance_invoices fi
LEFT JOIN email_archive ea ON fi.source_email_id = ea.id
WHERE fi.vendor = 'Zillow'
ORDER BY fi.date DESC
LIMIT 5;
