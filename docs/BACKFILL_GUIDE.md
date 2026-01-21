# 🛡️ FORTRESS PRIME - Backfill & Enrich Agent Guide

## Overview

The Backfill & Enrich Agent scans existing database records and enriches them with LLM-extracted structured data. It processes records where:

- **Market Intel**: `ticker` or `asset_class` columns are NULL
- **Legal Intel**: `case_status`, `priority`, or `next_deadline` columns are NULL

## Features

- ✅ Scans existing rows with NULL enrichment columns
- ✅ Uses LLM (Spark-1 Ollama) to extract structured data from content
- ✅ Updates database rows with extracted data
- ✅ Processes records in batches for efficiency
- ✅ Provides progress tracking and error handling
- ✅ Dry-run mode to preview changes
- ✅ Statistics reporting

## Usage

### Basic Usage

```bash
# Process all pending enrichments
python src/backfill_enrichment.py

# Process with custom batch size
python src/backfill_enrichment.py --batch-size 20

# Dry run (preview without making changes)
python src/backfill_enrichment.py --dry-run

# Show statistics only
python src/backfill_enrichment.py --stats-only
```

### Command-Line Options

- `--batch-size N`: Number of records to process per batch (default: 10)
- `--dry-run`: Preview what would be processed without making changes
- `--stats-only`: Only show statistics, do not process

### Examples

**Check current status:**
```bash
python src/backfill_enrichment.py --stats-only
```

**Preview what would be processed:**
```bash
python src/backfill_enrichment.py --dry-run --batch-size 5
```

**Process all pending records:**
```bash
python src/backfill_enrichment.py --batch-size 10
```

## What Gets Extracted

### Market Intel

**Ticker Symbol:**
- Extracts trading symbols from content
- Examples: 'NVDA', 'BTC', 'AAPL', 'ETH', 'TSLA'
- Normalized to uppercase, max 10 characters

**Asset Class:**
- Classifies asset type: STOCK, CRYPTO, BOND, COMMODITY, FOREX, OPTION, OTHER
- Uses context clues (exchanges, brokers, terminology)

### Legal Intel

**Case Status:**
- Extracts current status: FILED, PENDING, ACTIVE, SETTLED, DISMISSED, etc.
- Up to 100 characters

**Priority Level:**
- Assesses urgency: CRITICAL, HIGH, MEDIUM, LOW, ARCHIVE
- Based on deadlines, language, and legal requirements

**Next Deadline:**
- Extracts most important upcoming date (YYYY-MM-DD format)
- Looks for court dates, filing deadlines, response dates, hearings

## Configuration

Environment variables (`.env`):

```bash
# Database
DB_HOST=localhost
DB_NAME=fortress_db
DB_PORT=5432
ADMIN_DB_USER=miner_bot
ADMIN_DB_PASS=your_password

# LLM Configuration
WORKER_IP=192.168.0.104
LLM_MODEL=mistral:latest
API_TIMEOUT=30
```

## Output

The script provides:

1. **Initial Statistics**: Shows pending and total records
2. **Processing Progress**: Shows each record being processed
3. **Enrichment Results**: Shows extracted data for each record
4. **Final Statistics**: Shows remaining pending records
5. **Processing Time**: Total time taken

Example output:
```
🛡️  FORTRESS PRIME - Backfill & Enrich Agent
================================================================================

📊 Initial Statistics:
   Market Intel: 25 pending / 100 total
   Legal Intel: 15 pending / 50 total

================================================================================
📈 PROCESSING MARKET INTEL
================================================================================

[1] Processing market_intel #42...
   ✅ Enriched: ticker=NVDA, asset_class=STOCK

[2] Processing market_intel #43...
   ✅ Enriched: ticker=BTC, asset_class=CRYPTO

...

================================================================================
✅ BACKFILL COMPLETE
================================================================================
📊 Processing Statistics:
   Market Intel: 25 enriched, 0 errors
   Legal Intel: 15 enriched, 0 errors
   Total Time: 125.3 seconds

📊 Final Statistics:
   Market Intel: 0 pending / 100 total
   Legal Intel: 0 pending / 50 total
```

## Error Handling

- **API Errors**: Retries with exponential backoff
- **JSON Parse Errors**: Logs error and continues with next record
- **Database Errors**: Rolls back transaction and continues
- **Missing Content**: Skips records without content

## Performance

- **Processing Speed**: ~2-5 seconds per record (depends on LLM response time)
- **Batch Processing**: Processes 10 records at a time by default
- **API Throttling**: 0.5 second delay between records to avoid overwhelming LLM

For 100 records:
- Estimated time: ~5-8 minutes
- Can be adjusted with `--batch-size` parameter

## Best Practices

1. **Run dry-run first**: Preview what will be processed
2. **Check statistics**: Verify pending counts before processing
3. **Start small**: Use smaller batch sizes initially
4. **Monitor errors**: Check for patterns in failed enrichments
5. **Run during off-hours**: LLM processing can be resource-intensive

## Troubleshooting

**No records found:**
- Check if records have `content` column populated
- Verify NULL columns actually exist in database
- Run with `--stats-only` to check current status

**LLM API errors:**
- Verify Spark-1 is running: `curl http://192.168.0.104:11434/api/tags`
- Check `WORKER_IP` and `LLM_MODEL` in `.env`
- Increase `API_TIMEOUT` if timeouts occur

**Database connection errors:**
- Verify database credentials in `.env`
- Check database is running and accessible
- Ensure user has UPDATE permissions

## Integration

The backfill agent can be integrated with:

- **Cron jobs**: Schedule regular backfills
- **CI/CD pipelines**: Run after schema migrations
- **Manual workflows**: Run on-demand when needed

Example cron job (daily at 2 AM):
```bash
0 2 * * * cd /path/to/fortress-prime && python src/backfill_enrichment.py >> /var/log/backfill.log 2>&1
```
