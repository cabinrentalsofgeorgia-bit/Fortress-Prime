# Captain Cloudflared Runbook

This runbook captures the verified stable Cloudflare Tunnel posture on the Captain host after tunnel recovery, transport hardening, and package-source remediation.

## Verified Stable Posture

- Host: `spark-node-2` / Captain
- Tunnel: `Fortress-Prime`
- Tunnel ID: `aa7222a3-c1c9-4ee3-97c8-fb46b41a654e`
- Package source: official Cloudflare apt repo for `noble`
- Package version: `cloudflared 2026.3.0`
- Service: `cloudflared.service`
- Transport: pinned `http2`
- Startup guard: `ExecStartPre=/usr/bin/cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate`
- Stable state: `4` HA connections, `0` request errors, repeated `HTTP/2 200` on `https://crog-ai.com/login`

## Active Config

### Service unit

- `/etc/systemd/system/cloudflared.service`

```ini
[Service]
ExecStart=/usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml tunnel run
Restart=on-failure
RestartSec=5s
```

### Service drop-in

- `/etc/systemd/system/cloudflared.service.d/override.conf`

```ini
[Service]
ExecStartPre=/usr/bin/cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
```

### Tunnel config

- `/etc/cloudflared/config.yml`

```yaml
tunnel: aa7222a3-c1c9-4ee3-97c8-fb46b41a654e
credentials-file: /etc/cloudflared/aa7222a3-c1c9-4ee3-97c8-fb46b41a654e.json
protocol: http2

ingress:
  - hostname: ssh.crog-ai.com
    service: ssh://localhost:22
  - hostname: www.crog-ai.com
    service: http://127.0.0.1:3001
  - hostname: crog-ai.com
    service: http://127.0.0.1:3001
  - hostname: api.cabin-rentals-of-georgia.com
    service: http://localhost:8100
  - service: http_status:404
```

## Command Center build (Next.js standalone)

`output: "standalone"` does not copy `/.next/static` or `/public` into the standalone bundle. If HTML loads but the UI is blank, `/_next/static/chunks/*.js` is returning **404** from Node until assets are synced.

- The workspace `build` script runs `next build` and then `fortress-guest-platform/scripts/sync-next-standalone-assets.mjs`.
- After deploying a new build: `sudo systemctl restart fortress-frontend.service` so the server picks up fresh files.

## www hostname and edge cache

If `https://crog-ai.com/login` works but `https://www.crog-ai.com/login` returns **404** from Cloudflare (while `cloudflared` ingress already lists `www.crog-ai.com`), the usual cause is **DNS**: `www` was proxied without a **CNAME to the tunnel**. Repair from the Captain host (credentials must allow DNS write):

```bash
cloudflared tunnel route dns --overwrite-dns aa7222a3-c1c9-4ee3-97c8-fb46b41a654e www.crog-ai.com
```

After DNS or origin fixes, Cloudflare may still serve a **cached 404** for `/_next/static/*` on `www`. Purge cache for that hostname in the dashboard, or request with a cache-busting query string to confirm origin is healthy.

## Why This Posture Is Pinned

The prior failure pattern was intermittent QUIC instability: handshake timeouts, stream/datagram failures, and full connection collapse. Pinning `protocol: http2` removed that control-plane churn on this host and produced a clean five-minute stability watch after the package upgrade.

## Recovery Commands

### One-command smoke

```bash
cd /home/admin/Fortress-Prime
./scripts/verify_captain_cloudflared.sh
```

### Service status

```bash
systemctl status cloudflared.service --no-pager
cloudflared --version
cloudflared tunnel info aa7222a3-c1c9-4ee3-97c8-fb46b41a654e
```

### Metrics check

```bash
python3 - <<'PY'
import urllib.request
text = urllib.request.urlopen('http://127.0.0.1:20241/metrics', timeout=5).read().decode()
for key in (
    'cloudflared_tunnel_ha_connections',
    'cloudflared_tunnel_request_errors',
    'cloudflared_tunnel_total_requests',
):
    for line in text.splitlines():
        if line.startswith(key + ' '):
            print(line)
            break
PY
```

### Public reachability check

```bash
curl -I --max-time 15 https://crog-ai.com/login
```

### Restart path

```bash
sudo systemctl daemon-reload
sudo systemctl restart cloudflared.service
systemctl status cloudflared.service --no-pager
```

## Package Source

The host now uses the official Cloudflare apt repository for `Ubuntu 24.04 noble`.

- keyring: `/usr/share/keyrings/cloudflare-main.gpg`
- source list: `/etc/apt/sources.list.d/cloudflared.list`

Expected repo entry:

```bash
deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared noble main
```

Standard upgrade path:

```bash
sudo apt-get update
sudo apt-get install -y cloudflared
```

## Known Non-Blocking Warnings

- `ICMP proxy feature is disabled`
- `ping_group_range` warning for group `0`

Those warnings did not prevent stable tunnel registration or public reachability in the validated `http2` posture.
