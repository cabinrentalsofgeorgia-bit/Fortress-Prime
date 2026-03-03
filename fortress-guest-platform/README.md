# 🏔️ Fortress Guest Platform (FGP)
## Enterprise Guest Communication System for Cabin Rentals of Georgia

**Status**: 🚧 In Active Development  
**Version**: 1.0.0-alpha  
**Purpose**: Complete replacement for RueBaRue with AI superpowers

---

## 🎯 What This System Does

### Guest Communication
- **Inbound SMS Processing**: Receive and classify guest messages
- **AI-Powered Responses**: Instant, intelligent replies to common questions
- **Message Threading**: Full conversation history per guest
- **Scheduled Messaging**: Automated pre-arrival, check-in, post-stay campaigns

### Guest Lifecycle Management
- **Arrival Tracking**: Know who's arriving today
- **Stay Monitoring**: Proactive check-ins during stays
- **Departure Management**: Automated check-out flows
- **Post-Stay Follow-up**: Review requests, repeat booking offers

### Digital Guestbook
- **Property Guides**: WiFi, access codes, house rules, amenities
- **Area Guides**: Restaurants, attractions, emergency contacts
- **Extras Marketplace**: Upsell firewood, late checkout, etc.

### Operations
- **Work Order Management**: Track maintenance issues
- **Staff Notifications**: Alert team to urgent issues
- **Issue Escalation**: Route problems to right people
- **Analytics Dashboard**: Real-time metrics and trends

---

## 🏗️ Architecture

```
fortress-guest-platform/
├── backend/              # FastAPI application
│   ├── api/             # REST API endpoints
│   ├── models/          # SQLAlchemy models
│   ├── services/        # Business logic
│   ├── integrations/    # External services (Twilio, PMS, AI)
│   └── workers/         # Background tasks
├── frontend/            # React admin dashboard
│   ├── dashboard/       # Staff interface
│   └── guestbook/       # Guest-facing portal
├── database/            # Schema & migrations
├── config/              # Configuration files
└── docs/               # Documentation

Tech Stack:
- Backend: FastAPI (Python 3.12+)
- Database: PostgreSQL 15+
- Cache/Queue: Redis
- Vector DB: Qdrant (for AI/RAG)
- Frontend: React + TypeScript + Tailwind
- SMS: Twilio
- AI: OpenAI GPT-4 / Claude
- Deployment: Docker + Docker Compose
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- PostgreSQL 15+
- Redis
- Node.js 20+ (for frontend)

### Installation
```bash
# 1. Create virtual environment
cd /home/admin/Fortress-Prime/fortress-guest-platform
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment
cp .env.example .env
# Edit .env with your credentials

# 4. Initialize database
python scripts/init_db.py

# 5. Start backend
uvicorn backend.main:app --host 0.0.0.0 --port 8100 --reload

# 6. Start frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Access
- **Admin Dashboard**: http://localhost:3000
- **API**: http://localhost:8100
- **API Docs**: http://localhost:8100/docs
- **Guestbook**: http://crog-ai.com/guest/{reservation_id}

---

## 📊 Feature Status

### Phase 1: Core Platform ✅ (Current)
- [x] Database schema design
- [x] FastAPI backend skeleton
- [x] Guest & Reservation models
- [x] Message threading
- [x] Twilio integration
- [ ] Admin dashboard UI
- [ ] API documentation

### Phase 2: AI Engine (Next)
- [ ] Qdrant vector database
- [ ] Knowledge base ingestion
- [ ] RAG implementation
- [ ] Intent classification
- [ ] Response generation
- [ ] Sentiment analysis

### Phase 3: Lifecycle Automation
- [ ] Message scheduler
- [ ] Pre-arrival automation
- [ ] Check-in/check-out flows
- [ ] Post-stay follow-up
- [ ] Smart scheduling

### Phase 4: Digital Guestbook
- [ ] React frontend
- [ ] SMS magic link auth
- [ ] Property guides
- [ ] Area guides
- [ ] Extras marketplace

### Phase 5: Operations & Analytics
- [ ] Work order system
- [ ] Staff notifications
- [ ] Analytics dashboard
- [ ] Reporting engine

---

## 🔧 Configuration

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/fortress_guest

# Redis
REDIS_URL=redis://localhost:6379/0

# Twilio
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=+17064711479

# OpenAI
OPENAI_API_KEY=your_key

# PMS Integration
STREAMLINE_API_URL=https://api.streamlinevrs.com
STREAMLINE_API_KEY=your_key

# Application
SECRET_KEY=your_secret_key
ENVIRONMENT=development
```

---

## 📱 API Endpoints

### Guests
- `GET /api/guests` - List all guests
- `GET /api/guests/{id}` - Get guest details
- `POST /api/guests` - Create guest
- `GET /api/guests/arriving` - Guests arriving today
- `GET /api/guests/staying` - Current guests
- `GET /api/guests/departing` - Guests leaving today

### Messages
- `GET /api/messages` - List all messages
- `GET /api/messages/thread/{phone}` - Get conversation thread
- `POST /api/messages/send` - Send SMS
- `POST /api/webhooks/sms/incoming` - Twilio webhook

### Reservations
- `GET /api/reservations` - List reservations
- `GET /api/reservations/{id}` - Get reservation
- `POST /api/reservations/sync` - Sync from PMS

### Work Orders
- `GET /api/workorders` - List work orders
- `POST /api/workorders` - Create work order
- `PATCH /api/workorders/{id}` - Update status

### Analytics
- `GET /api/analytics/dashboard` - Dashboard metrics
- `GET /api/analytics/messages` - Message stats
- `GET /api/analytics/satisfaction` - Guest ratings

---

## 🤖 AI Features

### Automatic Response to:
- WiFi password requests
- Access code requests
- Directions/parking questions
- House rules
- Amenities (hot tub, grill, etc)
- Check-in/check-out times
- Local recommendations
- Emergency contacts

### Smart Features:
- **Intent Detection**: Classify messages (info/urgent/booking)
- **Sentiment Analysis**: Detect unhappy guests
- **Context-Aware**: Uses reservation details, property info
- **Learning**: Improves from feedback
- **Escalation**: Routes urgent issues to staff

---

## 🔒 Security

- JWT authentication for admin access
- SMS magic link for guest portal
- Rate limiting on all endpoints
- SQL injection prevention (SQLAlchemy ORM)
- XSS protection
- HTTPS only in production
- Encrypted credentials storage

---

## 📈 Performance

- **Response Time**: < 500ms for API calls
- **SMS Processing**: < 2 seconds end-to-end
- **AI Response**: < 5 seconds (including LLM call)
- **Dashboard Load**: < 1 second
- **Concurrent Users**: 100+ supported

---

## 🆘 Support

- **Documentation**: `/docs` folder
- **API Docs**: http://localhost:8100/docs (Swagger)
- **Logs**: `/var/log/fortress-guest-platform/`
- **Monitoring**: Built-in health checks at `/health`

---

## 📝 License

Proprietary - Cabin Rentals of Georgia  
Built by Fortress AI Systems

---

**Status**: Building Phase 1 - Core Platform Foundation 🚀
