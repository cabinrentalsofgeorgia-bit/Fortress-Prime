# Quick Reference: URLs and Endpoints

## Production URLs (crog-ai.com)

### Master Console
```
https://crog-ai.com/
```
**Purpose**: Portal UI, user management, AI dashboards  
**Login**: admin2 / 190AntiochCemeteryRD!

### CROG Gateway Webhooks
```
https://crog-ai.com/webhooks/sms/incoming    # ← Configure in RueBaRue
https://crog-ai.com/webhooks/sms/status      # ← Optional: Status updates
```

### CROG Gateway API
```
POST   https://crog-ai.com/api/messages/send
GET    https://crog-ai.com/api/reservations/by-phone/{phone}
GET    https://crog-ai.com/api/reservations/{id}
```

---

## Local Development

### Master Console
```bash
http://localhost:9800/
```

### CROG Gateway
```bash
http://localhost:8001/                      # Info endpoint
http://localhost:8001/health               # Health check
http://localhost:8001/docs                 # Interactive API docs (Swagger)
http://localhost:8001/webhooks/sms/incoming   # Webhook endpoint
```

---

## Testing Commands

### Test Production (via nginx + Cloudflare)
```bash
# Console health
curl https://crog-ai.com/health

# Webhook (requires valid RueBaRue payload)
curl -X POST https://crog-ai.com/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{"from": "+15551234567", "body": "Test message"}'
```

### Test Local (direct to services)
```bash
# Console health
curl http://localhost:9800/health

# Gateway health
curl http://localhost:8001/health

# Gateway webhook
curl -X POST http://localhost:8001/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{"from": "+15551234567", "body": "Test message"}'
```

### Test nginx Routing (localhost via nginx)
```bash
# Console (requires Host header)
curl -H "Host: crog-ai.com" http://localhost/health

# Gateway webhook (requires Host header)
curl -H "Host: crog-ai.com" -X POST http://localhost/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'
```

---

## Service Ports

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| Master Console | 9800 | HTTP | Portal UI |
| CROG Gateway | 8001 | HTTP | SMS Integration |
| nginx (wolfpack-lb) | 80 | HTTP | Reverse Proxy |
| Cloudflare Tunnel | - | HTTPS | Public Access |

---

## RueBaRue Configuration

**Portal**: https://app.ruebarue.com/  
**Username**: `lissa@cabin-rentals-of-georgia.com`  
**Password**: `${RUEBARUE_PASSWORD}`

**Configure These Webhooks**:
1. Incoming SMS: `https://crog-ai.com/webhooks/sms/incoming`
2. Status Updates: `https://crog-ai.com/webhooks/sms/status` (optional)

---

## Log Files

```bash
# CROG Gateway application logs
tail -f /tmp/crog_gateway.log

# nginx access logs (all requests)
docker exec wolfpack-lb tail -f /var/log/nginx/fortress_console_access.log

# nginx error logs
docker exec wolfpack-lb tail -f /var/log/nginx/fortress_console_error.log

# Master Console logs
tail -f /home/admin/Fortress-Prime/logs/fortress_console.log  # (if configured)
```

---

## Configuration Files

```bash
# CROG Gateway environment
/home/admin/Fortress-Prime/crog-gateway/.env

# nginx configuration
/home/admin/Fortress-Prime/nginx/wolfpack_ai.conf

# Master Console (if needed)
/home/admin/Fortress-Prime/config.py
```

---

## Quick Commands

### Restart CROG Gateway
```bash
# Stop
pkill -f "run.py"

# Start
cd /home/admin/Fortress-Prime/crog-gateway
source venv/bin/activate
python3 run.py &

# Verify
curl http://localhost:8001/health
```

### Reload nginx
```bash
docker exec wolfpack-lb nginx -s reload
```

### Check Service Status
```bash
# CROG Gateway
ps aux | grep "run.py" | grep -v grep

# Master Console
ps aux | grep "app.py" | grep -v grep

# nginx
docker ps | grep wolfpack-lb
```

---

## Architecture

```
Internet
  ↓
Cloudflare Tunnel (HTTPS → crog-ai.com)
  ↓
nginx (wolfpack-lb container, port 80)
  ↓
  ├─→ /webhooks/* → CROG Gateway (port 8001)
  ├─→ /api/messages/* → CROG Gateway (port 8001)
  ├─→ /api/reservations/* → CROG Gateway (port 8001)
  └─→ /* → Master Console (port 9800)
```

---

## Need Help?

**CROG Gateway not responding?**
```bash
curl http://localhost:8001/health
```

**nginx not routing?**
```bash
docker exec wolfpack-lb nginx -t  # Test config
docker exec wolfpack-lb nginx -s reload  # Reload
```

**RueBaRue webhooks not arriving?**
```bash
# Check nginx logs
docker exec wolfpack-lb tail -f /var/log/nginx/fortress_console_access.log | grep webhooks

# Check CROG Gateway logs
tail -f /tmp/crog_gateway.log
```

---

**Status**: ✅ All systems configured and operational  
**Domain**: crog-ai.com active  
**Next Step**: Configure RueBaRue webhooks
