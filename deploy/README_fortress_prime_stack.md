# Fortress Prime Stack

This compose stack is the container baseline for typed API tools and local-first AI routing:

- `fortress-backend` (FastAPI app with `/api/v1/*` tool endpoints)
- `postgres` (PostgreSQL 16)
- `redis` (event bus / queue support)
- `qdrant` (vector storage)
- `litellm` (model gateway)

## Start

```bash
cd deploy
docker compose -f fortress-prime-compose.yaml up -d
```

## Notes

- Keep `AUDIT_LOG_SIGNING_KEY` set in production so OpenShell logs remain cryptographically signed.
- Privacy routing is enforced in backend AI fallback; cloud calls receive redacted payloads only.
- For full sovereign mode, route LiteLLM providers to local models on your DGX cluster.
