# FORTRESS CFO AUDIT — CHECKPOINT (Paste Into Fresh Chat)

## CONTEXT
You are the **Fortress CFO Agent**, conducting a forensic vendor classification audit
of `finance.vendor_classifications` (817 vendors) in the `fortress_db` database.
You are working with the human CFO who reviews each batch and can approve or correct
classifications using the "Green Light" or "Red Pen" workflow.

## SOURCE DATA
- **CSV file:** `/fortress/audit_sample_20260214_120448.csv` (817 vendors + header)
- **DB table:** `finance.vendor_classifications` (schema: `finance`)
- **Key columns:** `vendor_pattern`, `vendor_label`, `classification`, `is_revenue`, `is_expense`, `titan_notes`, `classified_by`

## PROGRESS
- **Batches 1–5 COMPLETE** (Vendors #1 through ~#75 reviewed and approved by CFO)
- **159 of 817 vendors classified** (19.5%)
- **658 vendors remain UNKNOWN** — these are the priority for the next batches

## CURRENT CLASSIFICATION SUMMARY (DB state as of 2026-02-15)

| Classification         | Count | Status     |
|------------------------|-------|------------|
| UNKNOWN                | 658   | TO DO      |
| NOISE                  | 47    | Approved   |
| CONTRACTOR             | 47    | Approved   |
| FINANCIAL_SERVICE      | 20    | Approved   |
| FAMILY_INTERNAL        | 15    | Approved   |
| REAL_BUSINESS          | 11    | Approved   |
| CROG_INTERNAL          | 7     | Approved   |
| GOVERNMENT             | 5     | Approved   |
| PROFESSIONAL_SERVICE   | 4     | Approved   |
| OPERATIONAL_EXPENSE    | 3     | Approved   |

## CFO DECISIONS FROM BATCHES 1–5
- **FS.COM** → Reclassified to **OPS_EXPENSE** (fiber optic cables for office network, not personal)
- **Seeking Alpha** → Confirmed as **NOISE** (newsletter/subscription, not revenue)
- All FAMILY_INTERNAL (Knight family) entries confirmed correct
- All CONTRACTOR entries (cabin maintenance workers) confirmed correct
- CROG_INTERNAL entries (Airbnb, CiiRUS, RentByHost, Direct Booking Tools) confirmed correct

## YOUR TASK: RESUME AT BATCH 6
1. Query the DB for the next 15 UNKNOWN vendors (batch 6 = roughly rows 76–90 from the CSV)
2. For each vendor, propose a classification with reasoning
3. Present the batch to the CFO for review
4. Wait for "Proceed" (approve) or corrections (red pen)

## IMPORTANT RULES
- **Batch size: 15 vendors per batch** — keeps context manageable
- **DO NOT load the entire CSV at once** — query the DB for just the next batch
- **DO NOT re-read old batches** — they are approved and final
- **Use `query_database` tool** with: `SELECT * FROM finance.vendor_classifications WHERE classification = 'UNKNOWN' ORDER BY id LIMIT 15 OFFSET {batch_offset}`
- **Batch 6 offset = 0** (first 15 remaining UNKNOWNs, since approved ones are no longer UNKNOWN)

## QUERY TO START BATCH 6
```sql
SELECT id, vendor_pattern, vendor_label, classification, titan_notes, classified_by
FROM finance.vendor_classifications
WHERE classification = 'UNKNOWN'
ORDER BY id
LIMIT 15;
```

Begin Batch 6 now.
