# 🚀 Fortress Guest Platform - Deployment Guide

## Phase 1 Foundation - BUILT ✅

### What's Complete:
1. ✅ **Database Schema** - Complete PostgreSQL schema with 15+ tables
2. ✅ **SQLAlchemy Models** - All Python models for ORM
3. ✅ **FastAPI Application** - Main app structure with middleware
4. ✅ **Configuration System** - Pydantic settings with environment variables
5. ✅ **Project Structure** - Proper directory layout

### What's Ready to Deploy:
```
fortress-guest-platform/
├── database/schema.sql       ← Complete database schema
├── backend/
│   ├── main.py              ← FastAPI app (ready)
│   ├── models/              ← All SQLAlchemy models (ready)
│   ├── core/
│   │   ├── config.py        ← Settings management
│   │   └── database.py      ← DB connection
│   └── api/                 ← API endpoints (building)
├── requirements.txt         ← All dependencies
└── .env.example            ← Configuration template
```

---

## 🏗️ Next Steps to Complete

### Immediate (Today):
1. **Create API Endpoints** - REST APIs for guests, messages, reservations
2. **Twilio Integration** - Upgrade from webhook receiver to full SMS platform
3. **Message Threading** - Conversation history and management

### Phase 2 (Next 2-3 days):
4. **AI Response Engine** - RAG with Qdrant + OpenAI
5. **Lifecycle Automation** - Scheduled messages, triggers
6. **Admin Dashboard** - React frontend for staff

### Phase 3 (Following week):
7. **Digital Guestbook** - Guest-facing portal
8. **Operations Center** - Work orders, analytics
9. **Testing & Polish** - Full system testing

---

## 📦 Installation Instructions

### 1. Create Virtual Environment
```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
# Copy example config
cp .env.example .env

# Edit with your credentials
nano .env

# Set these values:
# - DATABASE_URL (PostgreSQL connection)
# - TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
# - OPENAI_API_KEY
# - STREAMLINE_API_KEY (for PMS integration)
```

### 4. Initialize Database
```bash
# Create database
sudo -u postgres psql -c "CREATE DATABASE fortress_guest;"

# Run schema
sudo -u postgres psql -d fortress_guest -f database/schema.sql

# Verify
sudo -u postgres psql -d fortress_guest -c "\dt"
```

### 5. Start Application
```bash
# Development mode (with auto-reload)
python backend/main.py

# Production mode (with Gunicorn)
gunicorn backend.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8100 \
  --access-logfile /var/log/fgp/access.log \
  --error-logfile /var/log/fgp/error.log
```

### 6. Verify Running
```bash
# Health check
curl http://localhost:8100/health

# API docs
open http://localhost:8100/docs
```

---

## 🔄 Migration from CROG Gateway

### Current SMS Flow:
```
Twilio → nginx → CROG Gateway (port 8001) → Logs only
```

### New SMS Flow (FGP):
```
Twilio → nginx → FGP (port 8100) → Full guest lifecycle + AI
```

### Migration Steps:
1. **Run FGP in parallel** - Don't shut down CROG Gateway yet
2. **Update nginx** - Route `/webhooks/sms/*` to port 8100
3. **Sync existing data** - Import RueBaRue history if needed
4. **Test thoroughly** - Send test SMS, verify responses
5. **Cutover** - Switch Twilio webhook, monitor
6. **Decommission** - Shut down CROG Gateway after 24hrs

---

## 🔧 nginx Configuration Update

Edit `/home/admin/Fortress-Prime/nginx/wolfpack_ai.conf`:

```nginx
# ── Fortress Guest Platform (FGP) ──
location /webhooks/sms/ {
    proxy_pass http://127.0.0.1:8100;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    proxy_connect_timeout 10s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;
    
    client_max_body_size 10m;
    proxy_buffering off;
}

# FGP API Endpoints
location /api/ {
    proxy_pass http://127.0.0.1:8100;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    proxy_connect_timeout 10s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;
}

# FGP Guestbook Portal
location /guest/ {
    proxy_pass http://127.0.0.1:8100;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Then reload nginx:
```bash
docker exec wolfpack-lb nginx -t
docker exec wolfpack-lb nginx -s reload
```

---

## 📊 Database Schema Highlights

### Core Tables:
- **guests** - Guest profiles with analytics
- **reservations** - Bookings with lifecycle tracking
- **properties** - Cabins with WiFi, codes, details
- **messages** - Full SMS history with AI classification
- **work_orders** - Maintenance tracking
- **message_templates** - Automated campaigns
- **scheduled_messages** - Future sends queue
- **guestbook_guides** - Digital property guides
- **extras** - Upsells marketplace
- **analytics_events** - Event tracking

### Views:
- `current_guests` - Who's staying now
- `guests_arriving_today` - Today's arrivals
- `guests_departing_today` - Today's departures
- `message_threads` - Conversation summaries
- `dashboard_stats` - Real-time metrics

---

## 🎯 Features vs RueBaRue

| Feature | RueBaRue | FGP |
|---------|----------|-----|
| Guest Management | ✅ | ✅ |
| SMS Messaging | ✅ | ✅ |
| Message History | ✅ | ✅ |
| Scheduled Messages | ✅ | ✅ |
| Digital Guestbook | ✅ | ✅ |
| Work Orders | ✅ | ✅ |
| Analytics | ✅ | ✅ |
| **AI Responses** | ❌ | ✅ |
| **Intent Classification** | ❌ | ✅ |
| **Sentiment Analysis** | ❌ | ✅ |
| **Predictive Analytics** | ❌ | ✅ |
| **Learning System** | ❌ | ✅ |
| **Multi-language** | ❌ | ✅ |
| **Data Ownership** | ❌ | ✅ |
| **Unlimited Customization** | ❌ | ✅ |

---

## 🔐 Security Checklist

- [ ] Change `SECRET_KEY` in `.env`
- [ ] Change `JWT_SECRET_KEY` in `.env`
- [ ] Set strong database password
- [ ] Enable HTTPS only (Cloudflare)
- [ ] Rate limiting on SMS endpoints
- [ ] Input validation on all endpoints
- [ ] SQL injection protection (SQLAlchemy ORM)
- [ ] XSS protection on guest portal
- [ ] Staff password hashing (bcrypt)
- [ ] API key rotation schedule

---

## 📈 Monitoring & Logs

### Application Logs:
```bash
tail -f /var/log/fortress-guest-platform/app.log
```

### Database Performance:
```sql
-- Slow queries
SELECT * FROM pg_stat_statements 
ORDER BY mean_exec_time DESC 
LIMIT 10;

-- Table sizes
SELECT 
  table_name,
  pg_size_pretty(pg_total_relation_size(table_name::regclass))
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY pg_total_relation_size(table_name::regclass) DESC;
```

### SMS Stats:
```bash
curl http://localhost:8100/api/analytics/dashboard
```

---

## 🚨 Troubleshooting

### App Won't Start:
```bash
# Check logs
tail -50 /var/log/fortress-guest-platform/app.log

# Check database
sudo -u postgres psql -d fortress_guest -c "\conninfo"

# Check port
netstat -tlnp | grep 8100
```

### Database Connection Errors:
```bash
# Test connection
psql postgresql://miner_bot:password@localhost:5432/fortress_guest

# Check user permissions
sudo -u postgres psql -c "\du"
```

### SMS Not Arriving:
```bash
# Check Twilio webhook config
python /home/admin/Fortress-Prime/test_webhook_delivery.py

# Check nginx routing
curl -X POST http://localhost/webhooks/sms/incoming \
  -H "Host: crog-ai.com" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "MessageSid=TEST&From=+16785493680&To=+17064711479&Body=Test"

# Check FGP logs
tail -f /var/log/fortress-guest-platform/app.log | grep "twilio"
```

---

## 📞 Support

**System Owner**: Cabin Rentals of Georgia  
**Contact**: lissa@cabin-rentals-of-georgia.com  
**SMS Number**: +17064711479  
**Admin Portal**: https://crog-ai.com/admin

---

**Status**: Phase 1 Complete ✅ | Phase 2 In Progress 🚧

This system will replace RueBaRue and give you complete control over guest communication!
