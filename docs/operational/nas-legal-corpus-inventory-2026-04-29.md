# NAS Legal Corpus Inventory — 2026-04-29

**Driver:** Phase B + Case II prep require a comprehensive retrieval surface. The companion caselaw audit (`docs/operational/caselaw-corpus-audit-2026-04-29.md`, PR #287) covered `/mnt/fortress_nas/legal-corpus/` only. This inventory walks the rest of NAS for any legal corpus material outside that path.

**Operator:** Gary Knight
**Executor:** Claude Code on spark-2
**Brief:** `/home/admin/nas-legal-corpus-inventory-brief.md`
**Outcome:** **B (small)** — one new substantive corpus candidate (GA appellate procedural rules, 1.8 MB), already-curated and pre-chunked. Companion ingestion plan is a one-paragraph note appended below; not large enough to justify a separate brief.

---

## 1. Top-level NAS landscape

NAS root (`/mnt/fortress_nas/`) — total walk surface ≈ 1.5 TB. Sized + scope-classified:

| Directory | Size | Walk decision | Notes |
|---|---|---|---|
| `legal-corpus/` | 82 MB | covered by **caselaw audit** (PR #287) | not re-walked here; cross-referenced |
| `Corporate_Legal/` (excl. `Business_Legal/<case_slug>/`) | 6.9 GB | walked (subset) | `Business_Legal/<case>/` per-case skipped per brief |
| `Corporate_Legal/Business_Legal/<all subdirs>` | included in 6.9 GB | **SKIPPED** per brief §6 | case-specific evidence (Case I + II), not corpus |
| `legal/` | 1.7 MB | walked | placeholder dirs (02_Legal, 03_Accounting, 07_CRM, fortress_docs); 1 PDF total |
| `legal_vault/` | 6.5 GB | **SKIPPED** per brief §6 | case-specific email vault, not corpus |
| `Backups_Critical/` | 334 MB | **SKIPPED** | known non-legal (per brief §6 spirit; verified contents are CROG/Personal/Properties backups) |
| `backups/` | 774 GB | **SKIPPED** per brief §6 | Postgres dumps; known non-legal |
| `nim-cache/` | 227 GB | **SKIPPED** per brief §6 | NIM container images |
| `nim_cache/` | 108 GB | **SKIPPED** | NIM image alias |
| `models/` | 156 GB | **SKIPPED** (sampled) | model weights, not corpus |
| `fortress_data/` | 239 GB | sampled — no `*legal*` / `*caselaw*` subdirs | sampled root for legal-named subdirs; none |
| `fortress_fast/` | 104 GB | not walked | symlink to `/mnt/ai_fast`; local fast cache, not corpus |
| `Communications/` | 67 GB | confirmed-then-skipped | emails (Business_CROG / Personal / MailPlus) — not corpus |
| `Uncategorized/` | 27 GB | sampled | mostly Business_CROG operational docs; one operator-history candidate surfaced (see §3) |
| `Digital_Media/` | 8.6 GB | not walked | media |
| `Business_Prime/` | 11 GB | sampled | duplicate of `Corporate_Legal/Business_Legal` case structure (Pleadings - GAND, Discovery, Depositions, etc. — case-specific, SKIPPED) |
| `Enterprise_War_Room/` | 3.5 GB | not walked | per brief, non-legal |
| `chroma_db/` | 2.4 GB | inspected | legacy ChromaDB; 224,209 personal-doc embeddings; not legal corpus (see §4) |
| `Real_Estate_Assets/` | 440 MB | sampled | property records, not corpus |
| `raw_images/` | 591 MB | not walked | media |
| `Financial_Ledger/` | 395 MB | sampled | tax / accounting; not corpus |
| `audits/` | 181 MB | inspected | audit manifests + reports; not corpus |
| `sectors/` | 12 MB | walked | mixed; non-case subdirs total < 1.5 MB and non-corpus (see §3) |
| `datasets/` | 6.9 MB | walked | **HIGH SIGNAL** — see §3 |
| `Business_MarketClub/` (root) | 27 MB | confirmed-then-skipped | trading alerts JSONs |
| `migration_workspace/` | 13 MB | not walked | system |
| `Intelligence/` | 128 KB | not walked | tiny |
| `training/` | 940 KB | confirmed-non-corpus | training jsonl |
| `distillation/` | 16 KB | confirmed-non-corpus | metadata json |
| `lora/` | 0 | empty | |
| `Transcripts/` | 0 | empty | financial-research transcript skeletons |
| `wealth/` | 4 KB | empty | LIVE_DISABLED marker |
| `quarantine/` | 0 | empty | |

**Top-level walk count:** 38 root entries inspected; 8 walked or sampled in detail; 13 confirmed-or-known non-legal and skipped; 6 explicitly excluded by brief; the rest empty or media-only.

---

## 2. Confirmed legal corpus (pre-existing)

Cross-referenced with the caselaw audit (`docs/operational/caselaw-corpus-audit-2026-04-29.md`):

| Path | Size | File count | Tags | Vectorized |
|---|---|---|---|---|
| `/legal-corpus/courtlistener/opinions-full.jsonl` | 52 MB | 1 file (1,880 rows) | `caselaw_state_ga` (insurance-filtered) | **VECTORED** in `legal_caselaw` (2,711 chunks) |
| `/legal-corpus/courtlistener/opinions-expanded.jsonl` | 8 MB | 1 file | `caselaw_state_ga` | included in `legal_caselaw` |
| `/legal-corpus/courtlistener/raw/` | trivial | empty subdirs (`opinions/`, `clusters/`, `api/`) | scaffolding | n/a |
| `/legal-corpus/courtlistener/filtered/georgia_insurance_opinions.jsonl` | trivial | 1 file | `caselaw_state_ga` | derivative |
| `/legal-corpus/ocga/raw/title-33/` | 0 | empty dir | scaffolding for OCGA Title 33 (insurance) — never populated | NOT_VECTORED |
| `/legal-corpus/training-pairs/` | 8 MB | 7 files (.jsonl + .json) | training data, **not retrieval corpus** | n/a (different pipeline — fine-tune) |

---

## 3. Candidate legal corpus — discovered in this inventory

### 3.1 NEW substantive: `/datasets/legal-corpus/ga-rules/`

| Field | Value |
|---|---|
| Path | `/mnt/fortress_nas/datasets/legal-corpus/ga-rules/` |
| Size | 1.8 MB |
| File count | 5 |
| Files | `ga-court-of-appeals-rules.{pdf,jsonl}`, `ga-supreme-court-rules.{pdf,jsonl}`, `manifest.json` |
| Tags | `practice_guides`, `statutes_state_ga` (procedural rules) |
| Vectorized | **NOT_VECTORED** — not present in any Qdrant collection |
| Recommendation | **Ingest** |

**Why it matters for Case II prep:** Case II is filed in NDGA federal court, but appellate / procedural cross-references to Georgia state rules happen routinely (e.g., supplemental jurisdiction, choice-of-law on state-court precedent in diversity cases). Having the GA appellate procedural rules in the retrieval surface lets BRAIN cite them during drafting and analysis.

**Ingestion note (one paragraph):** the data is already pre-chunked into JSONL with one rule per line. A small ingest can use the same pipeline as `legal_caselaw`: reuse `ingest_courtlistener.py`'s chunker via `--source` argument pointing at these JSONLs, with a flag to override the collection target (or write a 30-line wrapper). Estimated runtime under 5 minutes total. Not large enough to justify a separate full operational brief — flag for the operator to authorize as a single one-shot ingest, OR fold into the Phase B brief's "retrieval surface" prep step.

### 3.2 NEW operator-history candidate: `/Uncategorized/Business_CROG/CROG/Theft of Services/`

| Field | Value |
|---|---|
| Path | `/mnt/fortress_nas/Uncategorized/Business_CROG/CROG/Theft of Services/` |
| File count | 76 PDFs (signed theft-of-services letters from CROG-VRS guests) |
| Tags | `briefs_operator_history` |
| Vectorized | NOT_VECTORED |
| Recommendation | **Operator review** — these are operator's own drafting, signed copies of demand letters. Useful as drafting-style precedent for legal_drafter prompts ("write in this voice"); not useful as substantive caselaw. Decide ingest yes/no. |

### 3.3 Stalled scaffolding (empty dirs — NOT corpus, but flagged)

These exist as ingestion-pipeline scaffolding that was created and never populated. Flagging for the operator to either drive forward or remove:

| Path | State |
|---|---|
| `/legal-corpus/ocga/raw/title-33/` | Empty dir — Title 33 (Insurance) pull never populated |
| `/datasets/legal-corpus/ocga/.raw/title-9/` | Empty dir — Title 9 (Civil Practice) pull never populated |
| `/legal-corpus/courtlistener/raw/{opinions,clusters,api}/` | Empty subdirs — staging area unused after the pipeline went JSONL-direct |
| `/datasets/legal-corpus/legal-instruct/additions-20260422/` | Empty — fine-tune additions never landed for that date |

These are housekeeping items, not Phase B blockers.

### 3.4 Other legal-named directories — confirmed non-corpus

| Path | Why non-corpus |
|---|---|
| `/legal/02_Legal/`, `/legal/03_Accounting/`, `/legal/07_CRM/`, `/legal/fortress_docs/` | Empty placeholder structure (1 PDF total across all) |
| `/sectors/legal/case_23-11161-JKS/`, `.../fish-trap-suv2026000013/`, `.../prime-trust-23-11161/` | Case-specific (per brief, equivalent to `<case_slug>/` skip rule) |
| `/sectors/legal/pdf_archive/` | 5 PDFs of SUV2026000013 motion drafts — case-specific |
| `/sectors/legal/owner-statements/` | 18 financial owner statements — not legal corpus |
| `/sectors/legal/{context,intelligence,snapshots,vectors}/` | Operational metadata, tiny |
| `/Corporate_Legal/Personal_Documents/` | 31 MB / 156 files — personal household docs, not corpus |
| `/Corporate_Legal/Business_MarketClub/` | 16 KB / 2 JSON files — trading metadata |
| `/Business_Prime/Legal/` | Duplicate of `Corporate_Legal/Business_Legal/` case structure — case-specific evidence |

---

## 4. The chroma_db finding (legacy vector store)

`/mnt/fortress_nas/chroma_db/` (2.4 GB) holds a **single langchain collection with 224,209 embeddings** (384-dim). Source-path inspection of the metadata reveals the corpus is overwhelmingly **operator personal/household documents**:

```
/mnt/warehouse/documents/Documents - Gary's iMac/Software/dazzle/User's Manuals/HS 10 in 1 Readers.pdf
/mnt/warehouse/documents/Documents - Gary's iMac/CRG/MENU/Menu@CRG.pdf
/mnt/warehouse/documents/Documents - Gary's iMac/Credit Report/2009/03.29.2009/credit Report.rtfd/KnightCredit Rpt.pdf
/mnt/warehouse/documents/Documents - Gary's iMac/Noontootla Property/Appraisal/APPRAISAL_COVENTON[1].pdf
/mnt/warehouse/documents/Documents - Gary's iMac/Software/Virtual PC/version 2.1.1/.../VirtualPC™ 2.1 Manual.pdf
...
```

Mostly software manuals, household receipts, property appraisals, credit reports, dating from 2002 onward. **Not legal corpus.** It's a legacy ChromaDB that predates the Qdrant migration (Phase 5a moved retrieval to Qdrant).

**Status:** legacy / unused. Not part of Phase B retrieval surface. Worth flagging for the operator to decide whether to retire (delete the 2.4 GB) or migrate selectively. **Out of scope for this audit** — flagged here so the next inventory doesn't re-discover it.

---

## 5. Gap analysis — Outcome B (small)

The breadth-walk surfaced **one substantive new corpus candidate** (`/datasets/legal-corpus/ga-rules/`, 1.8 MB) and **one operator-judgment candidate** (`/Uncategorized/.../Theft of Services/`, 76 PDFs). The rest of NAS either:

- is the existing `/legal-corpus/` walk (covered by the caselaw audit),
- is case-specific evidence (skipped per brief),
- is operator personal / household / business non-legal,
- is empty scaffolding,
- or is a legacy ChromaDB store with no legal corpus.

There is **no hidden treasure trove of caselaw / treatises / Westlaw exports / Restatements on this NAS.** The corpus visible to retrieval is essentially `legal_caselaw` (2,711 GA-insurance chunks per the caselaw audit) plus whatever the operator authorizes from §3.1 (GA rules) and §3.2 (own-style drafting precedent).

This is itself an actionable finding: any "white-shoe-grade" Case II retrieval surface needs **federal CA11 ingestion** (per the caselaw audit's Outcome B and the companion ingestion brief at `docs/operational/briefs/legal-caselaw-federal-ingestion-2026-04-29.md`) plus optional **broader GA caselaw** (general state caselaw, not just insurance — flagged as a secondary finding in the caselaw audit). The current retrieval surface is too narrow.

---

## 6. Cross-reference

- **Caselaw audit** (depth on `/legal-corpus/`): `docs/operational/caselaw-corpus-audit-2026-04-29.md` — PR #287
- **Federal CA11 ingestion brief** (companion to the caselaw audit): `docs/operational/briefs/legal-caselaw-federal-ingestion-2026-04-29.md`
- **`qdrant-collections.md`** — does not list the GA-rules corpus; should be updated if §3.1 ingest lands
- **MASTER-PLAN §6.2 (Inference platform)** — "Caselaw corpus audit" entry should be updated to reflect both audits complete + Outcome B

---

## 7. Out-of-band housekeeping items surfaced (low priority)

Captured here so they don't get lost; **not** Phase B blockers:

1. `/legal-corpus/ocga/raw/title-33/` and `/datasets/legal-corpus/ocga/.raw/title-9/` are empty scaffolding — either drive forward (OCGA ingest) or remove the dirs.
2. `/chroma_db/` (2.4 GB) is an unused legacy ChromaDB. Decide whether to delete or selectively migrate.
3. `/Corporate_Legal/Business_Legal/` has both `7il-v-knight-ndga-ii/` (case-slug subdir) AND a flat structure with `Pleadings - GAND/`, `Discovery/`, `Depositions/`, `Correspondence/`, `THATCHER LAWSUIT/`, etc. The flat structure is the pre-case-slug layout. Both contain Case I + II evidence; the curated-set layout under the case-slug dir is the canonical one. Worth deciding whether to retire or alias the flat structure.
4. `/Business_Prime/Legal/` mirrors that flat case structure too. Same retire-or-alias question.

End of inventory.
