# Labeling QC Workflow

Phase 4e.1 — Gary's psql-based review interface for Godhead labels.

## Overview

Every capture automatically receives a Godhead judgment (confident/uncertain/escalate).
A sample of these judgments land in the QC queue for human review. You review via
direct psql queries. No UI required.

## Connecting

```bash
psql "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"
```

## Daily QC workflow

### Step 1: Check the queue

```sql
SELECT id, task_type, godhead_decision, godhead_reasoning,
       LEFT(user_prompt, 120) AS prompt_preview,
       LEFT(assistant_resp, 120) AS response_preview
FROM v_qc_queue
LIMIT 10;
```

### Step 2: Review and confirm or override

**Confirm (Godhead was right):**
```sql
UPDATE capture_labels
SET qc_decision   = 'confirm',
    qc_note       = 'Agreed. Response was accurate.',
    qc_reviewed_at = NOW(),
    label_source   = 'godhead'
WHERE id = '<label-uuid>';
```

**Override to escalate (Godhead said confident but response was bad):**
```sql
UPDATE capture_labels
SET qc_decision   = 'override_escalate',
    qc_note       = 'Response hallucinated a statute. Should have escalated.',
    qc_reviewed_at = NOW(),
    final_decision = 'escalate',
    label_source   = 'gary_qc'
WHERE id = '<label-uuid>';
```

**Override to confident (Godhead was too cautious):**
```sql
UPDATE capture_labels
SET qc_decision   = 'override_confident',
    qc_note       = 'Response was fine. Godhead over-flagged.',
    qc_reviewed_at = NOW(),
    final_decision = 'confident',
    label_source   = 'gary_qc'
WHERE id = '<label-uuid>';
```

### Step 3: Check daily stats

```sql
SELECT label_date, task_type, total_labeled,
       confident_count, uncertain_count, escalate_count,
       ROUND(total_cost_usd, 4) AS cost_usd,
       qc_sampled_count, qc_reviewed_count
FROM v_labeling_stats
WHERE label_date >= CURRENT_DATE - 7
ORDER BY label_date DESC, total_labeled DESC;
```

## Budget check

```bash
# From shell
cd ~/Fortress-Prime/fortress-guest-platform
.uv-venv/bin/python -m backend.services.labeling_pipeline --mode=status
```

Or in psql:
```sql
SELECT COALESCE(SUM(godhead_cost_usd), 0) AS spent_today,
       20.00 - COALESCE(SUM(godhead_cost_usd), 0) AS remaining
FROM capture_labels
WHERE godhead_called_at >= CURRENT_DATE;
```

## QC sampling rates (by task type)

| Task type | Sample rate | Rationale |
|-----------|-------------|-----------|
| legal_reasoning | 100% | Privilege risk; every label reviewed |
| brief_drafting | 100% | High stakes; attorney work |
| legal_citations | 100% | Citation accuracy is binary |
| contract_analysis | 100% | Legal and financial risk |
| pricing_math | 50% | Math errors have revenue impact |
| acquisitions | 50% | Strategic decisions |
| market_research | 25% | Moderate risk |
| code_* | 15% | Correctness verifiable by tests |
| vision_* | 10% | Lower legal risk |
| real_time | 10% | Currency hard to verify without tools |
| vrs_concierge | 5% | High volume, lower per-error cost |
| vrs_ota_response | 5% | High volume, well-templated |

## Finding patterns in Godhead errors

```sql
-- Which task types have highest override rate?
SELECT task_type,
       COUNT(*) FILTER (WHERE label_source = 'gary_qc') AS overrides,
       COUNT(*) AS reviewed,
       ROUND(100.0 * COUNT(*) FILTER (WHERE label_source='gary_qc') / COUNT(*), 1) AS override_pct
FROM capture_labels
WHERE qc_reviewed_at IS NOT NULL
GROUP BY task_type
ORDER BY override_pct DESC;

-- Show all overrides this week for retraining signal
SELECT id, task_type, godhead_decision, qc_decision, qc_note,
       LEFT(user_prompt, 200) AS prompt
FROM capture_labels
WHERE label_source = 'gary_qc'
  AND qc_reviewed_at >= CURRENT_DATE - 7
ORDER BY qc_reviewed_at DESC;
```
