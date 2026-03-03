#!/bin/bash
# Check if fortress_docs Enterprise War Room crawl is complete.
# Usage: ./bin/check_ingest_done.sh
# Or: watch -n 60 ./bin/check_ingest_done.sh  # poll every minute

if pgrep -f "rag_ingest.*Enterprise_War_Room" > /dev/null 2>&1; then
    echo "CRAWL RUNNING — $(date +%H:%M:%S)"
    tail -1 /tmp/doc_ingest.log 2>/dev/null | head -c 120
    echo ""
    python3 -c "
import sqlite3
conn = sqlite3.connect('/home/admin/fortress_fast/chroma_db/chroma.sqlite3')
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM embeddings e JOIN segments s ON e.segment_id = s.id JOIN collections c ON s.collection = c.id WHERE c.name = 'fortress_docs'\")
print(f'fortress_docs: {cur.fetchone()[0]} vectors')
conn.close()
" 2>/dev/null
    exit 1
fi

echo "CRAWL COMPLETE — $(date)"
echo ""
tail -15 /tmp/doc_ingest.log 2>/dev/null
echo ""
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/admin/fortress_fast/chroma_db/chroma.sqlite3')
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM embeddings e JOIN segments s ON e.segment_id = s.id JOIN collections c ON s.collection = c.id WHERE c.name = 'fortress_docs'\")
print(f'fortress_docs FINAL: {cur.fetchone()[0]} vectors')
conn.close()
" 2>/dev/null
exit 0
