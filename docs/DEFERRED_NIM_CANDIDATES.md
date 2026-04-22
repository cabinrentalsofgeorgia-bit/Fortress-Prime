# Deferred NIM Candidates

Models pre-cached or identified for future deployment. Not wired to any service today.

---

## llama-nemotron-embed-vl-1b-v2 — Legal/Property Vision Retrieval

**Status:** Identified, NOT cached (NIM container not available via nvcr.io)
**Intended use:** Vision-language embedding for Legal case images and property photos.
Enables Qdrant retrieval over image content (damage photos, property condition docs,
legal exhibit attachments).

**NGC catalog ID:** `nvidia/llama-nemotron-embed-vl-1b-v2`
**Build API:** Available at `https://integrate.api.nvidia.com/v1` ✅
**NIM container:** NOT FOUND at `nvcr.io/nim/nvidia/llama-nemotron-embed-vl-1b-v2:latest`

**Note on ARM64:** Unverifiable — NIM container doesn't exist on registry.
`llama-3.2-nemoretriever-1b-vlm-embed-v1` (the VLM retriever bundle) is on nvcr.io
but AUTH_DENIED — requires NIM entitlement/NVAIE.

**Closest available substitute (text-only, cached as smoke test):**
`nvidia/llama-nemotron-embed-1b-v2` → NAS at
`/mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar`

**Target node when deployed:** spark-1 (Legal primary) or spark-4 (property retrieval)
**Memory footprint:** ~2GB (embed models are lightweight)
**Decision needed:** Confirm whether text-only embed-1b is sufficient for Legal/Property,
or whether visual embedding is required. If visual: resolve NIM entitlement for
`llama-3.2-nemoretriever-1b-vlm-embed-v1`.

---

## nemotron-3-nano-30b-a3b — Deliberation Seats (Deployment B, DEFERRED)

**Status:** Deferred — ARM64 verification blocked, memory math needs confirmation
**See:** `docs/NIM_ARM64_VERIFICATION_2026-04-21.md` Phase 0 report
**Intended use:** Seats 4, 6, 9 of the 9-seat concierge council
**Blocked on:** NGC NIM entitlement for ARM64 manifest check + fp16 memory footprint
confirmation
**NAS path (reserved):** `/mnt/fortress_nas/nim-cache/nim/nemotron-3-nano-30b-a3b/latest/`

---

## Notes

- NAS paths are reserved for all deferred candidates
- When NVAIE subscription resolves: re-run Phase 0 ARM64 check for both deferred models
- Deferred models are NOT wired to any service until explicitly greenlighted
