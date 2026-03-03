# Fortune-500 Remediation Control Framework

## Purpose
Define enterprise-grade change control, severity handling, rollback discipline, and evidence requirements for all remediation phases.

## Change Windows
- **Standard window:** 09:00-17:00 local, Mon-Fri.
- **High-risk window:** Requires explicit approval and live rollback operator.
- **Emergency window:** Incident commander approval with post-incident review required.

## Severity Model and SLA
- **Critical:** Security/data-loss/service outage risk. Mitigate or rollback within 4 hours.
- **High:** Major reliability/compliance risk. Mitigate within 24 hours.
- **Medium:** Non-blocking process/control gaps. Mitigate within 5 business days.
- **Low:** Hygiene/documentation improvements. Mitigate within 20 business days.

## Required Evidence Per Change
- Change objective and impacted systems.
- Pre-change snapshot (`git status`, service status, backups if applicable).
- Verification outputs (tests, health checks, runtime validation).
- Rollback command and rollback validation output.
- Residual risk statement.

## Rollback Standard
- Every change includes:
  - forward execution command(s),
  - rollback command(s),
  - verification command(s) for both forward and rollback.
- If verification fails, rollback is mandatory before proceeding.

## Phase Gates
- Gate checks are mandatory and blocking.
- No phase transition without:
  - objective evidence archived,
  - owner approval,
  - unresolved Critical findings reduced to zero or explicitly accepted by owner.

## Incident Escalation Matrix
- **Owner:** Program lead.
- **Technical commander:** Infrastructure lead.
- **Security commander:** Security/compliance lead.
- **Communications:** Business owner.

## Accepted Risk Register Policy
- Accepted risks must include:
  - unique risk ID,
  - owner,
  - expiration/review date,
  - monitoring controls,
  - explicit acceptance note.
