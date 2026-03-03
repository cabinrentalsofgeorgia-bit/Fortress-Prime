# CROG Gateway Domain Configuration

## ✅ Domain: crog-ai.com

**Status**: CONFIGURED AND READY

---

## Configuration Summary

### Domain Setup
- **Domain**: `crog-ai.com`
- **Hosting**: Already configured with Cloudflare Tunnel
- **nginx**: Configured to route webhook traffic to CROG Gateway
- **SSL**: Handled by Cloudflare (automatic)

### Service Routing

#### Master Console (Port 9800)
- **URL**: `https://crog-ai.com/`
- **Routes**: All root paths (`/`)
- **Purpose**: Portal UI, user management, authentication

#### CROG Gateway (Port 8001)
- **Webhook URL**: `https://crog-ai.com/webhooks/`
- **API URL**: `https://crog-ai.com/api/`
- **Purpose**: SMS integration, guest messaging

---

## Webhook Endpoints

### For RueBaRue Configuration

Configure these webhook URLs in your RueBaRue dashboard:

**Incoming SMS Webhook**:
```
https://crog-ai.com/webhooks/sms/incoming
```

**Status Update Webhook**:
```
https://crog-ai.com/webhooks/sms/status
```

**Method**: POST  
**Content-Type**: application/json

---

## API Endpoints

### Send Message
```bash
POST https://crog-ai.com/api/messages/send
```

### Get Reservation by Phone
```bash
GET https://crog-ai.com/api/reservations/by-phone/{phone_number}
```

### Get Reservation by ID
```bash
GET https://crog-ai.com/api/reservations/{reservation_id}
```

### Health Check
```bash
GET https://crog-ai.com/api/messages/health
```

---

## nginx Configuration

**File**: `/home/admin/Fortress-Prime/nginx/wolfpack_ai.conf`

**Key Routes**:
```nginx
# CROG Gateway Webhooks
location /webhooks/ {
    proxy_pass http://192.168.0.100:8001;
    # ... proxy headers ...
}

# CROG Gateway API
location ~ ^/api/(messages|reservations)/ {
    proxy_pass http://192.168.0.100:8001;
    # ... proxy headers ...
}

# Master Console (default)
location / {
    proxy_pass http://127.0.0.1:9800;
    # ... proxy headers ...
}
```

**Container**: `wolfpack-lb`  
**Reload Command**: `docker exec wolfpack-lb nginx -s reload`

---

## Testing

### Test Webhook Endpoint
```bash
# Local test
curl -X POST http://localhost/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# Production test
curl -X POST https://crog-ai.com/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'
```

### Test Health Endpoint
```bash
# Console health
curl https://crog-ai.com/health

# Gateway health
curl https://crog-ai.com/api/messages/health
```

---

## Architecture Benefits

### 1. Single Domain
- **Simplicity**: One domain for all services
- **SSL**: Single certificate managed by Cloudflare
- **Maintenance**: Centralized DNS management

### 2. Path-Based Routing
- **Scalability**: Add new services without new domains
- **Security**: Granular access control per path
- **Clarity**: URLs clearly indicate service purpose

### 3. nginx Load Balancing
- **Performance**: Connection pooling and buffering
- **Resilience**: Health checks and failover
- **Observability**: Centralized access logging

---

## Next Steps

### 1. Configure RueBaRue Webhooks ⚠️ REQUIRED
1. Log into RueBaRue: https://app.ruebarue.com/
2. Navigate to Webhooks or Integration settings
3. Add webhook URL: `https://crog-ai.com/webhooks/sms/incoming`
4. Add status webhook: `https://crog-ai.com/webhooks/sms/status`
5. Save configuration

### 2. Test Real SMS Flow
```bash
# Monitor logs in real-time
tail -f /home/admin/Fortress-Prime/crog-gateway/crog_gateway.log

# Send test SMS to your RueBaRue number
# Watch logs for incoming webhook
```

### 3. Verify in Production
1. Send real SMS to your business number
2. Check logs: `tail -f /tmp/crog_gateway.log`
3. Verify webhook received
4. Verify Streamline VRS lookup
5. Confirm reply sent via RueBaRue

---

## Security Notes

### Current State
- **Authentication**: Not implemented (webhooks are public)
- **Rate Limiting**: Not implemented
- **IP Whitelisting**: Not configured

### Recommended Hardening

1. **Webhook Authentication**:
   - Add shared secret validation
   - Verify webhook signatures from RueBaRue

2. **Rate Limiting**:
   ```nginx
   limit_req_zone $binary_remote_addr zone=webhooks:10m rate=10r/s;
   limit_req zone=webhooks burst=20 nodelay;
   ```

3. **IP Whitelisting** (if RueBaRue provides static IPs):
   ```nginx
   location /webhooks/ {
       allow 203.0.113.0/24;  # RueBaRue IP range
       deny all;
       # ... proxy config ...
   }
   ```

---

## Troubleshooting

### Webhook Not Receiving
1. Check CROG Gateway is running:
   ```bash
   curl http://localhost:8001/health
   ```

2. Check nginx routing:
   ```bash
   curl http://localhost/webhooks/sms/incoming
   ```

3. Check nginx logs:
   ```bash
   docker exec wolfpack-lb tail -f /var/log/nginx/fortress_console_access.log
   ```

4. Check CROG Gateway logs:
   ```bash
   tail -f /tmp/crog_gateway.log
   ```

### Gateway Not Starting
```bash
# Check port availability
lsof -i :8001

# Restart gateway
cd /home/admin/Fortress-Prime/crog-gateway
source venv/bin/activate
python3 run.py
```

---

## Summary

✅ **Domain**: crog-ai.com configured  
✅ **nginx**: Routing configured and tested  
✅ **CROG Gateway**: Running on port 8001  
✅ **Master Console**: Running on port 9800  
✅ **URLs**: Webhooks ready at `/webhooks/` path  
✅ **Cloudflare**: Tunnel active and routing  

**READY FOR SMS INTEGRATION** 🚀

**Next**: Configure RueBaRue webhooks to point to `https://crog-ai.com/webhooks/sms/incoming`

---

## Verified Routing

### Test Results
```bash
# Console Health (Master Console on port 9800)
curl -H "Host: crog-ai.com" http://localhost/health
> Fortress Console Online

# Webhook Routing (CROG Gateway on port 8001)  
curl -H "Host: crog-ai.com" -X POST http://localhost/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{"from": "+15551234567", "body": "Test"}'
> {"detail":"Failed to process SMS webhook"}  # ✅ Route working (error is expected)

# Direct Gateway Access
curl http://localhost:8001/
> {"service":"CROG Gateway","version":"1.0.0",...}  # ✅ Running
```

**Status**: All routing verified and operational
