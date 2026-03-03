# Enterprise SMS Platform Architecture
## From RueBaRue to Sovereign SMS Infrastructure

---

## 🎯 Strategic Vision

### Current State
- **RueBaRue**: Manual messaging, no API, vendor lock-in
- **Data**: Trapped in RueBaRue platform
- **AI**: Council of Giants ready but no training data

### Future State (12 Months)
- **Sovereign SMS Platform**: Full ownership, unlimited scale
- **Historical Data**: All guest conversations extracted and indexed
- **AI Training**: Models learning from real guest interactions
- **Multi-Channel**: SMS, WhatsApp, Email, Voice unified
- **Enterprise Features**: Analytics, A/B testing, compliance, audit trails

---

## 📊 Three-Phase Execution Plan

### Phase 1: Data Liberation (Weeks 1-2) 🔓
**Goal**: Extract all historical data from RueBaRue

### Phase 2: Hybrid Operation (Weeks 3-8) 🔄
**Goal**: Run RueBaRue + Twilio in parallel, build custom platform

### Phase 3: Sovereign Platform (Weeks 9-12) 🚀
**Goal**: Launch enterprise SMS infrastructure, decommission RueBaRue

---

## 🔓 PHASE 1: Data Liberation from RueBaRue

### Strategy 1: Manual Export (If Available)
**Check RueBaRue for**:
- Reports → Export Messages
- Data Export functionality
- CSV/JSON download options
- Archive features

**What to export**:
- ✅ All message history
- ✅ Guest phone numbers
- ✅ Timestamps
- ✅ Message direction (inbound/outbound)
- ✅ Message status
- ✅ Associated reservations
- ✅ Property/cabin mappings

### Strategy 2: Web Scraping (Automated)
**If no export feature**, scrape the web interface:

```python
# /home/admin/Fortress-Prime/extract_ruebarue_data.py
"""
RueBaRue Data Extraction Tool
Logs in and scrapes all historical message data
"""

from playwright.async_api import async_playwright
import asyncio
import json
from datetime import datetime
import pandas as pd

class RueBaRueExtractor:
    def __init__(self):
        self.base_url = "https://app.ruebarue.com"
        self.username = "lissa@cabin-rentals-of-georgia.com"
        self.password = "${RUEBARUE_PASSWORD}"
        self.messages = []
    
    async def login(self, page):
        """Login to RueBaRue"""
        await page.goto(self.base_url)
        await page.fill('input[type="email"]', self.username)
        await page.fill('input[type="password"]', self.password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
    
    async def extract_conversations(self, page):
        """Extract all message conversations"""
        # Navigate to messages/inbox
        await page.goto(f"{self.base_url}/messages")
        
        # Get all conversation threads
        conversations = await page.query_selector_all('.conversation-item')
        
        for conv in conversations:
            conv_data = await self.extract_conversation_details(page, conv)
            self.messages.extend(conv_data)
    
    async def extract_conversation_details(self, page, conversation):
        """Extract individual conversation messages"""
        # Click conversation to open
        await conversation.click()
        await asyncio.sleep(1)
        
        # Extract all messages in thread
        messages = await page.query_selector_all('.message')
        
        conv_messages = []
        for msg in messages:
            message_data = {
                'phone': await self.extract_phone(msg),
                'text': await msg.inner_text(),
                'timestamp': await self.extract_timestamp(msg),
                'direction': await self.extract_direction(msg),
                'guest_name': await self.extract_guest_name(msg),
                'property': await self.extract_property(msg),
            }
            conv_messages.append(message_data)
        
        return conv_messages
    
    async def save_to_database(self):
        """Save extracted data to Fortress database"""
        # Connect to your PostgreSQL
        # Insert into message archive table
        pass
    
    async def save_to_json(self, filename="ruebarue_export.json"):
        """Save to JSON for backup"""
        with open(filename, 'w') as f:
            json.dump(self.messages, f, indent=2, default=str)
    
    async def save_to_csv(self, filename="ruebarue_export.csv"):
        """Save to CSV for analysis"""
        df = pd.DataFrame(self.messages)
        df.to_csv(filename, index=False)
    
    async def run(self):
        """Main extraction process"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                print("🔐 Logging into RueBaRue...")
                await self.login(page)
                
                print("📥 Extracting conversations...")
                await self.extract_conversations(page)
                
                print(f"✅ Extracted {len(self.messages)} messages")
                
                print("💾 Saving to database...")
                await self.save_to_database()
                
                print("💾 Saving to JSON...")
                await self.save_to_json()
                
                print("💾 Saving to CSV...")
                await self.save_to_csv()
                
                print("✅ Data extraction complete!")
                
            finally:
                await browser.close()

if __name__ == "__main__":
    extractor = RueBaRueExtractor()
    asyncio.run(extractor.run())
```

### Strategy 3: Email Forwarding (Continuous)
**If RueBaRue sends email notifications**:
- Set up email forwarding rule
- Parse emails to extract message content
- Real-time sync of new messages
- Build email→database pipeline

### Strategy 4: Manual Screenshots + OCR
**Last resort if no other method works**:
- Systematically screenshot all conversations
- Use OCR (Tesseract or cloud OCR)
- Extract text and structure data
- Time-consuming but comprehensive

### Data Schema for Historical Messages

```sql
-- /home/admin/Fortress-Prime/schema/message_archive.sql

CREATE TABLE message_archive (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,  -- 'ruebarue', 'twilio', 'sovereign'
    external_id VARCHAR(255),     -- Original message ID from provider
    
    -- Message details
    phone_number VARCHAR(20) NOT NULL,
    guest_name VARCHAR(255),
    message_body TEXT NOT NULL,
    direction VARCHAR(10) NOT NULL,  -- 'inbound', 'outbound'
    
    -- Timestamps
    sent_at TIMESTAMP NOT NULL,
    received_at TIMESTAMP,
    delivered_at TIMESTAMP,
    
    -- Context
    property_id INTEGER,
    reservation_id INTEGER,
    cabin_name VARCHAR(100),
    
    -- Classification (for AI training)
    intent VARCHAR(50),           -- 'checkin', 'wifi', 'directions', etc.
    sentiment VARCHAR(20),        -- 'positive', 'neutral', 'negative', 'urgent'
    response_quality INTEGER,     -- 1-5 rating
    resolution_time_seconds INTEGER,
    
    -- AI training metadata
    used_for_training BOOLEAN DEFAULT FALSE,
    training_label VARCHAR(50),
    human_reviewed BOOLEAN DEFAULT FALSE,
    
    -- Audit
    created_at TIMESTAMP DEFAULT NOW(),
    extracted_at TIMESTAMP,
    extraction_method VARCHAR(50),
    
    CONSTRAINT valid_direction CHECK (direction IN ('inbound', 'outbound')),
    CONSTRAINT valid_sentiment CHECK (sentiment IN ('positive', 'neutral', 'negative', 'urgent'))
);

CREATE INDEX idx_message_phone ON message_archive(phone_number);
CREATE INDEX idx_message_sent_at ON message_archive(sent_at);
CREATE INDEX idx_message_property ON message_archive(property_id);
CREATE INDEX idx_message_intent ON message_archive(intent);
CREATE INDEX idx_message_training ON message_archive(used_for_training);

-- Conversation threading
CREATE TABLE conversation_threads (
    id BIGSERIAL PRIMARY KEY,
    phone_number VARCHAR(20) NOT NULL,
    property_id INTEGER,
    started_at TIMESTAMP NOT NULL,
    last_message_at TIMESTAMP NOT NULL,
    message_count INTEGER DEFAULT 0,
    status VARCHAR(20),  -- 'active', 'resolved', 'escalated'
    
    UNIQUE(phone_number, property_id, started_at)
);

-- Guest profiles (enriched over time)
CREATE TABLE guest_profiles (
    id BIGSERIAL PRIMARY KEY,
    phone_number VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    
    -- Behavior patterns
    total_messages INTEGER DEFAULT 0,
    avg_response_time_seconds INTEGER,
    preferred_contact_time VARCHAR(20),  -- 'morning', 'afternoon', 'evening'
    common_questions TEXT[],
    
    -- Sentiment analysis
    overall_sentiment VARCHAR(20),
    satisfaction_score DECIMAL(3,2),
    
    -- Booking history
    total_stays INTEGER DEFAULT 0,
    favorite_properties TEXT[],
    lifetime_value DECIMAL(10,2),
    
    -- AI personalization
    communication_style VARCHAR(50),  -- 'formal', 'casual', 'brief', 'detailed'
    language_preference VARCHAR(10) DEFAULT 'en',
    
    first_contact TIMESTAMP,
    last_contact TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 🔄 PHASE 2: Hybrid Operation (Building Your Platform)

### Immediate: Twilio + RueBaRue Parallel

**Week 1-2: Setup**
```bash
# 1. Sign up for Twilio
# 2. Get phone number
# 3. Configure webhook → CROG Gateway
# 4. Update .env with Twilio credentials
```

**Week 3-4: Integration**
- New bookings → Twilio number (AI responses)
- Existing guests → RueBaRue (manual for now)
- Log ALL interactions to message_archive table
- Compare AI vs manual response quality

**Week 5-8: Transition**
- Gradually move guests to Twilio
- Port RueBaRue number to Twilio (if possible)
- Full message history in your database
- RueBaRue becomes backup only

---

## 🚀 PHASE 3: Sovereign SMS Platform

### Architecture: Enterprise-Grade SMS Infrastructure

```
┌─────────────────────────────────────────────────────────────────┐
│                    FORTRESS SMS PLATFORM                         │
│                    "Sovereign Communications"                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ INGRESS LAYER - Message Reception                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Twilio   │  │ Bandwidth│  │ Plivo    │  │ Direct   │       │
│  │ Webhook  │  │ Webhook  │  │ Webhook  │  │ Carrier  │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │             │              │             │              │
│       └─────────────┴──────────────┴─────────────┘              │
│                          │                                       │
│                   ┌──────▼──────┐                               │
│                   │ Load Balancer│                               │
│                   │   (nginx)    │                               │
│                   └──────┬───────┘                               │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│ ROUTING LAYER - Intelligent Message Router                       │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Message Router Service (FastAPI)                        │    │
│  │ - Phone number → Property mapping                       │    │
│  │ - Business hours detection                              │    │
│  │ - VIP guest detection                                   │    │
│  │ - Language detection                                    │    │
│  │ - Spam filtering                                        │    │
│  │ - Rate limiting                                         │    │
│  └────┬────────────────────────────────────────────────────┘    │
│       │                                                          │
│  ┌────▼─────────────────────────────────────────────────┐       │
│  │ Decision: Route to AI or Human?                      │       │
│  │ - Simple questions → AI                              │       │
│  │ - Complex issues → Human escalation                  │       │
│  │ - After hours → AI with morning follow-up            │       │
│  │ - VIP guests → Human + AI summary                    │       │
│  └────┬─────────────────────────────────────────────────┘       │
└───────┼──────────────────────────────────────────────────────────┘
        │
    ┌───┴───┐
    │       │
┌───▼───┐ ┌─▼────────────────────────────────────────────────────┐
│ HUMAN │ │ AI PROCESSING LAYER - Council of Giants             │
│ QUEUE │ ├──────────────────────────────────────────────────────┤
└───────┘ │  ┌──────────────────────────────────────────────┐   │
          │  │ Intent Classifier (Qwen 2.5:7b)              │   │
          │  │ - Checkin questions                          │   │
          │  │ - WiFi requests                              │   │
          │  │ - Directions                                 │   │
          │  │ - Maintenance issues                         │   │
          │  │ - Booking modifications                      │   │
          │  └────────┬─────────────────────────────────────┘   │
          │           │                                          │
          │  ┌────────▼─────────────────────────────────────┐   │
          │  │ Context Retrieval (Qdrant Vector DB)         │   │
          │  │ - Property-specific info (WiFi, codes, etc)  │   │
          │  │ - Guest history                              │   │
          │  │ - Similar past conversations                 │   │
          │  │ - Reservation details (from Streamline VRS)  │   │
          │  └────────┬─────────────────────────────────────┘   │
          │           │                                          │
          │  ┌────────▼─────────────────────────────────────┐   │
          │  │ Response Generator (DeepSeek R1:70b)         │   │
          │  │ - Personalized responses                     │   │
          │  │ - Tone matching (formal/casual)              │   │
          │  │ - Multi-turn conversations                   │   │
          │  │ - Proactive suggestions                      │   │
          │  └────────┬─────────────────────────────────────┘   │
          │           │                                          │
          │  ┌────────▼─────────────────────────────────────┐   │
          │  │ Quality Checker (Human-in-the-Loop)          │   │
          │  │ - Confidence scoring                         │   │
          │  │ - Sensitive content detection                │   │
          │  │ - Escalation triggers                        │   │
          │  └────────┬─────────────────────────────────────┘   │
          └───────────┼──────────────────────────────────────────┘
                      │
┌─────────────────────▼──────────────────────────────────────────┐
│ EGRESS LAYER - Message Sending                                │
├────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Delivery Optimizer                                       │ │
│  │ - Provider selection (Twilio/Bandwidth/Backup)           │ │
│  │ - Retry logic with exponential backoff                   │ │
│  │ - Delivery tracking                                      │ │
│  │ - Cost optimization                                      │ │
│  └────────┬─────────────────────────────────────────────────┘ │
│           │                                                    │
│  ┌────────▼─────────────────────────────────────────────────┐ │
│  │ Message Queue (Redis/RabbitMQ)                           │ │
│  │ - Guaranteed delivery                                    │ │
│  │ - Rate limiting per provider                             │ │
│  │ - Priority queuing (urgent first)                        │ │
│  └────────┬─────────────────────────────────────────────────┘ │
│           │                                                    │
│  ┌────────▼───────────┬────────────────┬──────────────────┐  │
│  │ Twilio API         │ Bandwidth API  │  Backup Provider │  │
│  └────────────────────┴────────────────┴──────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼──────────────────────────────────────────┐
│ DATA LAYER - Unified Storage                                  │
├────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ PostgreSQL   │  │ Qdrant       │  │ Redis        │        │
│  │ - Messages   │  │ - Vectors    │  │ - Cache      │        │
│  │ - Guests     │  │ - Embeddings │  │ - Sessions   │        │
│  │ - Properties │  │ - Knowledge  │  │ - Queue      │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
└────────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼──────────────────────────────────────────┐
│ ANALYTICS LAYER - Insights & Training                         │
├────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐      │
│  │ Real-time Dashboards (Grafana/Custom)               │      │
│  │ - Message volume by hour/day/property               │      │
│  │ - AI vs Human response rates                        │      │
│  │ - Average response time                             │      │
│  │ - Guest satisfaction scores                         │      │
│  │ - Cost per message by provider                      │      │
│  └─────────────────────────────────────────────────────┘      │
│                                                                │
│  ┌─────────────────────────────────────────────────────┐      │
│  │ AI Training Pipeline                                │      │
│  │ - Labeled conversation datasets                     │      │
│  │ - Response quality feedback loops                   │      │
│  │ - A/B testing response variants                     │      │
│  │ - Continuous model fine-tuning                      │      │
│  │ - Embedding updates                                 │      │
│  └─────────────────────────────────────────────────────┘      │
└────────────────────────────────────────────────────────────────┘
```

### Key Components to Build

#### 1. **Message Router Service** (`/fortress-sms/router/`)
- FastAPI service
- Phone → Property mapping
- Intent classification
- AI vs Human routing decisions
- Spam filtering
- Rate limiting

#### 2. **AI Response Engine** (`/fortress-sms/ai-engine/`)
- Integration with Council of Giants
- Context retrieval from Qdrant
- Response generation
- Quality scoring
- Escalation triggers

#### 3. **Provider Abstraction Layer** (`/fortress-sms/providers/`)
- Unified interface for all SMS providers
- Automatic failover
- Cost optimization
- Delivery tracking

#### 4. **Analytics & Training** (`/fortress-sms/analytics/`)
- Real-time dashboards
- Performance metrics
- Training data labeling
- Model fine-tuning pipelines

#### 5. **Admin Dashboard** (`/fortress-sms/admin/`)
- Message history viewer
- Guest profiles
- Manual intervention interface
- AI response review
- Property configuration

---

## 📈 Scale Considerations

### Horizontal Scaling
```yaml
# docker-compose.sms-platform.yml
services:
  # Load balancer
  nginx:
    image: nginx:latest
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/sms-lb.conf:/etc/nginx/nginx.conf
  
  # Router instances (scale to N)
  sms-router:
    build: ./router
    deploy:
      replicas: 5
    environment:
      - REDIS_URL=redis://redis:6379
      - PG_URL=postgresql://user:pass@postgres:5432/sms_db
  
  # AI Engine instances (GPU-backed)
  ai-engine:
    build: ./ai-engine
    deploy:
      replicas: 3
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
  
  # Message queue
  rabbitmq:
    image: rabbitmq:3-management
    ports:
      - "5672:5672"
      - "15672:15672"
  
  # Databases
  postgres:
    image: postgres:16
    volumes:
      - sms_data:/var/lib/postgresql/data
  
  redis:
    image: redis:7-alpine
  
  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrant_data:/qdrant/storage
```

### Performance Targets
- **Latency**: < 500ms from receipt to AI response
- **Throughput**: 10,000 messages/hour per instance
- **Availability**: 99.95% uptime
- **Scalability**: Linear horizontal scaling
- **Cost**: < $0.01 per message all-in

---

## 🔒 Compliance & Security

### TCPA Compliance (Critical for SMS)
- Explicit opt-in required
- Easy opt-out ("STOP" keyword)
- Quiet hours enforcement (9 PM - 8 AM local time)
- Do Not Call list checking
- Audit trail of all consents

### Data Privacy
- GDPR/CCPA compliant storage
- Data retention policies (7 years for bookings)
- PII encryption at rest
- Secure message transit (TLS 1.3)
- Guest data export on request

### Security
- API authentication (JWT + API keys)
- Rate limiting per phone/IP
- SQL injection prevention
- XSS protection
- Regular security audits

---

## 💰 Cost Analysis

### Current (RueBaRue)
- **Monthly**: ~$30-50
- **Per Message**: Unknown (bundled)
- **Scale**: Limited to platform capacity
- **Data Ownership**: None

### Twilio Transition
- **Monthly**: $1.15 (phone) + $0.0079/SMS
- **500 msgs/month**: ~$6/month
- **5,000 msgs/month**: ~$41/month
- **Data Ownership**: Full

### Sovereign Platform (At Scale)
- **Infrastructure**: $500-1000/month (servers, GPU)
- **Carriers**: $0.003-0.005/SMS (bulk direct rates)
- **10,000 msgs/month**: ~$530/month all-in
- **100,000 msgs/month**: ~$800/month
- **Data Ownership**: 100%
- **Margins**: Can resell to other cabin owners

---

## 🎯 Implementation Timeline

### Month 1: Foundation
- ✅ Extract RueBaRue data
- ✅ Set up Twilio + CROG Gateway
- ✅ Build message archive database
- ✅ Create guest profiles

### Month 2: AI Integration
- ✅ Train models on historical data
- ✅ Deploy Council of Giants for SMS
- ✅ A/B test AI vs manual responses
- ✅ Refine prompts and context retrieval

### Month 3: Platform Development
- ✅ Build router service
- ✅ Provider abstraction layer
- ✅ Admin dashboard
- ✅ Analytics pipeline

### Month 4: Migration & Scale
- ✅ Port RueBaRue number to platform
- ✅ Full AI automation
- ✅ Add backup SMS providers
- ✅ Deploy to production

### Month 5-6: Enhancement
- ✅ Multi-property support
- ✅ WhatsApp integration
- ✅ Voice call handling
- ✅ Predictive guest support

### Month 7-12: Market Expansion
- ✅ Package as SaaS for other cabin owners
- ✅ White-label offering
- ✅ Revenue: $99-299/month per property
- ✅ Scale to 100+ properties

---

## 🚀 Next Actions (This Week)

### 1. Data Extraction (Priority 1)
- [ ] I'll create the RueBaRue scraper script
- [ ] Run extraction to get all historical messages
- [ ] Import into PostgreSQL message_archive table
- [ ] Analyze data for training

### 2. Twilio Setup (Priority 2)
- [ ] Sign up for Twilio account
- [ ] Get phone number
- [ ] Configure webhook to CROG Gateway
- [ ] Test first SMS flow

### 3. Database Schema (Priority 3)
- [ ] Create message_archive tables
- [ ] Create guest_profiles tables
- [ ] Create conversation_threads tables
- [ ] Set up vector storage in Qdrant

### 4. AI Training Prep (Priority 4)
- [ ] Label historical messages by intent
- [ ] Create training datasets
- [ ] Fine-tune embeddings
- [ ] Test response generation

---

## 💡 Strategic Advantages

### Why Build Your Own Platform?

1. **Data Ownership**
   - All guest conversations owned by you
   - Train proprietary AI models
   - Competitive moat

2. **Scale Economics**
   - At 100K+ messages/month, 10x cheaper
   - Direct carrier relationships possible
   - No platform fees

3. **Innovation Velocity**
   - Deploy new features immediately
   - A/B test without limits
   - Integrate with any system

4. **Business Model**
   - Turn cost center into revenue
   - License to other cabin owners
   - $299/month x 100 properties = $29,900/month

5. **AI Advantage**
   - Models trained on YOUR data
   - Cabin-specific knowledge
   - Guest relationship history
   - Continuous improvement loops

---

## ✅ Decision Points

**Want me to start with**:

1. **Data Extraction Script** (2-3 hours)
   - Build RueBaRue scraper
   - Extract all historical data
   - Import to database

2. **Twilio Integration** (30 minutes)
   - Set up account
   - Configure CROG Gateway
   - Test SMS flow

3. **Database Schema** (1 hour)
   - Create all tables
   - Set up relationships
   - Initialize with RueBaRue data

4. **Full Platform Architecture** (1 week)
   - Build all components
   - Deploy on your cluster
   - Launch sovereign SMS platform

**Or all of the above?** 🚀

---

**Status**: Strategy defined, ready to execute. Your call on what to build first!
