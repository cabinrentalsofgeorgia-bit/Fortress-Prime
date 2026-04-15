# Fortress Guest Platform — Documentation Index

Central index for technical documentation under `docs/`.

## Architecture

| Document | Description |
|----------|-------------|
| [Sovereign Ledger Immutability (ADR)](architecture/sovereign_ledger_immutability.md) | Phase 7: Postgres immutability triggers, SHA-256 hash chain, webhooks, Hermes auditor, NeMo Command Center. |

## Operations & database

| Document | Description |
|----------|-------------|
| [Alembic reconciliation plan](alembic-reconciliation-plan.md) | Plan for aligning migrations and schema. |
| [Alembic reconciliation report](alembic-reconciliation-report.md) | Report output from reconciliation work. |
| [Alembic prod rollout runbook](alembic-prod-rollout-runbook.md) | Production rollout steps for migrations. |

## Security & access

| Document | Description |
|----------|-------------|
| [API surface auth classification](api-surface-auth-classification.md) | How API routes are classified for authentication. |
| [Permission matrix](permission-matrix.md) | Role and permission reference. |
| [Privileged surface checklist](privileged-surface-checklist.md) | Hardening checklist for privileged endpoints. |

## Product & integrations

| Document | Description |
|----------|-------------|
| [Streamline trust webhook](streamline-trust-webhook.md) | Inbound Streamline webhook auth, vault, optional variance posting. |
| [Storefront homepage cutover checklist](storefront-homepage-cutover-checklist.md) | Cutover tasks for the storefront homepage. |

---

For repo-wide AI and architecture rules, see the root [`.cursorrules`](../.cursorrules).
