# CROG Gateway - Strangler Fig Pattern Microservice

> **Production-grade FastAPI service for migrating guest communication from legacy systems to AI-powered automation.**

## 🏗️ Architecture Overview

This microservice implements the **Strangler Fig Pattern** to safely migrate functionality from legacy systems:

- **Legacy SMS**: RueBaRue (current provider)
- **Legacy PMS**: Streamline VRS (property management system)
- **New System**: CROG AI (your internal AI system)

### Hexagonal Architecture (Ports & Adapters)

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Application                     │
│                      (app/main.py)                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Traffic Router (Strangler)                │
│         Decides: Legacy, AI, or Shadow Mode?                │
└─────────────────────────────────────────────────────────────┘
                 │                    │                    │
        ┌────────┴────────┐  ┌────────┴────────┐  ┌────────┴────────┐
        │  SMSService     │  │ ReservationSvc  │  │   AIService     │
        │  (Interface)    │  │  (Interface)    │  │  (Interface)    │
        └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
                 │                    │                    │
        ┌────────┴────────┐  ┌────────┴────────┐  ┌────────┴────────┐
        │  RueBaRue       │  │ Streamline VRS  │  │   CROG AI       │
        │  Adapter        │  │    Adapter      │  │   Adapter       │
        └─────────────────┘  └─────────────────┘  └─────────────────┘
```

## 📁 Project Structure

```
crog-gateway/
├── app/
│   ├── core/
│   │   ├── interfaces.py      # ABC Port definitions (SMSService, ReservationService, AIService)
│   │   ├── config.py          # Pydantic Settings (feature flags, secrets)
│   │   └── logging.py         # Structured logging setup
│   ├── models/
│   │   └── domain.py          # Pydantic V2 domain models (Guest, Reservation, Message)
│   ├── services/
│   │   └── router.py          # TrafficRouter - The Strangler Pattern logic
│   ├── adapters/
│   │   ├── legacy/
│   │   │   ├── ruebarue.py    # RueBaRue SMS adapter (legacy)
│   │   │   └── streamline.py  # Streamline VRS PMS adapter (legacy)
│   │   └── ai/
│   │       └── crog.py        # CROG AI adapter (new system, placeholder)
│   ├── api/
│   │   └── routes.py          # FastAPI route handlers
│   └── main.py                # Application entry point
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
└── README.md                  # This file
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd crog-gateway
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual API keys and settings
```

**Critical Environment Variables:**

```bash
# Feature Flags (Start with these for safe migration)
ENABLE_AI_REPLIES=false      # AI can respond directly to guests
SHADOW_MODE=false            # Send to both legacy AND AI (comparison mode)
AI_INTENT_FILTER=            # Comma-separated intents AI should handle

# Legacy Systems
RUEBARUE_API_KEY=your_key
STREAMLINE_API_KEY=your_key
STREAMLINE_PROPERTY_ID=your_property_id

# New AI System
CROG_AI_URL=http://localhost:8000
CROG_AI_API_KEY=your_ai_key
```

### 3. Run the Service

```bash
# Development mode (auto-reload)
python app/main.py

# Production mode (with uvicorn)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 4. Test the API

```bash
# Health check
curl http://localhost:8000/health

# Send a test SMS
curl -X POST http://localhost:8000/api/messages/send \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+15551234567",
    "message_body": "Your access code is ready!"
  }'

# Lookup a reservation
curl http://localhost:8000/api/reservations/+15551234567
```

## 🎯 The Strangler Pattern - Migration Modes

The `TrafficRouter` supports three migration modes controlled by feature flags:

### Mode 1: Pass-through (Default - Safest)

```bash
ENABLE_AI_REPLIES=false
SHADOW_MODE=false
```

**Behavior**: 100% legacy system handles all requests. Zero risk.

### Mode 2: Shadow (Validation Phase)

```bash
ENABLE_AI_REPLIES=false
SHADOW_MODE=true
```

**Behavior**:
- Legacy system handles the request (guest receives legacy response)
- AI system ALSO processes the request (async, no guest impact)
- Responses are compared and logged for divergence analysis
- **Use this to validate AI accuracy before cutover**

### Mode 3: Cutover (Incremental Migration)

```bash
ENABLE_AI_REPLIES=true
SHADOW_MODE=false
AI_INTENT_FILTER=WIFI_QUESTION,CHECKIN_QUESTION
```

**Behavior**:
- AI handles ONLY the specified intents (WiFi, check-in questions)
- Legacy handles everything else
- **Gradual migration: Start with low-risk intents, expand over time**

### Mode 4: Full AI (Final State)

```bash
ENABLE_AI_REPLIES=true
SHADOW_MODE=false
AI_INTENT_FILTER=  # Empty = AI handles all intents
```

**Behavior**: AI handles 100% of guest communication. Legacy is strangled.

## 🔍 Observability

Every request includes a `trace_id` that flows through:

1. Incoming webhook
2. Intent classification
3. Reservation lookup
4. Traffic routing decision
5. SMS delivery

**Example log entry** (JSON):

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "event": "routing_decision_made",
  "trace_id": "abc123",
  "service": "CROG Gateway",
  "environment": "production",
  "route_to": "ai",
  "intent": "wifi_question",
  "reason": "AI enabled for intent: wifi_question"
}
```

## 🛡️ Resiliency

All external API calls use **automatic retries** with exponential backoff (via `tenacity`):

- **Max attempts**: 3
- **Initial wait**: 2 seconds
- **Backoff**: Exponential (2s, 4s, 8s)
- **Timeout**: 30 seconds

## 📝 Next Steps

### 1. Integrate with Actual APIs

Replace mock implementations in:

- `app/adapters/legacy/ruebarue.py` - Implement actual RueBaRue API calls
- `app/adapters/legacy/streamline.py` - Implement actual Streamline VRS API calls
- `app/adapters/ai/crog.py` - Implement actual CROG AI integration

### 2. Add Database Layer

Persist shadow mode results for analysis:

```python
# Store ShadowResult objects to compare Legacy vs AI responses
await db.save_shadow_result(shadow_result)
```

### 3. Add Monitoring

- Integrate with Datadog/CloudWatch for metrics
- Set up alerts for failed routes
- Track AI vs Legacy divergence rates

### 4. Load Testing

Use `locust` or `k6` to validate under load:

```bash
locust -f tests/load_test.py --host http://localhost:8000
```

## 🔒 Security

- **Never commit `.env`** - Secrets are managed via environment variables
- API keys are validated via `pydantic-settings`
- All phone numbers are E.164 validated
- CORS is restricted in production

## 📚 Documentation

- **Interactive API Docs**: http://localhost:8000/docs
- **OpenAPI Schema**: http://localhost:8000/openapi.json

## 🤝 Contributing

When adding new intents or adapters:

1. Define the interface in `app/core/interfaces.py`
2. Implement the adapter in `app/adapters/`
3. Update the `TrafficRouter` logic if needed
4. Add tests in `tests/`

## 📄 License

Proprietary - CROG Internal Use Only

---

**Built with**: FastAPI, Pydantic V2, Structlog, Tenacity, HTTPX
**Pattern**: Strangler Fig + Hexagonal Architecture
**Purpose**: Safe, incremental migration from legacy to AI
