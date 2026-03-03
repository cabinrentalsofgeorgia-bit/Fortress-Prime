# Fortress SMS Platform
## Sovereign Enterprise SMS Infrastructure

Complete enterprise-grade SMS platform with AI integration, multi-provider support, and comprehensive analytics.

---

## 🏗️ Architecture

```
fortress-sms/
├── router/              # Message routing service (FastAPI)
├── ai-engine/           # Council of Giants AI integration
├── providers/           # SMS provider abstraction layer
├── analytics/           # Real-time analytics & dashboards
├── admin/               # Admin web interface
├── database/            # Database migrations & schemas
├── docker/              # Docker configurations
└── docs/                # Documentation
```

---

## 🚀 Quick Start

### 1. Data Extraction from RueBaRue
```bash
cd /home/admin/Fortress-Prime
source venv_browser/bin/activate
python3 src/extract_ruebarue_data.py --mode full --export all
```

### 2. Initialize Database
```bash
psql -U miner_bot -d fortress_db -f schema/sms_platform_schema.sql
```

### 3. Configure Twilio (Temporary Provider)
```bash
# Sign up at https://www.twilio.com/
# Get Account SID, Auth Token, Phone Number

# Update .env
cd /home/admin/Fortress-Prime/crog-gateway
nano .env

# Add:
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+15551234567
```

### 4. Start CROG Gateway with Twilio
```bash
cd /home/admin/Fortress-Prime/crog-gateway
source venv/bin/activate
python3 run.py &

# Test webhook
curl -X POST http://localhost:8001/webhooks/sms/incoming \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "MessageSid=SMxxxxxxxxx&From=+15551234567&To=+15559876543&Body=Test message"
```

---

## 📊 Features

### Phase 1: Foundation (Current)
- ✅ RueBaRue data extraction
- ✅ Message archive database
- ✅ Twilio integration
- ✅ CROG Gateway webhooks
- ✅ Basic routing

### Phase 2: AI Integration (In Progress)
- 🔄 Council of Giants for SMS
- 🔄 Intent classification
- 🔄 Context retrieval from Qdrant
- 🔄 Response generation
- 🔄 Quality scoring

### Phase 3: Enterprise Features (Planned)
- ⏳ Multi-provider support
- ⏳ Admin dashboard
- ⏳ Real-time analytics
- ⏳ A/B testing
- ⏳ Cost optimization

---

## 🔧 Components

### 1. Message Router (`/router`)
- Receives incoming SMS from all providers
- Routes to AI or human based on rules
- Handles business hours, VIP guests, etc.
- Queue management for high volume

### 2. AI Engine (`/ai-engine`)
- Intent classification (Qwen 2.5:7b)
- Context retrieval (Qdrant vector DB)
- Response generation (DeepSeek R1:70b)
- Quality checking
- Escalation triggers

### 3. Provider Layer (`/providers`)
- Twilio adapter
- Bandwidth adapter
- Plivo adapter
- Direct carrier integration (future)
- Automatic failover
- Cost optimization

### 4. Analytics (`/analytics`)
- Real-time dashboards (Grafana)
- Performance metrics
- Cost tracking
- Guest satisfaction
- AI performance

### 5. Admin Dashboard (`/admin`)
- Message history viewer
- Guest profiles
- Manual intervention
- AI response review
- Property configuration

---

## 💾 Database Schema

### Core Tables
- `message_archive` - All messages from all sources
- `conversation_threads` - Grouped message sequences
- `guest_profiles` - Enriched guest data
- `sms_providers` - Multi-provider configuration
- `property_sms_config` - Per-property settings
- `ai_training_labels` - Human-labeled training data
- `message_analytics` - Pre-aggregated stats

See `/schema/sms_platform_schema.sql` for complete schema.

---

## 🔄 Data Flow

### Inbound Message Flow
```
SMS Provider (Twilio)
  ↓ Webhook
CROG Gateway (nginx → port 8001)
  ↓
Message Router
  ↓
├─→ AI Engine (Council of Giants)
│    ├─→ Intent Classifier
│    ├─→ Context Retrieval (Qdrant)
│    ├─→ Response Generator
│    └─→ Quality Checker
│         ├─→ Approve → Send
│         └─→ Escalate → Human Queue
│
└─→ Human Queue (Manual review)
     └─→ Send Response
```

### Outbound Message Flow
```
Response (AI or Human)
  ↓
Provider Selector (Cost optimization)
  ↓
Message Queue (Redis)
  ↓
SMS Provider (Twilio/Bandwidth/etc)
  ↓
Delivery Tracking
  ↓
Message Archive (Database)
```

---

## 🎯 Deployment

### Development
```bash
cd /home/admin/Fortress-Prime/fortress-sms
docker-compose -f docker-compose.dev.yml up
```

### Production
```bash
cd /home/admin/Fortress-Prime/fortress-sms
docker-compose -f docker-compose.prod.yml up -d
```

### Scaling
```bash
# Scale router instances
docker-compose up --scale router=10

# Scale AI engine instances
docker-compose up --scale ai-engine=5
```

---

## 📈 Performance

### Targets
- **Latency**: < 500ms receipt to AI response
- **Throughput**: 10,000 messages/hour per instance
- **Availability**: 99.95% uptime
- **Cost**: < $0.01 per message all-in

### Current
- **Latency**: ~800ms (needs optimization)
- **Throughput**: ~1,000 messages/hour
- **Availability**: 99.5%
- **Cost**: $0.0079/message (Twilio only)

---

## 💰 Cost Analysis

### Per Message Costs
| Provider | Cost/SMS | Setup | Monthly | Notes |
|----------|----------|-------|---------|-------|
| Twilio | $0.0079 | $0 | $1.15 | Best docs, most reliable |
| Bandwidth | $0.0050 | $0 | $500 min | Enterprise, volume only |
| Plivo | $0.0065 | $0 | $0.80 | Good alternative |
| Direct Carrier | $0.003 | $5,000 | $0 | Requires volume (100K+/month) |

### Platform Costs (At Scale)
- **Infrastructure**: $500-1000/month (GPU cluster, databases)
- **SMS**: $0.003-0.008/message (depends on provider mix)
- **10K msgs/month**: ~$560/month
- **100K msgs/month**: ~$800/month
- **1M msgs/month**: ~$3,500/month

### Revenue Potential (White-Label)
- **License per property**: $299/month
- **100 properties**: $29,900/month
- **Margin**: ~$26,000/month profit at 100 properties

---

## 🔒 Security & Compliance

### TCPA Compliance
- ✅ Explicit opt-in required
- ✅ Easy opt-out ("STOP" keyword)
- ✅ Quiet hours enforcement (9 PM - 8 AM)
- ✅ Do Not Call list checking
- ✅ Audit trail of consents

### Data Privacy
- ✅ GDPR/CCPA compliant
- ✅ Data retention policies
- ✅ PII encryption at rest
- ✅ TLS 1.3 in transit
- ✅ Guest data export on request

### API Security
- ✅ JWT authentication
- ✅ API key rotation
- ✅ Rate limiting
- ✅ SQL injection prevention
- ✅ XSS protection

---

## 📚 Documentation

- [Architecture Deep Dive](./docs/ARCHITECTURE.md)
- [API Reference](./docs/API.md)
- [Deployment Guide](./docs/DEPLOYMENT.md)
- [Provider Integration](./docs/PROVIDERS.md)
- [AI Training Pipeline](./docs/AI_TRAINING.md)

---

## 🆘 Support

**Issues**: Create issue in repository
**Docs**: See `/docs` folder
**Questions**: Contact development team

---

## 📝 License

Proprietary - Fortress Prime LLC

---

**Status**: Phase 1 Complete, Phase 2 In Progress
**Next**: Deploy AI engine, build admin dashboard
