# Claude Code Kickoff — Wave 3 Brief Amendment (doc-only)

**Target:** Claude Code on spark-2
**Driver:** Wave 2 fully ratified on main (PR #340 merged at f65c5f304). The Wave 3 retrieval-stack brief (`docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md`) was written 2026-04-30 — pre-Wave-2-ratification. Multiple presumptions in the original brief are now stale. This kickoff amends the brief to reconcile against current reality. Doc-only PR. No deployment work.

**Authoritative deep research:**
- `docs/research/nemotron-3-super-deep-research-2026-04-30.md` (carry-forward schema discipline)

**Note:** Embed deep-research recovery deferred — regenerate from Wave 1 EMBED ratification work, separate ticket per PR #341 commit message.

**Sequence position:** This PR is the prerequisite to Wave 3 deploy execution. After this brief amendment merges, a separate execution kickoff opens against the now-on-main amended brief.

---

## Mission

Five sequential gates. Halt on any failure. Surface inline before progressing.

1. **Pre-flight inspection** — capture current state of all stale-presumption surfaces (EMBED status, Vision status, BRAIN retirement status, frontier health, spark-5 GPU state, brief content).
2. **Reconciliation matrix** — walk the original brief against current state. Identify which sections need amendment, which are correct as-is, which are out of scope.
3. **Apply amendment** — edit `docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md` per the matrix. Add §0 reconciliation block (pattern from PR #337 Wave 2 brief). Preserve historical execution plan with `[Status:]` callouts.
4. **Surface diff** — operator review gate before commit.
5. **Commit + PR** — single-file doc-only PR, halt for operator review.

This is reconcile-then-document, NOT deploy-then-document. Wave 3 execution is a separate kickoff after this PR merges.

---

## Standing rules apply

Never `--admin`, never `--force` (force-with-lease only), never self-merge, never force-push main. Branches from `origin/main` only. Single Claude Code session.

```bash
cd /home/admin/Fortress-Prime
git fetch origin
git status
git log --oneline origin/main..HEAD
```

Confirm: clean working tree on or near main. `origin/main` HEAD = `f65c5f304` (PR #340 merge).

---

## Step 1 — Pre-flight inspection (read-only)

### 1.1 Branch from origin/main

```bash
git checkout origin/main
git checkout -b docs/wave-3-brief-amendment-2026-05-01
git status
```

### 1.2 Capture original brief content

```bash
ssh admin@192.168.0.100 'wc -l /home/admin/Fortress-Prime/docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md'
ssh admin@192.168.0.100 'head -60 /home/admin/Fortress-Prime/docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md'
```

Surface inline. Confirm the brief is on main (was committed when merged, not still untracked).

### 1.3 Capture EMBED current state on spark-3

```bash
ssh admin@192.168.0.105 'sudo systemctl is-active fortress-nim-embed.service 2>&1; sudo systemctl is-enabled fortress-nim-embed.service 2>&1'
ssh admin@192.168.0.105 'docker ps --filter name=fortress-nim-embed --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'
ssh admin@192.168.0.105 'curl -fsS --max-time 5 http://localhost:8102/v1/health/ready -w "\n%{http_code}\n" 2>&1'
```

Expected (per PR #336 Wave 1 close): EMBED active, healthy, port 8102. If different, surface — Wave 3 brief's "restart EMBED" framing is stale and the amendment scope shifts.

### 1.4 Capture Vision NIM status on spark-3

```bash
ssh admin@192.168.0.105 'sudo systemctl is-active fortress-nim-vision.service 2>&1; sudo systemctl is-enabled fortress-nim-vision.service 2>&1'
ssh admin@192.168.0.105 'docker ps --filter name=fortress-nim-vision --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'
```

Per operator note "vision deferred": expected inactive. If active, surface — userMemories carry-forward says vision is deferred, but operator may have updated direction.

### 1.5 Capture BRAIN-49B retirement state on spark-5

```bash
ssh admin@192.168.0.109 'sudo systemctl is-active fortress-nim-brain.service 2>&1; sudo systemctl is-enabled fortress-nim-brain.service 2>&1'
ssh admin@192.168.0.109 'docker ps -a --filter name=fortress-nim-brain --format "table {{.Names}}\t{{.Status}}"'
```

Expected: inactive, enabled (per PR #340 retirement runbook). Confirms spark-5 freed for Wave 3 retrieval host.

### 1.6 Capture spark-5 GPU + disk state

```bash
ssh admin@192.168.0.109 'docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"'
ssh admin@192.168.0.109 'df -h /'
ssh admin@192.168.0.109 'df -h /mnt/fortress_nas 2>/dev/null'
ssh admin@192.168.0.109 'systemctl list-units --type=service --no-pager --state=active | grep -iE "fortress|nim|vllm" | head -20'
```

Surface inline. Capacity baseline for Wave 3 deploy planning.

### 1.7 Capture spark-3 co-residency current state

```bash
ssh admin@192.168.0.105 'docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"'
ssh admin@192.168.0.105 'systemctl list-units --type=service --no-pager --state=active | grep -iE "fortress|nim|vllm" | head -20'
```

Surface inline. Spark-3 currently hosts: TP=2 frontier rank-0 (`vllm-node` if that's the unit name) + EMBED NIM. This is the co-residency baseline that the amendment must address.

### 1.8 Frontier health

```bash
ssh admin@192.168.0.100 'curl -fsS --max-time 10 http://10.10.10.3:8000/v1/health/ready -w "\n%{http_code}\n"'
```

Expected: 200. If not 200, surface — Wave 3 amendment work shouldn't proceed if the frontier is degraded.

### 1.9 Inspect MASTER-PLAN §6.2 Wave 3 references

```bash
ssh admin@192.168.0.100 'grep -B 2 -A 5 -nE "Wave 3|reranker|nv-ingest|extraction NIM|Tier-1" /home/admin/Fortress-Prime/docs/operational/MASTER-PLAN.md 2>&1 | head -50'
```

Surface inline. Capture how the Master Plan currently references Wave 3 — relevant for cross-reference accuracy in the amendment.

### 1.10 Inline summary

Surface findings as a table:

| Surface | Original brief presumed | Current reality | Amendment scope |
|---|---|---|---|
| EMBED on spark-3 | Inactive (Phase 8 evicted, needs restart) | <observed> | Likely: drop §7 restart steps, frame as "EMBED already running" |
| Vision on spark-3 | Inactive, restart in §7 | <observed> | Per operator: vision deferred — drop or mark deferred |
| BRAIN-49B on spark-5 | Active, will retire later | Retired 2026-04-30 per PR #340 | Drop "BRAIN retirement" framing; spark-5 already freed |
| Frontier health | Active, soak in progress | <observed> | If 200: confirm soak active |
| Spark-5 GPU baseline | ~128GB free post-BRAIN | <observed via docker stats> | Update §4.4 capacity check to docker stats |
| Spark-3 co-residency | Clean (Phase 8 evicted) | TP=2 rank-0 + EMBED active | New baseline; amendment §A capacity re-eval |
| §4.4 capacity check method | nvidia-smi memory.free | GB10 reports [N/A] | Replace with docker stats |
| Co-residency monitor runbook | Not present | Missing | Add |
| LiteLLM alias schema | Pre-PR-#338 schema possible | Top-level chat_template_kwargs required | Add schema discipline note for legal-rerank/legal-extract |

Plus narrative on:
- Anything where reality contradicts a hard-stop or scope boundary in the original brief
- Any new defects surfaced post-2026-04-30 that affect Wave 3
- Any deferred-but-still-on-board items from operator (Vision, etc.)

**HALT here.** Surface inspection findings inline. Do NOT proceed to Step 2 until I review.

---

## Step 2 — Reconciliation matrix

**Only after operator confirms inspection findings.**

### 2.1 Walk the original brief section by section

For each section in the brief, surface:

| Section | Header | Original presumption | Current reality | Amendment action |
|---|---|---|---|---|
| Front matter | Driver / Stacks on / Resolves | Presumes pre-Wave-2 state | <observed> | Update PR references to include #337-#340 |
| §1 Mission | Deploy + restart | Restart EMBED + Vision | EMBED active; Vision deferred | Reframe Mission to drop restart |
| §2 Hard stops | 7 stops | All still apply? | <observed> | Likely all still apply; confirm |
| §3 Scope | A-G in scope | Component C "restart EMBED+Vision on spark-3" | Stale | Reframe C as "no-op verify" or remove |
| §4 Pre-flight | §4.4 spark-5 readiness uses nvidia-smi | nvidia-smi can't read GB10 | Defect | Replace |
| §5 Component A Reranker | spark-5 deploy | Spark-5 free now per ADR-007 | Correct | Add GB10 profile pin discipline reminder |
| §6 Component B Extraction | spark-5 deploy | Same | Correct | Add GB10 profile pin discipline reminder |
| §7 Component C EMBED+Vision restart | Restart both | EMBED active, Vision deferred | Stale | Replace with "verify EMBED, defer Vision" |
| §8-10 LiteLLM aliases / Reindex / E2E smoke | Add legal-rerank, legal-extract | Schema requirements unclear | Pre-PR-#338 | Add schema discipline (top-level kwargs, no extra_body) |
| §11 PR | Final commit + PR | Targets 2026-04-30 timestamp | Stale | Update commit timestamp framing |
| §12 Final report | Auto-surface | Still applies | Correct | No change |
| §13 Constraints | List | All still apply? | <observed> | Confirm |
| §14 (if present) | Various | <surface> | <observed> | <varies> |

### 2.2 New §0 reconciliation block (front-matter pattern from PR #337)

Brief gets a new §0 prepended (pattern from `phase-9-wave-2-alias-surgery-brief.md` §0 reconciliation block on main per PR #337). Subsections:

- **§0.1 Status as of 2026-05-01** — table of "what's already done" / "what remains" / "what's been deferred" / "what's been retired since brief was written"
- **§0.2 Capacity check method update** — replace nvidia-smi with docker stats + working-load smoke; specific commands
- **§0.3 Sequenced deployment** — Reranker before Extraction. Smallest first, stress test against EMBED + frontier, then add Extraction one NIM at a time
- **§0.4 Co-residency monitor runbook** — what to watch (HTTP 500 from any NIM, frontier latency regression, NCCL collective timeouts on TP=2), how to triage, rollback path.
- **§0.5 Schema discipline for new aliases** — top-level `chat_template_kwargs` (not `extra_body`-wrapped) per PR #338. Although Reranker/Extraction aliases may not need reasoning kwargs, the discipline rule applies to ANY alias edit going forward
- **§0.6 GB10 profile pin discipline** — every NIM pulled to spark-5 must verify GB10 profile (cc_12_0) (cudaErrorSymbolNotFound failure mode without proper profile pin)
- **§0.7 Cross-references** — PR #336 (EMBED ratification), PR #337-#340 (Wave 2 ratification), super deep research
- **§0.8 NOT-do scope** — what this brief amendment does NOT change (frontier endpoint, EMBED running config, code, etc.)

### 2.3 Inline `[Status:]` callouts in the historical execution plan

Pattern from PR #337: leave the original §1-§14 intact (preserves historical execution plan), but prepend `[Status:]` callouts at specific section heads where reality has changed. E.g.:

```
## §7 Component C — restart EMBED + Vision NIMs on spark-3

[Status: 2026-05-01 — EMBED is already running and ratified per PR #336 Wave 1 close. Vision is deferred per operator decision. This section is preserved as historical execution plan. Current Wave 3 execution proceeds with EMBED-already-running and Vision-deferred per §0.1.]

Now that retrieval workload moves to spark-5 (Reranker + Extraction), spark-3 can re-host EMBED + Vision...
```

This pattern prevents rewriting the entire brief and preserves the original author's framing while making the document accurate for current readers.

### 2.4 Surface reconciliation matrix inline

Show the populated Step 2.1 table + the §0 subsection outline + the planned `[Status:]` callout locations.

**HALT here.** Wait for operator approval of amendment scope before applying edits.

---

## Step 3 — Apply amendment

**Only after operator approves Step 2 reconciliation matrix.**

### 3.1 Prepend §0 reconciliation block

Edit `docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md` to add §0 as drafted in Step 2.2. Place after front-matter, before original §1 Mission.

### 3.2 Add `[Status:]` callouts

For each section identified in Step 2.3, prepend a single-paragraph `[Status:]` callout. Do NOT modify the section's original content beyond the callout. Preserves historical record.

### 3.3 Update front-matter

- Add references to PRs #336-#340 in **Stacks on:** list
- Update **Resolves:** if needed
- Add the two deep-research docs to **Companion deep research:**

### 3.4 Surface working-tree diff

```bash
git diff docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md | head -200
```

Show the full diff. Confirm:
- §0 block added cleanly
- `[Status:]` callouts inserted at agreed locations only
- Front-matter updated
- No section content beyond callouts modified
- File still parses as markdown (no broken section structure)

**HALT here.** Wait for operator approval of diff before commit.

---

## Step 4 — Commit + PR

**Only after operator approves Step 3 diff.**

### 4.1 Stage and inspect

```bash
cd /home/admin/Fortress-Prime
git add docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md
git status  # must show ONLY this one file
git diff --cached | head -200
```

### 4.2 Commit

```bash
git commit -m "docs(wave-3): brief amendment — reconcile to post-Wave-2 reality (doc-only)

Original brief (2026-04-30) presumed:
- EMBED inactive on spark-3 (Phase 8 evicted; needs restart)
- BRAIN-49B active on spark-5 (would retire as part of Wave 2)
- Spark-3 clean (no co-tenants)
- Vision restart in scope

Current reality (2026-05-01 post-Wave-2 ratification):
- EMBED running per PR #336 (Wave 1 ratification)
- BRAIN-49B retired per PR #340 (Wave 2 ratification); spark-5 freed
- Spark-3 hosts TP=2 frontier rank-0 + EMBED (co-residency)
- Vision deferred per operator decision

Amendments applied (single-file, doc-only):
- New §0 reconciliation block prepended (pattern from PR #337)
  - §0.1 Status table (done/remains/deferred/retired)
  - §0.2 Capacity check method update (docker stats)
  - §0.3 Sequenced deployment (Reranker before Extraction)
  - §0.4 Co-residency monitor runbook
  - §0.5 Schema discipline for new aliases (PR #338 carry-forward)
  - §0.6 GB10 profile pin discipline
  - §0.7 Cross-references
  - §0.8 NOT-do scope
- [Status:] callouts at sections where reality has shifted (preserves historical
  execution plan; pattern from PR #337)
- Front-matter updated with current PR references and deep-research companions

References:
- PR #336 (Wave 1 EMBED ratification)
- PR #337-#340 (Wave 2 ratification sequence)
- docs/research/nemotron-3-super-deep-research-2026-04-30.md
- (embed deep-research deferred — separate ticket per PR #341)

What this PR does NOT do:
- Does not deploy any NIM
- Does not modify any service
- Does not change any code
- Does not modify the frontier endpoint
- Does not start Wave 3 execution (separate kickoff after this merges)
"
```

### 4.3 Push and open PR

```bash
git push -u origin docs/wave-3-brief-amendment-2026-05-01
gh pr create \
  --base main \
  --head docs/wave-3-brief-amendment-2026-05-01 \
  --title "docs(wave-3): brief amendment — reconcile to post-Wave-2 reality (doc-only)" \
  --body-file <body-file>
```

PR body should include:

1. **Summary.** Wave 3 brief amendment per post-Wave-2 reality reconciliation.
2. **Step 1 inspection findings.** The reality table.
3. **Step 2 amendment scope.** What changed, what stayed.
4. **Why this PR is doc-only.** Deploy execution is a separate kickoff after merge.
5. **What this PR does NOT do.**
6. **References.** All PRs and deep research docs.
7. **Next deliverable after merge.** Wave 3 execution kickoff against the now-amended brief.
8. Mark "merge BLOCKED on operator review."

---

## Step 5 — Halt

When this PR merges:
- Wave 3 brief is reconciled to current reality on main
- Next deliverable: Wave 3 execution kickoff (separate session)
- Don't queue execution work in this kickoff; one PR at a time

---

## Surface points before declaring this kickoff done

1. Step 1 inspection table populated + narrative findings
2. Operator-confirmation gate at end of Step 1 (HALT)
3. Step 2 reconciliation matrix populated + §0 outline + callout locations
4. Operator-confirmation gate at end of Step 2 (HALT)
5. Step 3 diff inline
6. Operator-confirmation gate at end of Step 3 (HALT)
7. After confirmation: Step 4 stage + commit + PR URL + number

---

## Hard constraints

- DO NOT modify any service (frontier, EMBED, Vision, BRAIN, anything)
- DO NOT touch live `litellm_config.yaml` or `deploy/litellm_config.yaml`
- DO NOT modify any code (BrainClient, synthesizers, council, anything)
- DO NOT pull any NIM (NGC commands prohibited in this kickoff)
- DO NOT modify any file outside `docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md`
- DO NOT modify the original brief's §1-§14 content beyond `[Status:]` callouts at agreed locations
- DO NOT proceed past any HALT gate without operator approval
- DO NOT use `--admin`, `--force`, or self-merge
- If §1 inspection surfaces reality that contradicts the amendment scope (e.g., EMBED actually inactive, or BRAIN-49B somehow re-active), halt — the amendment text needs revision before proceeding
- If Vision is unexpectedly active, halt — operator decision needed on whether amendment treats Vision as live or still-deferred

Standing by.
