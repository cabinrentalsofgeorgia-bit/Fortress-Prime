# 🛡️ FORTRESS PRIME - Data Enrichment System

## Overview

The enrichment system automatically extracts structured data from unstructured content using LLM analysis. When new records are inserted into `market_intel` or `legal_intel`, the system automatically enriches them with:

- **Market Intel**: Ticker symbol and asset class (STOCK, CRYPTO, BOND, etc.)
- **Legal Intel**: Priority level (CRITICAL, HIGH, MEDIUM, LOW) and next deadline date

## Architecture

### Components

1. **Enrichment Service** (`src/enrichment_service.py`)
   - LLM-powered extraction functions
   - `enrich_market_intel(record_id)` - Extracts ticker and asset_class
   - `enrich_legal_intel(record_id)` - Extracts priority and next_deadline

2. **Enrichment Processor** (`src/enrichment_processor.py`)
   - Continuous background processor
   - Processes pending enrichments in batches
   - Can run as a standalone service

3. **Data Router** (`src/data_router.py`)
   - Automatically triggers enrichment on insert
   - Integrated with routing logic

## Automatic Triggering Options

### Option 1: Immediate Enrichment (Default)

The data router automatically triggers enrichment immediately after inserting new records:

```python
from data_router import route_incoming_data

email_data = {
    'sender': 'trader@broker.com',
    'subject': 'Trade Confirmation',
    'content': 'You bought 100 shares of NVDA at $500.00',
    'date': datetime.now().date()
}

result = route_incoming_data(email_data, source_email_id=123)
# Enrichment happens automatically in the background
```

### Option 2: Background Processor (Recommended for High Volume)

Run the continuous enrichment processor as a separate service:

```bash
# Run as background service
python src/enrichment_processor.py

# Or run in background
nohup python src/enrichment_processor.py > enrichment.log 2>&1 &
```

This checks every 30 seconds for new records and processes them in batches.

### Option 3: Manual Batch Processing

Process pending enrichments on-demand:

```python
from enrichment_service import process_pending_enrichments

# Process up to 10 pending records
stats = process_pending_enrichments(batch_size=10)
print(f"Processed: {stats['market_processed']} market, {stats['legal_processed']} legal")
```

### Option 4: Database Triggers (Advanced)

You can also set up PostgreSQL triggers to call enrichment functions automatically. See `docs/DATABASE_TRIGGERS.md` for details.

## Configuration

Environment variables (`.env`):

```bash
# Enrichment processor settings
ENRICHMENT_INTERVAL=30        # Check every 30 seconds
ENRICHMENT_BATCH_SIZE=10      # Process 10 records per batch

# Spark-1 LLM endpoint
WORKER_IP=192.168.0.104
```

## Usage Examples

### Enrich a Single Record

```python
from enrichment_service import enrich_market_intel, enrich_legal_intel

# Enrich market intel
result = enrich_market_intel(record_id=42)
if result['success']:
    print(f"Ticker: {result['ticker']}, Asset Class: {result['asset_class']}")

# Enrich legal intel
result = enrich_legal_intel(record_id=43)
if result['success']:
    print(f"Priority: {result['priority']}, Deadline: {result['next_deadline']}")
```

### Process All Pending

```python
from enrichment_processor import continuous_enrichment_loop

# Run continuous loop (Ctrl+C to stop)
continuous_enrichment_loop()
```

## Database Schema

### Market Intel

```sql
ALTER TABLE market_intel 
ADD COLUMN ticker VARCHAR(10),
ADD COLUMN asset_class VARCHAR(50),
ADD COLUMN enriched_at TIMESTAMP;
```

**Asset Classes**: STOCK, CRYPTO, BOND, COMMODITY, FOREX, OPTION, OTHER

### Legal Intel

```sql
ALTER TABLE legal_intel 
ADD COLUMN priority VARCHAR(50),
ADD COLUMN next_deadline DATE,
ADD COLUMN enriched_at TIMESTAMP;
```

**Priorities**: CRITICAL, HIGH, MEDIUM, LOW, ARCHIVE

## Monitoring

Check enrichment status:

```python
from enrichment_processor import get_unenriched_count

counts = get_unenriched_count()
print(f"Pending: {counts['market']} market, {counts['legal']} legal")
```

## Error Handling

- Enrichment failures are logged but don't block record insertion
- Failed enrichments can be retried by running the processor
- Records with `enriched_at = NULL` are candidates for retry

## Performance

- LLM API calls: ~2-5 seconds per record
- Batch processing: 10 records every 30 seconds = ~300 records/hour
- For higher throughput, increase `ENRICHMENT_BATCH_SIZE` or run multiple processors

## Troubleshooting

**Enrichment not triggering:**
- Check Spark-1 connectivity: `curl http://192.168.0.104:11434/api/tags`
- Verify LLM model is loaded: `mistral:latest`
- Check logs for API errors

**Records not enriching:**
- Verify `content` column is not NULL
- Check for API timeouts (increase `API_TIMEOUT` if needed)
- Run processor manually to see detailed error messages
