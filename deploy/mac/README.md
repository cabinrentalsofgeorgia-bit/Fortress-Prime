# Mac Mini SOTA setup

One-time clone and launchd setup for the CROG stack on the Mac Mini (master_console on :9800, AI gateway on :8090).

**You can do all of this from Cursor:** open `~/AI-Projects` or the repo in Cursor, use the integrated terminal or ask the agent to run the steps below.

---

## Pre-flight (before setup)

Ensure a **`.env`** file exists in the repo root (e.g. `~/AI-Projects/Fortress-Prime-SOTA/.env`) with `JWT_SECRET` and any database credentials. The launchd wrapper sources this so the Command Center can start; without it the process will exit and launchd will restart it in a loop.

---

## Prerequisites

- **GitHub access:** Either SSH (key in `~/.ssh` and added to GitHub under Settings → SSH and GPG keys) or HTTPS with a [Personal Access Token](https://github.com/settings/tokens) as password when cloning.
- **Xcode Command Line Tools** or **Homebrew** if you need `git` or `nginx` (Apple Silicon often has nginx via Homebrew at `/opt/homebrew/bin/nginx`).

Test SSH: `ssh -T git@github.com`

---

## One-time clone

From your chosen parent directory (e.g. `~/AI-Projects`):

```bash
cd ~/AI-Projects
git clone git@github.com:cabinrentalsofgeorgia-bit/Fortress-Prime.git Fortress-Prime-SOTA
cd Fortress-Prime-SOTA
git checkout main
```

If you don’t use SSH, clone via HTTPS (GitHub will prompt for username and PAT as password):

```bash
git clone https://github.com/cabinrentalsofgeorgia-bit/Fortress-Prime.git Fortress-Prime-SOTA
cd Fortress-Prime-SOTA
git checkout main
```

---

## One-time setup

From the **repo root** (e.g. `~/AI-Projects/Fortress-Prime-SOTA`):

```bash
./deploy/mac/setup.sh
```

`setup.sh` will:

1. Create `/var/log/crog` and set ownership to your user.
2. Substitute `__SOTA_REPO__` and `__SOTA_USER__` in the launchd plists and install them to `/Library/LaunchDaemons`.
3. Load `com.crog.master_console` (FastAPI on :9800) and `com.crog.ai_gateway` (Nginx on :8090).

It infers the repo path from the script location, so it works for any install path (e.g. `~/AI-Projects/Fortress-Prime-SOTA`). You may be prompted for `sudo` for system daemons.

---

## Verification (telemetry check)

After setup, verify the Brain and AI Gateway are up:

```bash
# Check launchd registered the services
launchctl list | grep crog

# Verify FastAPI (Command Center) is up
curl -I http://127.0.0.1:9800

# Verify Nginx (AI Gateway) is routing to the Sparks
curl -s http://127.0.0.1:8090/v1/models
```

You should see the two launchd jobs, a successful HTTP response from :9800, and a response from :8090 (or 502 if Sparks are not up yet). Logs: `/var/log/crog/`.

**If you get 502 on :8090:** Another Nginx may be bound to 8090 (e.g. `nginx -c .../nginx/fortress_legal_gateway.conf`), which proxies to a different subnet (10.10.10.x). Stop it (`pkill -f "nginx.*fortress_legal_gateway"` or kill the nginx master PID from `ps aux | grep nginx`), then run `sudo launchctl kickstart -k system/com.crog.ai_gateway` so the CROG gateway (192.168.0.x upstreams) runs on 8090.
