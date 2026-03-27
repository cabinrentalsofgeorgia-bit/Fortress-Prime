# Strike 8 — Redirect Vanguard (Strangler Fig Edge)

## Purpose

Intercepts **`cabin-rentals-of-georgia.com`** at Cloudflare before Drupal. For paths matching **`/cabins/{slug}`**, the Worker looks up **`slug`** in **Workers KV**. If present, the request is **proxied** to the **sovereign Next.js** deployment (e.g. Vercel) while the **browser URL stays on the apex domain**.

All **other paths** are proxied to the **Drupal origin**, preserving **legacy 301 redirects** and unmigrated behavior (including the historical redirect map).

## Components

| Piece | Role |
|--------|------|
| **`gateway/redirect-vanguard-worker.mjs`** | Cloudflare Worker (Switchman). |
| **`gateway/wrangler.redirect-vanguard.toml`** | Wrangler config + KV binding. |
| **`backend/services/redirect_vanguard_kv.py`** | Cloudflare REST API: upsert/delete slug. |
| **`backend/services/seo_deploy_consumer.py`** | After successful deploy + revalidate, **upserts slug into KV**. |
| **`POST /api/internal/redirect-vanguard/kv/full-sync`** | Super-admin: rebuild KV from all `seo_patches.status = deployed`. |
| **`DELETE /api/internal/redirect-vanguard/kv/slug/{slug}`** | Super-admin: remove one slug from KV. |

## Cloudflare dashboard

1. **Workers KV** → Create namespace **`SOVEREIGN_DEPLOYED_SLUGS`** (name is cosmetic; binding is `DEPLOYED_SLUGS`).
2. **API Token** with **Workers KV Storage → Edit** (and account read if required).
3. Deploy Worker; attach route e.g. **`cabin-rentals-of-georgia.com/*`** only when authorized.

## DGX / API environment

```bash
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_KV_NAMESPACE_DEPLOYED_SLUGS=...
```

If unset, deploy still succeeds; KV sync is skipped (logged at debug).

## First cutover (example)

1. Approve + deploy SEO patch for property slug **`the-rivers-edge`** (existing pipeline).
2. Deploy consumer writes KV key **`the-rivers-edge`** = `1`.
3. Worker route live → **`/cabins/the-rivers-edge`** serves Next.js; rest of site remains Drupal.

## Full resync

```bash
curl -X POST -H "Authorization: Bearer <staff_jwt>" \
  https://<api-host>/api/internal/redirect-vanguard/kv/full-sync
```

## Doctrine

- **Do not** break the **4,530 legacy 301s**: non–cabin paths and unmigrated slugs continue to hit Drupal.
- **Internal ops** stay on **crog-ai.com**; this Worker is **public storefront** only.
