# Fortress Legal Review Throughput Instrumentation Model

Status: READ_ONLY_THROUGHPUT_INSTRUMENTATION_ACTIVE

## Purpose

Measure controlled internal review operations without exposing legal content or mutating evidence state.

## Metrics

- queue depth
- queue aging/SLA distribution
- review traversal count
- remediation triage count
- contradiction review count
- evidence navigation count
- reviewer handoff count
- escalation count
- unresolved-source count
- excluded-source count
- confidence distribution
- completion readiness

## Measurement Method

Metrics are derived from existing review-operation metadata:

- remediation review queue
- contradiction review queue
- evidence navigation queue
- escalation review queue
- reviewer operations model
- operational certification model

## Safety Controls

- no document body text in metrics
- no locked/restricted content
- no confidential legal text
- no persistent reviewer assignment writes
- no source resolution status changes
- no signoff/final/external authority

## Checker Assertions

The authenticated checker must confirm internal pilot visibility and continue confirming review operations, review scaling, operational certification, signoff-pending, no external authority, and no final legal advice.
