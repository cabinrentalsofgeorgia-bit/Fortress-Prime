# CROG Gateway - Quick Reference Card

> **One-page cheat sheet for developers**

---

## 🚀 Common Commands

```bash
# Quick start (auto-setup)
./start.sh

# Manual start
python app/main.py

# Docker
docker-compose up -d                  # Start
docker-compose logs -f                # View logs
docker-compose restart crog-gateway   # Restart
docker-compose down                   # Stop

# Testing
make test                            # Run tests with coverage
pytest tests/test_router.py -v      # Run specific test
pytest tests/ --cov=app              # Coverage report

# Code quality
make format                          # Format code (black, isort)
make lint                            # Lint code (flake8, mypy)

# Dependencies
pip install -r requirements.txt      # Install
pip freeze > requirements.txt        # Update
```

---

## 🎛️ Feature Flags (Environment Variables)

```bash
# Pass-through Mode (100% legacy)
ENABLE_AI_REPLIES=false
SHADOW_MODE=false
AI_INTENT_FILTER=

# Shadow Mode (compare AI vs Legacy)
ENABLE_AI_REPLIES=false
SHADOW_MODE=true
AI_INTENT_FILTER=

# AI Cutover (WiFi questions only)
ENABLE_AI_REPLIES=true
SHADOW_MODE=false
AI_INTENT_FILTER=WIFI_QUESTION

# AI Cutover (multiple intents)
ENABLE_AI_REPLIES=true
SHADOW_MODE=false
AI_INTENT_FILTER=WIFI_QUESTION,ACCESS_CODE_REQUEST,CHECKIN_QUESTION

# Full AI (all intents)
ENABLE_AI_REPLIES=true
SHADOW_MODE=false
AI_INTENT_FILTER=  # Empty = all
```

---

## 🔍 Monitoring Commands

```bash
# Health check
curl http://localhost:8000/health

# View feature flags
curl http://localhost:8000/config

# Tail logs
tail -f logs/app.log

# Query logs (JSON)
cat logs/app.log | jq 'select(.event == "routing_decision_made")'

# Find errors
cat logs/app.log | jq 'select(.level == "error")'

# Trace a specific request
cat logs/app.log | jq 'select(.trace_id == "abc123")'

# Count routes by type
cat logs/app.log | jq -r '.route_to' | sort | uniq -c

# Shadow mode divergence
cat logs/app.log | jq 'select(.event == "shadow_comparison_complete" and .responses_match == false)'
```

---

## 📂 File Structure (Key Files)

```
app/
├── main.py                    # FastAPI entry point
├── core/
│   ├── interfaces.py          # ABCs (Ports)
│   ├── config.py              # Settings (Feature Flags)
│   └── logging.py             # Structured logging
├── models/
│   └── domain.py              # Pydantic models
├── services/
│   └── router.py              # TrafficRouter (Strangler)
├── adapters/
│   ├── legacy/
│   │   ├── ruebarue.py        # SMS adapter
│   │   └── streamline.py      # PMS adapter
│   └── ai/
│       └── crog.py            # AI adapter
└── api/
    └── routes.py              # FastAPI routes
```

---

## 🔌 API Endpoints

| Endpoint                     | Method | Purpose                    |
| ---------------------------- | ------ | -------------------------- |
| `/`                          | GET    | API info                   |
| `/health`                    | GET    | Health check               |
| `/config`                    | GET    | Feature flags              |
| `/webhooks/sms/incoming`     | POST   | Incoming SMS webhook       |
| `/webhooks/sms/status`       | POST   | SMS status update          |
| `/api/messages/send`         | POST   | Send SMS (manual)          |
| `/api/reservations/{phone}`  | GET    | Lookup reservation         |

**Docs**: http://localhost:8000/docs

---

## 🧪 Testing APIs

```bash
# Health check
curl http://localhost:8000/health

# Send SMS
curl -X POST http://localhost:8000/api/messages/send \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+15551234567",
    "message_body": "Test message"
  }'

# Lookup reservation
curl http://localhost:8000/api/reservations/+15551234567

# Incoming SMS webhook (simulate)
curl -X POST http://localhost:8000/webhooks/sms/incoming \
  -H "Content-Type: application/json" \
  -d '{
    "id": "msg_123",
    "from": "+15551234567",
    "to": "+15559876543",
    "body": "What is the WiFi password?",
    "received_at": "2024-01-15T10:30:00Z"
  }'
```

---

## 📊 Key Metrics to Monitor

| Metric                      | Query                                                  | Alert |
| --------------------------- | ------------------------------------------------------ | ----- |
| Routing decisions           | `grep "routing_decision_made" logs/app.log`            | N/A   |
| AI routes                   | `jq 'select(.route_to == "ai")' logs/app.log`         | N/A   |
| Shadow divergence           | `jq 'select(.responses_match == false)' logs/app.log` | > 20% |
| Errors                      | `jq 'select(.level == "error")' logs/app.log`         | > 10  |
| Response time               | `jq '.elapsed_ms' logs/app.log \| avg`                | > 1s  |

---

## 🔧 How To: Common Tasks

### Add a New SMS Provider

1. Create adapter in `app/adapters/sms/new_provider.py`
2. Implement `SMSService` interface
3. Update `app/main.py` to use new adapter

### Add a New Intent

1. Add to `MessageIntent` enum in `app/models/domain.py`
2. Update `classify_intent()` in `app/adapters/legacy/ruebarue.py`
3. Add handler in `app/adapters/ai/crog.py`

### Enable Shadow Mode

```bash
# Edit .env
SHADOW_MODE=true

# Restart
docker-compose restart crog-gateway
```

### Rollback to Legacy (Emergency)

```bash
# Edit .env
ENABLE_AI_REPLIES=false
SHADOW_MODE=false

# Restart immediately
docker-compose restart crog-gateway
```

### Analyze Shadow Results

```bash
# Export to CSV for analysis
grep "shadow_comparison_complete" logs/app.log | \
  jq -r '[.timestamp, .intent, .responses_match, .divergence_details] | @csv' > shadow_results.csv
```

---

## 🛡️ Production Checklist

Before deploying:

- [ ] `.env` configured with production keys
- [ ] Feature flags set correctly
- [ ] Tests passing (`make test`)
- [ ] Docker image built (`make docker-build`)
- [ ] Health check working
- [ ] Monitoring/alerting configured
- [ ] Rollback plan documented
- [ ] Stakeholders notified

---

## 🐛 Troubleshooting

### Issue: "Module not found" error

```bash
# Ensure venv activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Issue: "Connection refused" to external APIs

```bash
# Check .env has correct API URLs
grep "API_URL" .env

# Test connectivity
curl -v https://api.ruebarue.com/v1/health
```

### Issue: High response times

```bash
# Check which adapter is slow
grep "elapsed_ms" logs/app.log | jq '.adapter, .elapsed_ms'

# Increase timeout
HTTP_TIMEOUT_SECONDS=60  # in .env
```

### Issue: Shadow mode divergence

```bash
# Find divergent responses
grep "shadow_comparison_complete" logs/app.log | \
  jq 'select(.responses_match == false)'

# Disable shadow mode temporarily
SHADOW_MODE=false
```

---

## 📚 Documentation Map

| File                         | Content                                  |
| ---------------------------- | ---------------------------------------- |
| `README.md`                  | Getting started, installation            |
| `ARCHITECTURE.md`            | Deep dive into design patterns           |
| `MIGRATION_PLAYBOOK.md`      | Week-by-week migration guide             |
| `PROJECT_SUMMARY.md`         | High-level overview                      |
| `QUICK_REFERENCE.md`         | This file - commands & cheat sheet       |

---

## 🔗 Quick Links

- **API Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/health
- **Config**: http://localhost:8000/config
- **Logs**: `logs/app.log`
- **Tests**: `pytest tests/ -v`

---

## 📞 Emergency Contacts

```bash
# Rollback to 100% legacy (immediate)
export ENABLE_AI_REPLIES=false
export SHADOW_MODE=false
docker-compose restart crog-gateway

# Check service status
docker-compose ps

# View recent errors
docker-compose logs --tail=100 crog-gateway | grep ERROR
```

---

**Print this page and keep it at your desk!**
