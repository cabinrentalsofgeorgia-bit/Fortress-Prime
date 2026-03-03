# RueBaRue Webhook Manual Configuration Guide

## 📸 Analysis from Automation Attempt

The automation script captured the login page but couldn't proceed past login. This suggests RueBaRue may have:
- CAPTCHA verification
- Two-factor authentication (2FA)
- JavaScript-based login protection
- Session-based security

**Manual configuration required.**

---

## 🔐 Step-by-Step Configuration

### Step 1: Login to RueBaRue

1. **Open your browser** and navigate to:
   ```
   https://app.ruebarue.com/
   ```

2. **Login with your credentials**:
   - **Email**: `lissa@cabin-rentals-of-georgia.com`
   - **Password**: `${RUEBARUE_PASSWORD}`

3. **Complete any 2FA** if prompted

---

### Step 2: Find Webhook/Integration Settings

Once logged in, look for one of these menu items (usually in the left sidebar or top navigation):

**Most Likely Locations**:
- ⚙️ **Settings** → **Webhooks**
- ⚙️ **Settings** → **Integrations**
- 🔧 **Account** → **API** or **Webhooks**
- 🔗 **Integrations** → **Webhooks**
- 👨‍💻 **Developer** → **Webhooks** or **API**

**Alternative Locations**:
- Click your profile/account icon (usually top-right)
- Look for **Account Settings** or **Preferences**
- Check for an **Admin** or **Advanced** section

---

### Step 3: Configure Incoming SMS Webhook

When you find the webhook configuration page:

1. **Look for**: "Incoming Messages", "Inbound SMS", "Received Messages", or similar

2. **Enter this webhook URL**:
   ```
   https://crog-ai.com/webhooks/sms/incoming
   ```

3. **HTTP Method**: Should be `POST` (this is usually default)

4. **Content-Type**: Should be `application/json` (usually default)

5. **Webhook Events**: Select or enable:
   - ✅ Incoming SMS
   - ✅ Message Received
   - ✅ Inbound Message

---

### Step 4: Configure Status Webhook (Optional but Recommended)

If there's an option for delivery status webhooks:

1. **Look for**: "Delivery Status", "Message Status", "Status Updates", "Outbound Status"

2. **Enter this webhook URL**:
   ```
   https://crog-ai.com/webhooks/sms/status
   ```

3. **Webhook Events**: Select or enable:
   - ✅ Message Sent
   - ✅ Message Delivered
   - ✅ Message Failed

---

### Step 5: Save and Test

1. **Click Save** or **Update** button

2. **Test the webhook** (if RueBaRue provides a test function):
   - Look for "Test Webhook" or "Send Test Event"
   - Click it to send a test payload

3. **Verify on your end**:
   ```bash
   # Watch CROG Gateway logs
   tail -f /tmp/crog_gateway.log
   
   # You should see the test webhook arrive
   ```

---

## 🔍 What to Look For

### Webhook Configuration Page Examples

The webhook page typically shows fields like:

```
┌─────────────────────────────────────────────┐
│ Incoming SMS Webhook                        │
├─────────────────────────────────────────────┤
│ URL: [_______________________________]      │
│ Method: [POST ▼]                            │
│ Events: ☑ Message Received                  │
│         ☑ SMS Inbound                        │
│ Status: ● Active                            │
│                                             │
│ [Test Webhook] [Save]                       │
└─────────────────────────────────────────────┘
```

### Common Field Names

Look for input fields labeled:
- "Webhook URL"
- "Callback URL"
- "POST URL"
- "Endpoint"
- "Notification URL"
- "HTTP Endpoint"

---

## 📝 Information to Document

While you're in the RueBaRue dashboard, please note:

### 1. Webhook Payload Format
Look for documentation showing:
- What fields are sent in the webhook payload
- Example JSON structure
- Field names (e.g., `from`, `body`, `messageId`, etc.)

### 2. Authentication
Check if webhooks require:
- API key in headers
- Shared secret for signature verification
- Basic authentication
- Bearer token

### 3. Phone Number Configuration
Find your RueBaRue phone number(s):
- What number guests will text
- If multiple numbers, which one for cabin inquiries
- Any number formatting requirements

### 4. Rate Limits
Check if there are:
- Webhook delivery rate limits
- SMS sending limits
- API call limits

---

## 🧪 Testing the Webhook

### Test 1: RueBaRue Built-in Test
If available, use their test feature first.

### Test 2: Real SMS Test
```bash
# Start monitoring logs
tail -f /tmp/crog_gateway.log

# Send an SMS from your phone to the RueBaRue number
# Message: "Test webhook"

# You should see in logs:
# - Incoming webhook received
# - Phone number extracted
# - Streamline VRS lookup (will fail if not configured)
# - Response generated
```

### Test 3: Manual Webhook Test
```bash
# Send a test webhook directly to CROG Gateway
curl -X POST https://crog-ai.com/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+15551234567",
    "to": "+15559876543",
    "body": "Test message",
    "messageId": "test_123",
    "timestamp": "2026-02-16T12:00:00Z"
  }'

# Check logs
tail -20 /tmp/crog_gateway.log
```

---

## ⚠️ Troubleshooting

### Issue: Can't Find Webhook Settings

**Try**:
1. Search in the RueBaRue interface for "webhook", "API", or "integration"
2. Check RueBaRue documentation or help center
3. Contact RueBaRue support: "How do I configure webhooks for incoming SMS?"

### Issue: Webhook Not Firing

**Check**:
1. Webhook URL is exactly: `https://crog-ai.com/webhooks/sms/incoming`
2. Webhook is enabled/active in RueBaRue
3. CROG Gateway is running:
   ```bash
   curl http://localhost:8001/health
   ```
4. nginx is routing correctly:
   ```bash
   curl -H "Host: crog-ai.com" http://localhost/webhooks/sms/incoming
   ```
5. Cloudflare Tunnel is active:
   ```bash
   curl https://crog-ai.com/health
   ```

### Issue: Webhook Returns Error

**Check logs**:
```bash
# CROG Gateway logs
tail -50 /tmp/crog_gateway.log | grep error

# nginx logs
docker exec wolfpack-lb tail -50 /var/log/nginx/fortress_console_error.log
```

---

## 📸 Screenshot Checklist

Please take screenshots of:

1. ✅ RueBaRue dashboard (to see menu structure)
2. ✅ Webhook configuration page
3. ✅ Webhook settings showing the URL saved
4. ✅ Any documentation about webhook payload format
5. ✅ Phone number(s) configured in your account

Save them in `/home/admin/Fortress-Prime/ruebarue_screenshots/` and I can review them.

---

## 🎯 Expected Webhook Payload

Based on common SMS platforms, RueBaRue likely sends:

```json
{
  "from": "+15551234567",
  "to": "+15559876543",
  "body": "What's the WiFi password?",
  "messageId": "msg_abc123",
  "timestamp": "2026-02-16T12:00:00Z",
  "status": "received"
}
```

**Key fields we need**:
- `from` - Guest's phone number
- `body` - Message text
- `messageId` - For tracking

If the payload format is different, we'll need to update the CROG Gateway webhook handler.

---

## 🔄 Next Steps After Configuration

1. **Webhook URL added** to RueBaRue → ✅
2. **Send test SMS** to verify webhook
3. **Configure Streamline VRS** credentials in CROG Gateway
4. **Test full flow**: SMS → Webhook → Lookup → Reply
5. **Monitor for 24 hours** to ensure stability

---

## 🆘 Need Help?

If you encounter any issues:

1. **Document what you see**:
   - Take screenshots
   - Note exact error messages
   - Copy any configuration options

2. **Share with me**:
   - Put screenshots in `/home/admin/Fortress-Prime/ruebarue_screenshots/`
   - Tell me what options you see
   - Describe any error messages

3. **I can help**:
   - Interpret RueBaRue's documentation
   - Update CROG Gateway to match their payload format
   - Debug webhook delivery issues
   - Configure alternative approaches

---

## Summary

✅ **Login**: https://app.ruebarue.com/  
✅ **Email**: lissa@cabin-rentals-of-georgia.com  
✅ **Password**: ${RUEBARUE_PASSWORD}  
✅ **Webhook URL**: https://crog-ai.com/webhooks/sms/incoming  
✅ **Status URL**: https://crog-ai.com/webhooks/sms/status  

**Action Required**: Manual login and webhook configuration

Once configured, send a test SMS and run:
```bash
tail -f /tmp/crog_gateway.log
```

Good luck! Let me know what you find and I'll help with any issues.
