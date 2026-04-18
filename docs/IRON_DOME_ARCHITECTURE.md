# Iron Dome — Fortress-Prime Sovereign AI Defense System

**Version:** 2.0
**Date:** April 18, 2026
**Author:** Gary Knight (with Claude)
**Supersedes:** v1 (commit 1b1b8231e)

## What Iron Dome defends against

Fortress-Prime is a four-business operator (CROG-VRS, Fortress Legal, Master Accounting, acquisitions) with a single operator. The operator's edge is speed of decision, depth of analysis, and cost discipline.

Iron Dome is the AI infrastructure that preserves all three against four specific threats:

Threat 1: Frontier vendor lock-in. When every legal deliberation, every tenant communication, every acquisition analysis runs against Anthropic/OpenAI APIs, the operator's cost structure tracks their price increases and their availability.

Threat 2: Privileged data leakage. Fortress Legal deliberates on active litigation. If that deliberation flows to a third-party model vendor, the privilege argument is materially weakened. If it flows to a training corpus, the privilege is destroyed.

Threat 3: Compute economics that stop scaling. Solo operator means every billed API call is a tax on margin.

Threat 4: Model quality degradation over time. Vendor model changes (silent updates, deprecations, alignment drift) change the operator's decision-quality baseline without notice.

Iron Dome's answer: run frontier-quality inference locally on owned infrastructure, with a distillation flywheel that improves local models from frontier teacher signals, behind a privilege filter that keeps sensitive work inside the perimeter.

## Where we are (April 18, 2026 post-deploy)

Live in production under tag salvage-complete-20260417 plus Round 2 hotfixes:
- ai_router._capture_interaction (fire-and-forget teacher capture)
- shadow_router at /api/v1/shadow
- godhead_swarm tier-routing scaffold
- nightly_distillation_exporter (not yet enabled)
- recursive_agent_loop worker (gated off)
- legal_council persona writes to llm_training_captures (UNFILTERED)
- get_ollama_endpoints helper
- Owner-ledger module suite (PRs #44, #45)

Live DB state: alembic at head. llm_training_captures auto-created on first exporter run.

## The five phases

Phase 1 — Plumbing deployed (DONE, April 18). All 7 services on new code, /health green, legal_council works, ai_router fires cleanly.

Phase 2 — Privilege filter (THIS SESSION). Prevent privileged legal material from entering llm_training_captures. Filter at capture write site. Default route for legal personas and modules: RESTRICTED. Exit: zero legal_council outputs in llm_training_captures.

Phase 3 — Flywheel activation. After Phase 2: bootstrap tables, run first exporter pass, verify zero privileged content in JSONL, enable nightly timer.

Phase 4 — Distillation fine-tune loop. systemd units exist. Trainer script, eval harness, promotion criteria, rollback logic all pending.

Phase 5 — Multi-node service discovery and failover across spark cluster. Lower priority.

## Seven operational principles

1. Never rebase a branch with substantial uncommitted work.
2. Avoid parallel background shells that modify git state.
3. Triage memory is unreliable after four hours — re-audit before commit.
4. Confirm file paths with find before writing them into prompts.
5. SSH drops are part of the operating environment — operations over a minute must survive session loss.
6. Deployments and key rotations are separate operations.
7. Every hardcoded default is a future rotation obligation. Use env-var-or-RuntimeError. Fail loudly in production.

## Risks still live

R1: sk-fortress-master-123 in git history on pre-PR-#37 commits. Actual live key differs; rotation scheduled post-deploy stabilization.

R2: Live LITELLM_MASTER_KEY in gitignored root litellm_config.yaml on disk. Migrate to env var + systemd drop-in during rotation.

R3: miner_bot Postgres password in git history on pre-PR-#39 commits. Rotation needed.

R4: Pre-existing event_consumer NameError unmasked by restart. Not a deploy regression. Tracked.

R5: Unbounded training capture surface. Phase 2 addresses legal_council. ediscovery_agent, owner portal comms, damage-claim workflows, reservation webhooks also need filter coverage. Filter must apply at capture layer globally.

## Moat

Most cabin-rental operators and most litigators do not have a 4-node Spark cluster with 100Gbps interconnect. Duplicating this infrastructure is substantial cost.

Every frontier inference call is one call of training signal for the sovereign tier. Over time the distilled tier handles progressively more of the workload. The operator's AI cost curve trends flat (hardware + electricity); competitor cost curves track vendor price sheets.

The moat deepens with time. Not replicable on commodity laptops or consumer SaaS plans.
