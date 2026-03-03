# RueBaRue Webhook Configuration Guide

## Quick Setup

### Step 1: Login to RueBaRue
**URL**: https://app.ruebarue.com/  
**Username**: `lissa@cabin-rentals-of-georgia.com`  
**Password**: `${RUEBARUE_PASSWORD}`

### Step 2: Navigate to Webhooks
Look for settings like:
- **Webhooks**
- **Integrations**  
- **API Settings**
- **Developer Settings**

### Step 3: Configure Webhook URLs

#### Incoming SMS Webhook
```
https://crog-ai.com/webhooks/sms/incoming
```

**Purpose**: Receives incoming guest text messages  
**Method**: POST  
**Content-Type**: application/json

**Expected Payload** (RueBaRue format):
```json
{
  "from": "+15551234567",
  "to": "+15559876543",
  "body": "What's the WiFi password?",
  "messageId": "msg_123456",
  "timestamp": "2026-02-16T12:00:00Z"
}
```

#### Status Update Webhook (Optional)
```
https://crog-ai.com/webhooks/sms/status
```

**Purpose**: Receives delivery status updates  
**Method**: POST  
**Content-Type**: application/json

**Expected Payload**:
```json
{
  "messageId": "msg_123456",
  "status": "delivered",
  "timestamp": "2026-02-16T12:00:05Z"
}
```

---

## Testing the Integration

### 1. Send Test SMS
Send a text message to your RueBaRue phone number (the one guests text).

### 2. Monitor Logs
```bash
# CROG Gateway logs
tail -f /tmp/crog_gateway.log

# nginx access logs
docker exec wolfpack-lb tail -f /var/log/nginx/fortress_console_access.log
```

### 3. Expected Flow
```
Guest sends SMS
  ↓
RueBaRue receives SMS
  ↓
RueBaRue webhook → https://crog-ai.com/webhooks/sms/incoming
  ↓
nginx routes to CROG Gateway (port 8001)
  ↓
TrafficRouter processes message
  ↓
Lookup reservation in Streamline VRS
  ↓
Generate response (AI or legacy)
  ↓
Send reply via RueBaRue API
  ↓
Guest receives response
```

---

## Webhook Security

### Current State
⚠️ **Webhooks are currently public** (no authentication)

### Recommended: Add Webhook Signature Verification

1. Check if RueBaRue provides webhook signing
2. Add signature verification to CROG Gateway
3. Update `app/api/routes.py`:

```python
import hmac
import hashlib

def verify_ruebarue_signature(payload: str, signature: str, secret: str) -> bool:
    """Verify RueBaRue webhook signature"""
    expected = hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

@router.post("/webhooks/sms/incoming")
async def receive_sms_webhook(request: Request, ...):
    # Get signature from headers
    signature = request.headers.get("X-RueBaRue-Signature")
    
    # Verify before processing
    if not verify_ruebarue_signature(raw_payload, signature, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # ... process webhook ...
```

---

## Troubleshooting

### Webhook Not Arriving

**Check 1**: CROG Gateway running?
```bash
curl http://localhost:8001/health
```

**Check 2**: nginx routing working?
```bash
curl -H "Host: crog-ai.com" -X POST http://localhost/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'
```

**Check 3**: Cloudflare Tunnel active?
```bash
curl https://crog-ai.com/health
# Should return: "Fortress Console Online"
```

**Check 4**: RueBaRue webhook URL correct?
- Must be: `https://crog-ai.com/webhooks/sms/incoming`
- **Not**: `http://` (must use HTTPS)
- **Not**: Missing `/webhooks/` path

### Guest Not Receiving Reply

**Check 1**: RueBaRue credentials correct?
```bash
# Check .env file
cat /home/admin/Fortress-Prime/crog-gateway/.env | grep RUEBARUE
```

**Check 2**: CROG Gateway logs show errors?
```bash
tail -50 /tmp/crog_gateway.log | grep error
```

**Check 3**: Test RueBaRue API directly
```python
import httpx
import base64

# Your credentials
username = "lissa@cabin-rentals-of-georgia.com"
password = "${RUEBARUE_PASSWORD}"
credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

# Test API
async with httpx.AsyncClient() as client:
    response = await client.post(
        "https://app.ruebarue.com/api/v1/sms/send",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json"
        },
        json={
            "to": "+15551234567",  # Your test number
            "body": "Test message from CROG Gateway"
        }
    )
    print(response.status_code, response.text)
```

---

## RueBaRue API Documentation

### Check for Documentation
Look in RueBaRue dashboard for:
- **API Documentation**
- **Developer Guide**
- **Webhook Reference**

### Common API Endpoints
```
GET  /api/v1/messages          # List messages
POST /api/v1/messages/send     # Send SMS
GET  /api/v1/messages/{id}     # Get message details
```

### Authentication
**Type**: Basic Auth  
**Username**: Your RueBaRue email  
**Password**: Your RueBaRue password  

**Header Format**:
```
Authorization: Basic bGlzc2FAY2FiaW4tcmVudGFscy1vZi1nZW9yZ2lhLmNvbTpCZXJhY2hhaDMh
```

---

## Production Checklist

Before going live:

- [ ] RueBaRue webhooks configured
- [ ] Test SMS flow end-to-end
- [ ] Streamline VRS API credentials added
- [ ] Monitor logs for 24 hours
- [ ] Set up alerting for webhook failures
- [ ] Document emergency contact procedure
- [ ] Add webhook signature verification
- [ ] Set up rate limiting in nginx
- [ ] Configure backup SMS provider (if needed)

---

## Emergency Rollback

If CROG Gateway has issues, route directly to legacy:

1. **Disable CROG Gateway in RueBaRue**:
   - Remove webhook URL
   - RueBaRue will hold messages

2. **Or: Enable Pass-Through Mode**:
   ```bash
   # Edit .env
   ENABLE_AI_REPLIES=false
   SHADOW_MODE=false
   
   # Restart gateway
   cd /home/admin/Fortress-Prime/crog-gateway
   pkill -f "run.py"
   source venv/bin/activate
   python3 run.py &
   ```

3. **Monitor Recovery**:
   ```bash
   tail -f /tmp/crog_gateway.log
   ```

---

## Support Contacts

**CROG Gateway Issues**:
- Logs: `/tmp/crog_gateway.log`
- Config: `/home/admin/Fortress-Prime/crog-gateway/.env`

**RueBaRue Issues**:
- Support: https://app.ruebarue.com/support
- Login: `lissa@cabin-rentals-of-georgia.com`

**Cloudflare Issues**:
- Tunnel logs: Check Cloudflare dashboard
- Domain: crog-ai.com

---

## Next Steps

1. ✅ Login to RueBaRue
2. ✅ Find Webhook settings
3. ⚠️ Add incoming webhook URL: `https://crog-ai.com/webhooks/sms/incoming`
4. ⚠️ Save and test with real SMS
5. ⚠️ Monitor logs for first 24 hours
6. ⚠️ Configure Streamline VRS credentials when ready

**Current Status**: Domain configured, ready for webhook setup
