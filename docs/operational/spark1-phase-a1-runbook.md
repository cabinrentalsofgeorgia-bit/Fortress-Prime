# Spark-1 Phase A1 Runbook (Reshaped, Additive)

**Created:** 2026-04-29
**Source brief:** `~/spark1-phase-a1-reshaped-brief.md` (spark-1 only)
**Branch:** `feat/spark1-phase-a1-legal-overlays`
**Owner:** Gary Knight
**Scope:** verification + minimal-mutation overlays. No schema changes, no role changes (modulo conditional `.env` cleanup), no alembic, no Postgres restart, no UFW changes.

---

## What Phase A1 does

1. Verifies the legal schema is intact on spark-1 (no mutation).
2. Verifies NAS mount and legal directories.
3. Resolves the stale `fortress_app` reference (autonomous decision tree).
4. Tightens `fortress-brain.service` Streamlit bind from `0.0.0.0` to `127.0.0.1` (sovereignty fix).
5. Files the alembic-divergence issue that blocks M3 activation.
6. Writes durable migration provenance.

## What Phase A1 does NOT do

- No `alembic upgrade` on spark-1 (heads divergent — see Issue filed by this PR).
- No role create / drop / alter on spark-1 (canonical 004 roles already in place).
- No mutation to `public.*`, `division_a.*`, `hedge_fund.*`, or any `alembic_version` row.
- No write to admin.env values (rename action proved unsafe — see §3 below).
- No consumer service wired to spark-1 Postgres (M3 owns first write path).
- No UFW config change (separate audit follow-up).

---

## §1 — Pre-flight (read-only)

```bash
# DB role + listener sanity
sudo -u postgres psql -c "\du" | grep fortress
sudo ss -tlnp | grep 5432
```

Expected:
- Roles `fortress_admin` (CREATEDB), `fortress_api` (login only).
- Postgres listening on `127.0.0.1:5432` and `192.168.0.104:5432`.
- No `fortress_app` role.

If a fortress role is missing or `fortress_app` exists: STOP — pre-conditions for Phase A1 not met.

## §2 — Legal schema verification (read-only)

```bash
sudo -u postgres psql -d fortress_db -c "\dt legal.*"
sudo -u postgres psql -d fortress_db -c "
  SELECT table_name,
         (SELECT COUNT(*) FROM information_schema.columns
          WHERE table_schema='legal' AND table_name=t.table_name) AS col_count
  FROM information_schema.tables t
  WHERE table_schema='legal' ORDER BY table_name;"

# Same for fortress_prod
sudo -u postgres psql -d fortress_prod -c "
  SELECT table_name,
         (SELECT COUNT(*) FROM information_schema.columns
          WHERE table_schema='legal' AND table_name=t.table_name) AS col_count
  FROM information_schema.tables t
  WHERE table_schema='legal' ORDER BY table_name;"
```

Expected: 38 tables (per `\dt`) / 44 rows in `information_schema.tables` (extras are pre-v2 compatibility views: `case_graph_edges`, `case_graph_nodes`, `discovery_draft_items`, `discovery_draft_packs`, `legal_cases`, `sanctions_alerts`).

Spot-checked tables (all confirmed present 2026-04-29):
`cases`, `vault_documents`, `case_slug_aliases`, `privilege_log`, `ingest_runs`, `correspondence`, `deadlines`, `filings`, `case_actions`, `case_evidence`, `case_watchdog`, `case_precedents`.

If any expected table missing: STOP, surface. Do **not** run alembic to fix — it means the spark-2 schema export was incomplete.

## §3 — fortress_app role disambiguation

Run from `~/Fortress-Prime` on spark-1 (or any local clone):

```bash
grep -rIn "fortress_app" \
  --include="*.py" --include="*.env*" --include="*.yaml" --include="*.yml" \
  --include="*.sh" --include="*.toml" --include="*.cfg" --include="*.ini" \
  --include="*.md" \
  | grep -v "spark1-current-state" \
  | grep -v "\.git/"

grep -rIn "POSTGRES_FORTRESS_APP_PASSWORD" \
  --include="*.py" --include="*.env*" --include="*.yaml" --include="*.yml" \
  --include="*.sh" --include="*.toml" --include="*.cfg" --include="*.ini"
```

**Decision tree:**

- **No hits anywhere → conclusion 3a (stale).** This is what 2026-04-29 found.
  
  Brief's prescribed action is "rename APP → API in admin.env, value carried over." **DO NOT execute this literally** if both APP and API entries already exist with different values — doing so overwrites the working `fortress_api` password.
  
  On 2026-04-29 admin.env had three keys: `ADMIN_PASSWORD`, `APP_PASSWORD` (44 chars), `API_PASSWORD` (64 chars). Values differ. **Action taken: no-op.** Document the residual APP key in `spark-2-to-spark-1-migration-provenance.md` and leave the file alone. Cleanup is a one-line `sed` follow-up if operator wants the APP key gone.

- **Hits in service code (`backend/services/*.py`, `backend/core/database.py`, `backend/core/config.py`) → conclusion 3b (intentional third role).** STOP. Surface to operator. Do not create the role.

- **Hits in both → 3b with ambiguity.** STOP.

## §4 — NAS mount + legal directories (read-only)

```bash
mountpoint /mnt/fortress_nas
ls -ld /mnt/fortress_nas/Corporate_Legal/Business_Legal/
ls -ld /mnt/fortress_nas/legal_vault/
ls -1 /mnt/fortress_nas/legal_vault/
ls -ld /mnt/fortress_nas/audits/
df -h /mnt/fortress_nas
```

Expected on 2026-04-29:
- Mount: active (`192.168.0.113:/volume1/ai-data-new`, 54 TB free).
- `legal_vault/` subdirs: `7il-v-knight-ndga`, `affidavit-filing`, `fish-trap-suv2026000013`, `vanderburge-v-knight-fannin` (4 directories — note: brief listed 6 expected, actual is 4; consolidation is operator-intended).
- `Corporate_Legal/Business_Legal/` and `audits/` readable.

If mount missing: STOP. NAS is a hard prerequisite for the legal pipeline.

## §5 — Sovereignty fix: bind fortress-brain Streamlit to loopback

Pre-2026-04-29 state: `fortress-brain.service` Streamlit bound to `0.0.0.0:8501` because the systemd unit's ExecStart did not specify `--server.address` (Streamlit defaults to all interfaces). Audit S-01 (UFW disabled) compounds the exposure. Public-bound Streamlit on a legal data plane spark violates CONSTITUTION.md Article I.

The active configuration is split across:
- `/etc/systemd/system/fortress-brain.service` (base unit)
- `/etc/systemd/system/fortress-brain.service.d/10-legacy-path.conf` (drop-in that overrides `ExecStart` to use `Fortress-Prime.legacy/venv/`)

The drop-in's ExecStart is what runs. Edit the drop-in to add `--server.address 127.0.0.1` to the streamlit invocation:

```bash
sudo sed -i.bak \
  's|--server.port 8501 --server.headless true|--server.address 127.0.0.1 --server.port 8501 --server.headless true|' \
  /etc/systemd/system/fortress-brain.service.d/10-legacy-path.conf

sudo systemctl daemon-reload
sudo systemctl restart fortress-brain.service
sleep 3
sudo systemctl is-active fortress-brain.service
sudo ss -tlnp | grep 8501
# expected after: 127.0.0.1:8501 (loopback only); NOT 0.0.0.0:8501 / [::]:8501
```

If the listener is still on `0.0.0.0`: stop, investigate Streamlit version or unit-file precedence (look for any `.service.d/*.conf` other than `10-legacy-path.conf`).

If access from spark-2 or operator workstation is needed, route via Tailscale or SSH tunnel — never re-bind to `0.0.0.0`.

After successful restart, copy the updated unit + drop-in into the repo:

```bash
mkdir -p /home/admin/Fortress-Prime/deploy/systemd/fortress-brain.service.d
sudo cat /etc/systemd/system/fortress-brain.service \
  > /home/admin/Fortress-Prime/deploy/systemd/fortress-brain.service
sudo cat /etc/systemd/system/fortress-brain.service.d/10-legacy-path.conf \
  > /home/admin/Fortress-Prime/deploy/systemd/fortress-brain.service.d/10-legacy-path.conf
```

## §6 — Issue filing

Title: `M3 prereq: merge divergent alembic heads on spark-2 fortress_db`

See body in `~/spark1-phase-a1-reshaped-brief.md` §9. Labels: `M3-blocker`, `alembic`, `postgres`, `spark-1`.

## §7 — Provenance doc

`docs/operational/spark-2-to-spark-1-migration-provenance.md` — written / updated by Phase A1 PR. Treat as the durable migration record going forward.

## §8 — Verification at exit

| Check | How | Pass criterion |
|---|---|---|
| Legal schema present | `\dt legal.*` against `fortress_db` and `fortress_prod` | 38 tables, 12 spot-checks all return 1 |
| NAS mount | `mountpoint /mnt/fortress_nas` | "is a mountpoint" |
| `fortress_app` resolution | grep over repo | 0 hits → 3a no-op (or 3b STOP and surface) |
| Streamlit bind | `ss -tlnp \| grep 8501` | `127.0.0.1:8501` (NOT `0.0.0.0`) |
| Provenance doc | `git log docs/operational/spark-2-to-spark-1-migration-provenance.md` | committed in this branch |
| State snapshot | `git log docs/operational/spark1-current-state-2026-04-29.md` | committed in this branch |
| Alembic issue | `gh issue list --label M3-blocker` | issue exists, linked in PR |

PR merge BLOCKED on operator review per brief §10.
