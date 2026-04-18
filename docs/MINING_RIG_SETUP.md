# 🛡️ Email Mining Rig - Setup Guide

## Overview

The Email Mining Rig is an intelligent email processing system that uses Google Gemini AI to extract structured data from emails. It automatically identifies and extracts:
- **Finance Invoices**: Vendor payments, bills, expenses
- **Market Signals**: Stock/crypto trading signals (BUY/SELL)

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

New dependencies added:
- `google-generativeai` - Google Gemini API client
- `pydantic` - Data validation
- `python-dotenv` - Environment variable management

### 2. Configure Environment

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your Google Gemini API key:
   ```env
   GOOGLE_API_KEY=your_actual_api_key_here
   ```

3. Verify database configuration matches your setup:
   ```env
   DB_HOST=localhost
   DB_NAME=fortress_db
   DB_USER=miner_bot
   DB_PASS=REPLACE_ME_WITH_REAL_PASSWORD
   ```

**Get a Google Gemini API Key:**
- Visit: https://makersuite.google.com/app/apikey
- Create a new API key
- Copy it to your `.env` file

### 3. Upgrade Database Schema

Run the database upgrade script to create the new tables and add the `is_mined` column:

```bash
python src/init_gold_db.py
```

This will:
- ✅ Add `is_mined` (boolean) column to `email_archive` table
- ✅ Create `finance_invoices` table with indexes
- ✅ Create `market_signals` table with indexes
- ✅ Update existing emails to `is_mined = FALSE`

### 4. Run the Mining Rig

Process unmined emails:

```bash
python src/mining_rig.py
```

The script will:
- Fetch the oldest 10 unmined emails (`is_mined = FALSE`)
- Analyze each email with Gemini AI
- Extract finance invoices and market signals
- Insert structured data into respective tables
- Mark emails as `is_mined = TRUE`

## Database Schema

### New Tables

#### `finance_invoices`
```sql
id SERIAL PRIMARY KEY
vendor TEXT NOT NULL
amount DECIMAL(10, 2) NOT NULL
date DATE NOT NULL
category TEXT
source_email_id INTEGER REFERENCES email_archive(id)
created_at TIMESTAMP
updated_at TIMESTAMP
```

#### `market_signals`
```sql
id SERIAL PRIMARY KEY
ticker TEXT NOT NULL
action TEXT NOT NULL CHECK (action IN ('BUY', 'SELL'))
price DECIMAL(10, 4)
confidence_score DECIMAL(3, 2) CHECK (0 <= score <= 1)
source_email_id INTEGER REFERENCES email_archive(id)
created_at TIMESTAMP
updated_at TIMESTAMP
```

### Modified Table

#### `email_archive`
- Added: `is_mined BOOLEAN DEFAULT FALSE`

## Usage Examples

### Process Specific Batch Size

Edit `src/mining_rig.py` to change the batch size:

```python
process_emails(batch_size=20)  # Process 20 emails per run
```

### Check Mining Status

```sql
-- Count unmined emails
SELECT COUNT(*) FROM email_archive WHERE is_mined = FALSE;

-- View extracted invoices
SELECT * FROM finance_invoices ORDER BY date DESC LIMIT 10;

-- View extracted market signals
SELECT * FROM market_signals ORDER BY created_at DESC LIMIT 10;
```

### Run as Scheduled Job

Add to crontab for automatic processing every hour:

```bash
# Edit crontab
crontab -e

# Add this line (runs every hour)
0 * * * * cd /path/to/fortress-prime && python src/mining_rig.py >> logs/mining_rig.log 2>&1
```

## Data Validation

The system uses Pydantic models for strict data validation:

- **FinanceInvoice**: Validates vendor names, positive amounts, date format (YYYY-MM-DD)
- **MarketSignal**: Validates ticker symbols, BUY/SELL actions, confidence scores (0-1)
- **EmailAnalysis**: Validates overall extraction confidence

## Error Handling

- Invalid JSON responses from Gemini are logged and skipped
- Individual invoice/signal insertion errors don't stop batch processing
- Failed emails remain `is_mined = FALSE` for retry

## Performance Notes

- Default batch size: 10 emails per run
- Gemini API rate limits apply (check your quota)
- Processing time: ~2-5 seconds per email (depends on Gemini API response time)

## Troubleshooting

### "GOOGLE_API_KEY not found"
- Ensure `.env` file exists in project root
- Verify `GOOGLE_API_KEY=your_key` is set in `.env`
- Check file permissions

### "Table does not exist"
- Run `python src/init_gold_db.py` to create tables

### "Connection refused"
- Verify PostgreSQL is running
- Check database credentials in `.env`
- Ensure `fortress_db` database exists

### Low extraction accuracy
- Gemini responses may vary
- Check `extraction_confidence` scores in logs
- Consider adjusting the prompt in `analyze_with_gemini()` function

---

**Next Steps:**
- Schedule regular mining runs
- Build dashboard views for extracted data
- Create alerts for high-value transactions
- Analyze market signal accuracy over time
