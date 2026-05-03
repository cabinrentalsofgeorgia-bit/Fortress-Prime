# Fortress Legal Runtime Ownership Audit - 2026-05-03

Status: read-only live audit
Scope: Spark-2 vs Spark-1 runtime ownership for Fortress Legal foundation hardening
Related map: `docs/architecture/runtime-map.md`

No services were started, stopped, restarted, reloaded, migrated, or modified during this audit.

## Summary

The live runtime evidence supports the runtime map's current-state conclusion:

- **Spark-2 is the active Fortress Legal / Fortress Prime app-control-plane host today.**
- **Spark-1 is reachable and running useful platform pieces, but it is not yet serving the Fortress Legal backend, ARQ worker, command-center, Qdrant, or LiteLLM gateway.**
- Spark-1 should remain documented as the Legal target/staging host until an explicit cutover proves otherwise.

## Spark-2 Live Evidence

Spark-2 hostname evidence:

- Hostname: `spark-node-2`
- Operator access path: `ssh admin@spark-2`

Running service evidence included:

| Runtime surface | Live Spark-2 evidence |
|---|---|
| Backend | `fortress-backend.service` active/running, `ExecStart=/usr/local/bin/run-fortress-backend.sh` |
| Worker | `fortress-arq-worker.service` active/running |
| Command center / console | `crog-ai-frontend.service`, `fortress-console.service`, and Next.js processes active |
| Postgres | `postgresql@16-main.service` active/running, listening on `5432` |
| Redis | `redis-server.service` active/running, listening on `127.0.0.1:6379` |
| Qdrant | Docker container `fortress-qdrant` running `qdrant/qdrant:v1.13.2`, ports `6333-6334` |
| LiteLLM | `litellm-gateway.service` active/running on `127.0.0.1:8002` using `/home/admin/Fortress-Prime/litellm_config.yaml` |
| Ollama | `ollama.service` active/running, port `11434` |
| Ray | `fortress-ray-head.service` active/running, head at `192.168.0.100` |
| Sync/indexing | `fortress-sync-worker.service`, `fortress-sentinel.service`, `fortress-watcher.service`, `fortress-telemetry.service` active/running |

Observed listening ports relevant to the map:

| Port | Interpretation |
|---:|---|
| `5432` | Postgres 16 on Spark-2 |
| `6333`, `6334` | Qdrant on Spark-2 |
| `6379` | Redis on Spark-2 loopback |
| `8000` | Backend or internal app surface on Spark-2 |
| `8002` | LiteLLM gateway on Spark-2 loopback |
| `3000`, `3005` | Next.js / command-center frontend surfaces |
| `9800` | Fortress console |
| `11434` | Ollama |
| `6390`, `8265` | Ray head / dashboard |

Observed active Postgres connections on Spark-2:

| Database | Role(s) observed | Meaning |
|---|---|---|
| `fortress_shadow` | `fortress_api` | Active runtime/control-plane sessions |
| `fortress_db` | `fortress_api`, `miner_bot` | Active legal/legacy DB usage still present |
| `fortress_prod` | `fortress_api` | Active production/mirror DB usage still present |
| `fortress_guest` | `fgp_app` | Legacy/dev surface still connected somewhere |
| `paperclip_db` | `paperclip_admin` | Paperclip control-plane usage |

## Spark-1 Live Evidence

Spark-1 reachability evidence:

- `spark-1` resolves to Tailscale `100.127.241.36`.
- `spark-node-1` resolves to `10.10.10.1`.
- Spark-1 responded to ping from Spark-2.
- Hostname: `spark-node-1`.
- Observed addresses include `192.168.0.104`, `10.10.10.1`, and `100.127.241.36`.

Running service evidence included:

| Runtime surface | Live Spark-1 evidence |
|---|---|
| Postgres | `postgresql@16-main.service` active/running |
| Redis | `redis-server.service` active/running on loopback |
| NIM sovereign | `fortress-nim-sovereign.service` active/running, Docker container on port `8000` |
| Ray | `fortress-ray-worker.service` active/running as worker against Spark-2 Ray head |
| Ollama | `ollama.service` active/running |
| Brain UI | `fortress-brain.service` active/running on loopback `8501` |

Spark-1 unit-file evidence did **not** show these app-control-plane units installed/enabled:

- `fortress-backend.service`
- `fortress-arq-worker.service`
- `fortress-console.service`
- `litellm-gateway.service`
- `fortress-qdrant.service` or equivalent Qdrant unit

Spark-1 Docker evidence:

| Container | Image | Runtime meaning |
|---|---|---|
| `fortress-nim-sovereign` | `nvcr.io/nim/meta/llama-3.1-8b-instruct-dgx-spark:latest` | Sovereign inference endpoint on Spark-1 |
| Portainer agent | `portainer/agent:lts` | Cluster/container management agent |

Observed active Postgres connections on Spark-1:

| Database | Role(s) observed | Meaning |
|---|---|---|
| `postgres` | `postgres` | Only local audit/admin query observed |

No active application sessions into Spark-1 legal/runtime DBs were observed during this audit.

## Security Finding

### High: Spark-1 NGC key exposed in process arguments

The Spark-1 NIM container command exposes an `NGC_API_KEY` value in process arguments. The value is intentionally **not** copied into this document.

Why this matters:

- Process arguments can be visible to local users and captured in process listings, telemetry, debug logs, shell history, or incident artifacts.
- Because the key appeared in live process arguments, assume the credential is exposed.

Recommended remediation:

1. Rotate the affected NGC credential.
2. Move the key out of command-line arguments.
3. Prefer a root-owned environment file, systemd credential, or Docker secret-style injection.
4. Restart only the affected NIM service after the replacement secret path is in place.
5. Re-run a redacted process-argument check after restart to prove the key no longer appears in `ps` output.

Do not commit the key, print it, or paste it into issue/PR text.

## Conclusion

For Fortress Legal planning and feature-free foundation hardening, the current live ownership should be treated as:

| Layer | Current live owner | Target / notes |
|---|---|---|
| Backend API | Spark-2 | Spark-1 target only after explicit cutover |
| ARQ / workers | Spark-2 | Spark-1 not active for these units |
| Command center / Legal UI | Spark-2 | Spark-1 not active for these units |
| Postgres runtime sessions | Spark-2 | Spark-1 DB exists but no app sessions observed |
| Qdrant legal | Spark-2 | Spark-1 has no observed Qdrant runtime |
| LiteLLM gateway | Spark-2 | Spark-1 has no observed LiteLLM runtime |
| Redis | Spark-2 active; Spark-1 also running local Redis | Legal app consumers observed on Spark-2 |
| Inference | Spark-1 and Spark-2 both participate | Spark-1 runs NIM sovereign and Ray worker; Spark-2 runs Ollama/LiteLLM/Ray head |

## Next Foundation Moves

1. Remediate and rotate the exposed Spark-1 NGC credential.
2. Add an explicit Spark-1 cutover gate before any doc claims Spark-1 is the active Legal host.
3. Verify live LiteLLM alias ownership and reconcile Spark-5 vs Spark-3+4 vs Spark-1 inference docs.
4. Verify Qdrant alias/read/write contract for `legal_ediscovery_active` and v2.
5. Reconcile `nas_layout` shape across migration, batch ingest, and legal case API.
