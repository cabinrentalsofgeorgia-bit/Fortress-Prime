#!/bin/bash
cd /home/admin/Fortress-Prime

# Load required environment variables securely
export QDRANT_HOST="127.0.0.1" 
export QDRANT_URL="http://127.0.0.1:6333"
export $(grep -E '^(FRED_API_KEY|QDRANT_API_KEY|DB_)' .env | xargs)

echo "========================================"
echo "Fortress Intelligence Update: $(date)"
echo "========================================"

/usr/bin/python3 src/ingest_macro_data.py
/usr/bin/python3 src/ingest_real_estate_data.py
/usr/bin/python3 src/ingest_black_swan_data.py

echo "Update Complete."
