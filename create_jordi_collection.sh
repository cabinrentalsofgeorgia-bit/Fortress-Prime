#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# Create Qdrant jordi_intel Collection
# ═══════════════════════════════════════════════════════════════════════════

set -e

QDRANT_URL="http://localhost:6333"
QDRANT_API_KEY="ba9bea29e2db1d31025171ffb33d74f151987bdb2fa6760beaa54ab28c23ff5d"
COLLECTION="jordi_intel"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 Creating Qdrant Collection: $COLLECTION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if collection already exists
echo "Checking if collection exists..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "$QDRANT_URL/collections/$COLLECTION" \
  -H "api-key: $QDRANT_API_KEY")

if [ "$STATUS" == "200" ]; then
    echo "✅ Collection '$COLLECTION' already exists"
    
    # Get stats
    curl -s "$QDRANT_URL/collections/$COLLECTION" \
      -H "api-key: $QDRANT_API_KEY" | \
      python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"   Vectors: {data['result']['vectors_count']:,}\"); print(f\"   Points: {data['result']['points_count']:,}\")"
    
    echo ""
    echo "ℹ️  To recreate, first delete:"
    echo "   curl -X DELETE $QDRANT_URL/collections/$COLLECTION -H 'api-key: $QDRANT_API_KEY'"
    exit 0
fi

# Create collection
echo "Creating collection with nomic-embed-text config (768-dim)..."

RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT \
  "$QDRANT_URL/collections/$COLLECTION" \
  -H "api-key: $QDRANT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {
      "size": 768,
      "distance": "Cosine"
    }
  }')

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" == "200" ] || [ "$HTTP_CODE" == "201" ]; then
    echo "✅ Collection created successfully!"
    echo ""
    echo "Collection Details:"
    echo "$BODY" | python3 -c "import sys, json; data=json.load(sys.stdin); print(json.dumps(data, indent=2))" 2>/dev/null || echo "$BODY"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Ready to ingest Jordi Visser content!"
    echo ""
    echo "Next steps:"
    echo "  1. Gather content: ./bin/hunt-jordi --once"
    echo "  2. Ingest: python3 src/ingest_jordi_knowledge.py"
    echo "  3. Query: ./bin/sovereign jordi \"Bitcoin thesis\""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "❌ Failed to create collection (HTTP $HTTP_CODE)"
    echo ""
    echo "Response:"
    echo "$BODY"
    exit 1
fi
