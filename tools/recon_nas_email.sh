#!/bin/bash
# Recon: locate email cold storage on NAS for the Feeder
# Run on Captain. Outputs paths the Feeder can target (PST and/or EML).

set -e
NAS="${NAS_ROOT:-/mnt/fortress_nas}"
VOL1="${VOL1_SOURCE:-/mnt/vol1_source}"
TIMEOUT_PST="${PST_FIND_TIMEOUT:-20}"

echo "=============================================="
echo "  RECON: Email cold storage on NAS"
echo "=============================================="
echo "  NAS root:    $NAS"
echo "  Vol1 source: $VOL1"
echo "=============================================="
echo ""

# --- 1. EML (MailPlus Data Lake) ---
GMAIL_ARCHIVE="$NAS/Communications/System_MailPlus_Server/ENTERPRISE_DATA_LAKE/01_LANDING_ZONE/GMAIL_ARCHIVE"
RAW_DUMP="$NAS/Communications/System_MailPlus_Server/ENTERPRISE_DATA_LAKE/01_LANDING_ZONE/RAW_EMAIL_DUMP"

echo "--- 1. EML (MailPlus / Gmail archive) ---"
if [ -d "$GMAIL_ARCHIVE" ]; then
  eml_count=$(find "$GMAIL_ARCHIVE" -maxdepth 2 -name "*.eml" -type f 2>/dev/null | wc -l)
  eml_size=$(du -sh "$GMAIL_ARCHIVE" 2>/dev/null | cut -f1)
  echo "  Path:  $GMAIL_ARCHIVE"
  echo "  Count: $eml_count .eml files (sample)"
  echo "  Size:  $eml_size"
  echo "  -> Feeder target: point ingest at this path to flood email_archive with EML."
else
  echo "  Path not found: $GMAIL_ARCHIVE"
fi

if [ -d "$RAW_DUMP" ]; then
  raw_count=$(find "$RAW_DUMP" -maxdepth 2 -type f 2>/dev/null | wc -l)
  echo "  RAW_EMAIL_DUMP: $raw_count files (sample)"
fi
echo ""

# --- 2. PST (optional, can be slow) ---
echo "--- 2. PST (Outlook archives) ---"
for root in "$NAS" "$VOL1"; do
  if [ ! -d "$root" ]; then continue; fi
  echo "  Searching $root (timeout ${TIMEOUT_PST}s)..."
  pst_list=$(timeout "$TIMEOUT_PST" find "$root" -maxdepth 8 -name "*.pst" -type f 2>/dev/null | head -50)
  pst_count=$(echo "$pst_list" | grep -c . 2>/dev/null || echo 0)
  if [ "$pst_count" -gt 0 ]; then
    echo "  Found $pst_count .pst under $root (max 50 shown):"
    echo "$pst_list" | head -20 | sed 's/^/    /'
  else
    echo "  No .pst found in top 8 levels."
  fi
done
echo ""

# --- 3. Summary ---
echo "=============================================="
echo "  FEEDER TARGET (recommended)"
echo "=============================================="
echo "  EML (ready now):"
echo "    $GMAIL_ARCHIVE"
echo "  -> Use an EML ingester (e.g. read .eml, insert into email_archive)."
echo ""
echo "  PST: If recon found .pst above, point ingest_pst.py at that directory."
echo "  If no PST on NAS, the 'motherlode' is the EML archive (7k+ messages)."
echo "=============================================="
