-- Vendor Classifications from TITAN Audit
-- Generated: 2026-02-14 07:42:01
-- Total vendors: 1

BEGIN;

-- Brian Woolever <brian.woolever: UNKNOWN (0% confidence)
INSERT INTO finance.vendor_classifications (vendor_pattern, vendor_label, classification, is_revenue, is_expense, titan_notes)
VALUES ('Brian Woolever <brian.woolever', 'Brian Woolever <brian.woolever', 'UNKNOWN', False, False, 'Error during classification: substring not found | Confidence: 0% | Division: UNKNOWN | Subcategory: error')
ON CONFLICT (vendor_pattern) DO UPDATE SET
  classification = EXCLUDED.classification,
  is_revenue = EXCLUDED.is_revenue,
  is_expense = EXCLUDED.is_expense,
  titan_notes = EXCLUDED.titan_notes,
  classified_at = NOW();

COMMIT;
