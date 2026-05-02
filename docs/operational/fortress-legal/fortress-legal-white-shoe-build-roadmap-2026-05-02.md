# Fortress Legal White-Shoe Build Roadmap

Date: 2026-05-02
Purpose: Convert Fortress Legal from a strong legal document system into a top-tier matter control platform.

## 1. Operating Principle

A top law firm does not win because it has documents. It wins because it controls deadlines, facts, issue framing, evidence, privilege, staffing, economics, and decision history. Fortress Legal should make those controls visible and repeatable for every matter.

## 2. Build Pillars

### Pillar A - Matter Command Center

One screen per matter:

- Service status
- Next deadline
- Filing posture
- Counsel status
- Evidence status
- Financial exposure
- Issue risk heatmap
- Open operator decisions
- Today's highest-value move

### Pillar B - Docket and Service Sentinel

- Daily docket watch
- Service event detection
- Waiver request detection
- Deadline recomputation
- Alert ladder: 21 days, 14 days, 7 days, 72 hours, 24 hours
- Proof-of-service archive

### Pillar C - First-Response Builder

- Allegation-by-allegation response matrix
- Affirmative defense workbench
- Rule 12 issue screen
- Counterclaim hook mapping
- Filing-ready answer generator
- Counsel redline export

### Pillar D - Issue Matrix

Each issue gets:

- Legal standard
- Facts supporting
- Facts against
- Evidence links
- Authority links
- Risk rating
- Next action
- Filing usage

### Pillar E - Evidence-to-Pleading Traceability

- Every factual assertion ties to evidence
- Every evidence item ties to case_slug, source path, status, privilege class
- Every generated filing gets a trace report
- No trace, no filing

### Pillar F - Privilege Firewall

Classes:

- Public filing
- Produced evidence
- Internal factual work product
- Privileged counsel communication
- Operator strategy
- Settlement/economic analysis

Rules:

- Privileged strategy never enters public filing drafts unless deliberately converted.
- Counsel packets are sanitized after conflict clearance.
- Retrieval and generation must respect privilege class.

### Pillar G - Counsel Packet Mode

Outputs:

- Conflict-check email
- Attorney briefing package
- Evidence index
- Draft answer matrix
- Fee-scope request
- Call script
- Counsel scorecard
- Post-call summary

### Pillar H - Red-Team Review

Before any filing/package:

- Opposing-party attack memo
- Judge-risk memo
- Waiver-risk memo
- Evidence-gap memo
- Privilege-leak scan
- Tone/professionalism scan

### Pillar I - Decision Log

Every key decision logs:

- Date
- Decision
- Options considered
- Reason
- Risk accepted
- Evidence relied on
- Next review trigger

### Pillar J - Retrieval Health and Corpus Integrity

- Collection counts by case_slug
- Alias target verification
- Vector dimension verification
- Legacy-path exclusion checks
- Retry health checks
- Regression tests for key queries

## 3. First Three Product Sprints

Sprint 1 - Case II matter control:

- Build matter command center document/schema.
- Build answer matrix from complaint.
- Build counsel tracker from conflict-check responses.
- Build service/deadline log.

Sprint 2 - Filing readiness:

- Generate answer draft from matrix.
- Generate Rule 12 issue memo.
- Generate counterclaim viability memo.
- Run red-team review.

Sprint 3 - Platform hardening:

- Add privilege classes to artifacts.
- Add evidence trace report.
- Add Qdrant collection/alias health report.
- Add retrieval regression pack for Case I and Case II.

## 4. Excellence Standard

Fortress Legal is excellent when an operator can answer these questions in under two minutes:

- What is the next deadline?
- What is the current service posture?
- What must be filed next?
- What facts support each filing paragraph?
- What evidence is privileged?
- Which counsel cleared conflicts?
- What is the economic decision point?
- What is the biggest legal risk?
- What is today's highest-value move?

If the system cannot answer those questions, the build is not yet white-shoe grade.
