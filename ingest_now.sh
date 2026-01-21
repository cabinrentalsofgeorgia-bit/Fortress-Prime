#!/bin/bash
echo "🛡️  FORTRESS PRIME: INGESTION PROTOCOL INITIATED"
echo "------------------------------------------------"
echo "📂 Scanning Legal & Business Vaults for NEW files..."

# Run the python indexer
/home/admin/miniforge3/bin/python /home/admin/fortress-prime/src/indexer_service.py

echo "------------------------------------------------"
echo "✅ Protocol Complete. Dashboard Updated."
