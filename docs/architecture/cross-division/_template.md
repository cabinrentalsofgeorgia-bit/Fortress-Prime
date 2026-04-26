# Cross-Division Flow: <Name>

Last updated: <YYYY-MM-DD>

## Summary

One paragraph. What flow is this? Which divisions does it span? What is the shape of the data moving between them?

## Path

```
[Source Division]  ──>  [Shared Service]  ──>  [Target Division]
        │                    │                       │
        │                    └── transformation ───>│
        │                                            │
        └── audit / log ─────────────────────────>  legal.ingest_runs
                                                    or equivalent
```

## Trigger

When does this flow execute? Operator command, cron, webhook, message?

## Steps

1. Source division emits event / writes record / sends API call
2. Shared service classifies / routes / transforms
3. Target division receives + persists
4. Audit trail written

## Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| Source unavailable | logs + alerting | retry queue |
| Classifier ambiguous | `case_slug = NULL` | quarantine queue |
| Target write fails | `processing_status = 'failed'` | re-run script |

## Authoritative source-of-truth

Which doc/schema/code path is the canonical reference for this flow?

## Cross-references

- Source division: `../divisions/<name>.md`
- Shared service: `../shared/<name>.md`
- Target division: `../divisions/<name>.md`
- Code: `<path/to/file.py>`
- Runbook: `../../runbooks/<name>.md`
