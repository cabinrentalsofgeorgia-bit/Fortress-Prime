# Complete SMS Platform Setup Guide
## From RueBaRue to Enterprise Platform in 4 Phases

---

## 📋 Overview

This guide walks you through the complete transformation from RueBaRue (manual SMS) to a sovereign enterprise SMS platform with AI automation.

**Timeline**: 1-2 weeks for full deployment
**Effort**: ~20 hours total
**Result**: Enterprise SMS platform with AI, multi-provider support, analytics

---

## 🎯 What You'll Build

### Phase 1: Data Liberation ✅ READY
Extract all historical guest conversations from RueBaRue for AI training

### Phase 2: Twilio Integration ✅ READY
Get SMS working with Twilio as your provider (30 minutes)

### Phase 3: Hybrid Operation 🔄 IN PROGRESS
Run RueBaRue + Twilio in parallel, build custom platform components

### Phase 4: Sovereign Platform ⏳ PLANNED
Launch your own enterprise SMS infrastructure

---

## ✅ PHASE 1: Data Liberation (30-60 minutes)

### What This Does
Extracts ALL historical messages from RueBaRue including:
- Guest conversations
- Phone numbers
- Timestamps
- Inbound/outbound messages
- Property associations

### Step-by-Step

#### 1. Activate Browser Environment
```bash
cd /home/admin/Fortress-Prime
source venv_browser/bin/activate
```

#### 2. Run Data Extraction
```bash
python3 src/extract_ruebarue_data.py --mode full --export all
```

**What happens**:
- Script logs into RueBaRue
- Navigates to messages/conversations
- Extracts all message data
- Saves to:
  - `/home/admin/Fortress-Prime/data/ruebarue_export.json`
  - `/home/admin/Fortress-Prime/data/ruebarue_export.csv`
  - PostgreSQL `message_archive` table

#### 3. Review Extracted Data
```bash
# Check extraction summary
cat /home/admin/Fortress-Prime/data/extraction_summary.json

# View sample messages
head -20 /home/admin/Fortress-Prime/data/ruebarue_export.csv

# Check database
psql -U miner_bot -d fortress_db -c "SELECT COUNT(*) FROM message_archive WHERE source='ruebarue';"
```

#### 4. Troubleshooting

**If extraction gets stuck at login**:
- RueBaRue may have CAPTCHA or 2FA
- Check screenshots in `/home/admin/Fortress-Prime/data/ruebarue_*.png`
- Manual fallback: Export from RueBaRue dashboard if available

**If no messages found**:
- Check `/home/admin/Fortress-Prime/data/ruebarue_page_content.html`
- RueBaRue may have changed their HTML structure
- Contact for script updates

---

## ✅ PHASE 2: Twilio Integration (30 minutes)

### Prerequisites
- Credit card (for Twilio account)
- $0-15 (Twilio gives $15 free credit)

### Step-by-Step

#### 1. Run Automated Setup Script
```bash
cd /home/admin/Fortress-Prime
./setup_twilio.sh
```

**The script will**:
- Prompt for Twilio Account SID
- Prompt for Auth Token
- Prompt for Phone Number
- Update `.env` configuration
- Test API connection
- Restart CROG Gateway
- Verify webhook endpoint

#### 2. Manual Twilio Account Setup (If needed)

**A. Sign up for Twilio**:
1. Go to https://www.twilio.com/try-twilio
2. Create account with email
3. Verify phone number
4. Get $15 free credit

**B. Get Phone Number**:
1. Twilio Console → Phone Numbers → Buy a Number
2. Search for local number in your area
3. Purchase ($1.15/month)
4. Note the number in E.164 format (e.g., +15551234567)

**C. Get Credentials**:
1. Twilio Console → Account Dashboard
2. Copy Account SID
3. Copy Auth Token (click "Show")

**D. Configure Webhook**:
1. Click your phone number
2. Scroll to "Messaging"
3. Set "A MESSAGE COMES IN":
   - URL: `https://crog-ai.com/webhooks/sms/incoming`
   - Method: `POST`
4. Save configuration

#### 3. Test Integration
```bash
# Check CROG Gateway is running
curl http://localhost:8001/health

# Monitor logs
tail -f /tmp/crog_gateway.log

# Send test SMS to your Twilio number
# From your phone: Text "Test message" to your Twilio number

# You should see in logs:
# - Webhook received
# - Phone number extracted
# - Streamline VRS lookup (may fail if not configured yet)
# - Response generated
```

#### 4. Verify Through Cloudflare
```bash
# Test via public URL
curl -X POST https://crog-ai.com/webhooks/sms/incoming \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "MessageSid=TEST&From=+15551234567&Body=Hello"

# Should return TwiML response
```

---

## 🔄 PHASE 3: Hybrid Operation (1-2 weeks)

### Week 1: Parallel Systems

#### 1. Configure Both Systems
- **RueBaRue**: Keep for existing guests, manual overflow
- **Twilio + AI**: Use for new bookings, test AI responses

#### 2. Update Guest Communications
```
New booking confirmation:
"Welcome to [Cabin Name]! 
For immediate assistance, text us at: [Twilio Number]
Our AI assistant is available 24/7 to help with:
- Check-in information
- WiFi passwords
- Directions
- Property questions"
```

#### 3. Monitor Both Systems
```bash
# CROG Gateway / Twilio
tail -f /tmp/crog_gateway.log

# RueBaRue
# Check web interface manually
```

#### 4. Compare Performance
Track these metrics:
- Response time (AI vs Manual)
- Guest satisfaction
- Resolution rate
- Time saved

### Week 2: Full Migration

#### 1. Port RueBaRue Number to Twilio (Optional)
- Contact Twilio support
- Provide RueBaRue number
- Transfer takes 1-2 weeks
- Cost: ~$5-15 one-time fee

#### 2. Update All Listings
- Update Airbnb/VRBO profiles
- Update booking confirmations
- Update website
- Update printed materials

#### 3. Decommission RueBaRue
- Export final data
- Cancel subscription
- Archive account info

---

## ⏳ PHASE 4: Sovereign Platform (Weeks 3-12)

### What You'll Build

#### 1. Multi-Provider Support
- Add Bandwidth.com for backup
- Add Plivo for international
- Direct carrier integration (future)
- Automatic failover

#### 2. Advanced AI Integration
- Fine-tune models on your historical data
- Property-specific knowledge bases
- Guest personalization
- Proactive messaging

#### 3. Analytics Dashboard
- Real-time message volume
- AI performance metrics
- Cost tracking
- Guest satisfaction scores
- Revenue impact

#### 4. Admin Interface
- Web dashboard for message management
- Guest profile viewer
- Manual intervention tools
- AI response review
- Property configuration

### Components to Deploy

```bash
# 1. Message Router
cd /home/admin/Fortress-Prime/fortress-sms/router
docker-compose up -d

# 2. AI Engine
cd /home/admin/Fortress-Prime/fortress-sms/ai-engine
docker-compose up -d

# 3. Analytics
cd /home/admin/Fortress-Prime/fortress-sms/analytics
docker-compose up -d

# 4. Admin Dashboard
cd /home/admin/Fortress-Prime/fortress-sms/admin
docker-compose up -d
```

---

## 📊 Success Metrics

### Week 1 Targets
- ✅ Twilio integrated and receiving messages
- ✅ 100% of test messages delivered
- ✅ < 2 second response time
- ✅ RueBaRue data fully extracted

### Month 1 Targets
- ✅ 50% of guests on Twilio/AI system
- ✅ 90% AI success rate (no human escalation needed)
- ✅ Guest satisfaction ≥ 4.5/5
- ✅ 80% reduction in manual time

### Month 3 Targets
- ✅ 100% of guests on sovereign platform
- ✅ Multi-provider redundancy
- ✅ Analytics dashboard live
- ✅ 95% AI success rate
- ✅ < $0.01 per message cost

---

## 💰 Cost Breakdown

### Setup Costs (One-Time)
- Twilio number: $1.15
- Number porting (optional): $5-15
- Development time: Your own time
- **Total**: ~$10-20

### Monthly Operating Costs

**At 500 messages/month**:
- Twilio: $1.15 (phone) + $4 (messages) = $5.15/month
- Infrastructure: Included in existing cluster
- **Total**: ~$5-10/month

**At 5,000 messages/month**:
- Twilio: $1.15 (phone) + $40 (messages) = $41/month
- Infrastructure: $50/month (dedicated resources)
- **Total**: ~$90/month

**At 50,000 messages/month**:
- Multi-provider: ~$250/month
- Infrastructure: $500/month
- **Total**: ~$750/month

### Cost Savings vs RueBaRue
| Volume | RueBaRue | Sovereign | Savings |
|--------|----------|-----------|---------|
| 500/mo | $30-50 | $5-10 | $25-40/mo |
| 5,000/mo | $100-200 | $90 | $10-110/mo |
| 50,000/mo | $1,000+ | $750 | $250+/mo |

Plus: **10-20 hours/month saved** in manual messaging time

---

## 🆘 Troubleshooting

### Twilio Not Receiving Messages

**Check 1**: Webhook configured?
```bash
# Should see webhook URL in Twilio console
```

**Check 2**: CROG Gateway running?
```bash
curl http://localhost:8001/health
```

**Check 3**: nginx routing?
```bash
curl -H "Host: crog-ai.com" http://localhost/webhooks/sms/incoming
```

**Check 4**: Cloudflare Tunnel active?
```bash
curl https://crog-ai.com/health
```

### AI Responses Not Working

**Check 1**: AI enabled in .env?
```bash
grep ENABLE_AI_REPLIES /home/admin/Fortress-Prime/crog-gateway/.env
# Should show: ENABLE_AI_REPLIES=true
```

**Check 2**: Council of Giants running?
```bash
curl http://localhost:11434/api/tags
```

**Check 3**: Qdrant running?
```bash
curl http://localhost:6333/collections
```

### Data Extraction Failed

**Check 1**: Browser automation working?
```bash
source /home/admin/Fortress-Prime/venv_browser/bin/activate
playwright --version
```

**Check 2**: RueBaRue credentials correct?
```bash
# Check in src/extract_ruebarue_data.py
```

**Check 3**: Review screenshots
```bash
ls -lh /home/admin/Fortress-Prime/data/ruebarue_*.png
```

---

## 📚 Additional Resources

### Documentation
- `ENTERPRISE_SMS_PLATFORM_ARCHITECTURE.md` - Full technical architecture
- `ALTERNATIVE_SMS_PROVIDERS.md` - Provider comparison
- `fortress-sms/README.md` - Platform overview

### Scripts
- `setup_twilio.sh` - Automated Twilio setup
- `src/extract_ruebarue_data.py` - Data extraction tool
- `schema/sms_platform_schema.sql` - Database schema

### Monitoring
```bash
# CROG Gateway logs
tail -f /tmp/crog_gateway.log

# Database queries
psql -U miner_bot -d fortress_db

# System resources
htop
nvidia-smi
```

---

## ✅ Checklist

### Phase 1: Data Liberation
- [ ] Activate venv_browser environment
- [ ] Run extract_ruebarue_data.py
- [ ] Verify data in /data folder
- [ ] Check database for imported messages
- [ ] Review extraction summary

### Phase 2: Twilio Integration
- [ ] Sign up for Twilio account
- [ ] Get phone number
- [ ] Run ./setup_twilio.sh
- [ ] Configure webhook in Twilio console
- [ ] Send test SMS
- [ ] Verify logs show message received

### Phase 3: Hybrid Operation
- [ ] Keep RueBaRue active for existing guests
- [ ] Use Twilio for new bookings
- [ ] Monitor both systems daily
- [ ] Compare AI vs manual performance
- [ ] Collect guest feedback

### Phase 4: Sovereign Platform
- [ ] Plan multi-provider setup
- [ ] Deploy analytics dashboard
- [ ] Build admin interface
- [ ] Migrate all guests to sovereign platform
- [ ] Decommission RueBaRue

---

## 🎯 Next Steps

**Right Now**:
1. Run data extraction: `python3 src/extract_ruebarue_data.py`
2. Set up Twilio: `./setup_twilio.sh`
3. Send test SMS
4. Monitor logs

**This Week**:
1. Enable AI responses in .env
2. Configure Streamline VRS credentials
3. Test full guest interaction flow
4. Collect metrics

**This Month**:
1. Migrate 50% of guests to Twilio
2. Fine-tune AI on historical data
3. Build analytics dashboard
4. Plan full migration

---

**Status**: All tools ready, scripts created, database prepared
**Action**: Run Phase 1 and Phase 2 now - takes ~1 hour total

🚀 **Let's go! Start with**: `python3 src/extract_ruebarue_data.py --mode full`
