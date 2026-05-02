# Spark Cluster Inventory — 2026-04-28

**Total Nodes:** 6 sparks (ADR-001 update required — currently states 4)

---

## Node Status Summary

| Node | Status | RAM Free | Notes |
|------|--------|----------|-------|
| spark-1 | Online | 314 GB | M3 migration target |
| spark-2 | Online | — | Fortress-Prime primary |
| spark-3-1 | Online | — | Live replacement for offline 100.87.23.102 |
| spark-4 | Online | 116 GB | qwen 32B + Ollama — best general-purpose |
| spark-5 | Online | Saturated | RAM consumed by BRAIN workloads |
| spark-6 | Online | 118 GB | SSH key authorization needed |

**Cluster Headroom:** ~470 GB total (314 + 118 + 38)

---

## Node Details

### spark-1
- **Role:** M3 trilateral migration target
- **Capacity:** 314 GB free
- **Status:** Ready for fortress_prod mirror writes

### spark-2  
- **Role:** Fortress-Prime primary host
- **Status:** Production workload active

### spark-3-1
- **Role:** Live spark-3 replacement
- **Previous:** Replaced offline node at 100.87.23.102
- **Status:** Online and operational

### spark-4
- **Role:** General-purpose inference + development
- **Capacity:** 116 GB free
- **Services:** qwen 32B model, Ollama runtime
- **Recommendation:** Best choice for new general-purpose workloads

### spark-5
- **Role:** BRAIN specialized workloads
- **Capacity:** RAM-saturated
- **Status:** Not available for new allocations

### spark-6
- **Role:** Available capacity node
- **Capacity:** 118 GB free
- **Blocker:** SSH key authorization required
- **Action Required:** Provision SSH access for utilization

---

## Capacity Planning

**Available Nodes for New Work:**
1. **spark-4** — 116 GB, general-purpose ready
2. **spark-6** — 118 GB, pending SSH access
3. **spark-1** — 314 GB, post-M3 migration

**Saturated Nodes:**
- **spark-5** — BRAIN workloads consuming all RAM
- **spark-2** — Fortress-Prime production load

---

## Action Items

1. **ADR-001 Update:** Revise architecture decision record to reflect 6-node cluster (currently documents 4)
2. **spark-6 SSH:** Authorize SSH keys for spark-6 access
3. **Capacity Monitoring:** Track spark-1 utilization post-M3 activation

---

**Last Updated:** 2026-04-28  
**Next Review:** Post-M3 activation (spark-1 utilization assessment)