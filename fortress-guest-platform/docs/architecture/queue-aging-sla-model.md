# Fortress Legal Queue Aging and SLA Model

Status: SLA_VISIBILITY_ACTIVE_FOR_REVIEW_ATTENTION

## Purpose

The SLA model helps reviewers prioritize attention. It is not a legal deadline system, filing calendar, or counsel-signoff system.

## SLA Bands

- critical_24h: review owner should be assigned within 24 hours.
- high_48h: queue manager should review within 48 hours.
- standard_5d: review triage within 5 business days.
- low_10d: review when capacity is available.

## Baseline Age Source

Current age/staleness is a baseline backlog marker derived from existing manifests. It does not create or mutate queue timestamps.

## Escalation States

- escalate_if_unassigned
- queue_manager_review
- standard_queue
- watchlist

## Boundaries

SLA labels may not:

- create legal deadlines
- create filing/service/email authority
- create final legal advice
- alter evidence lineage
- unlock restricted content
- auto-resolve source issues

## Incident Interaction

Any SLA item involving auth, public exposure, restricted-content boundaries, schema/RLS mutation, auto-signoff, final legal conclusions, or external submission must trigger incident review rather than queue acceleration.
