# CROG Gateway - Architecture Deep Dive

## 🏛️ Architectural Patterns

### 1. Hexagonal Architecture (Ports & Adapters)

The core business logic (TrafficRouter) depends on **interfaces**, not implementations.

```
┌──────────────────────────────────────────────────────┐
│              Core Business Logic                      │
│          (app/services/router.py)                     │
│                                                        │
│  TrafficRouter decides: Legacy, AI, or Shadow?        │
└──────────────────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
   ┌──────────┐    ┌──────────┐   ┌──────────┐
   │   PORT   │    │   PORT   │   │   PORT   │
   │SMS       │    │PMS       │   │AI        │
   │Service   │    │Service   │   │Service   │
   └──────────┘    └──────────┘   └──────────┘
   (Interface)     (Interface)    (Interface)
         │               │               │
         ▼               ▼               ▼
   ┌──────────┐    ┌──────────┐   ┌──────────┐
   │ ADAPTER  │    │ ADAPTER  │   │ ADAPTER  │
   │RueBaRue  │    │Streamline│   │CROG AI   │
   └──────────┘    └──────────┘   └──────────┘
```

**Benefits**:

- Swap SMS providers (RueBaRue → Twilio) by changing ONE file
- Swap PMS (Streamline → Guesty) by changing ONE file
- Test with mocks (no external dependencies)

---

### 2. Strangler Fig Pattern

Incrementally migrate from Legacy to AI without rewriting everything.

```
┌─────────────────────────────────────────────┐
│         Incoming Guest Message               │
│           (SMS Webhook)                      │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│          Traffic Router                      │
│   (Feature Flag Decision Tree)              │
└─────────────────────────────────────────────┘
         │              │              │
         │              │              │
    ┌────▼───┐     ┌────▼───┐    ┌────▼───┐
    │ Legacy │     │ Shadow │    │   AI   │
    │  100%  │     │Legacy+ │    │Specific│
    │        │     │AI Log  │    │Intents │
    └────────┘     └────────┘    └────────┘
```

**Migration Path**:

1. **Pass-through** (Week 1): 100% Legacy
2. **Shadow** (Weeks 2-4): Legacy + AI (compare)
3. **Cutover** (Weeks 5-10): AI handles WiFi, then expand
4. **Full AI** (Week 11+): AI handles 95%+

---

## 📂 Code Organization

### Domain-Driven Design

```
app/
├── core/               # Domain logic & interfaces
│   ├── interfaces.py   # ABCs (Ports)
│   ├── config.py       # Settings (Feature Flags)
│   └── logging.py      # Observability
│
├── models/             # Domain entities
│   └── domain.py       # Guest, Reservation, Message
│
├── services/           # Business logic
│   └── router.py       # TrafficRouter (Strangler)
│
├── adapters/           # External integrations (Adapters)
│   ├── legacy/
│   │   ├── ruebarue.py     # SMS Provider
│   │   └── streamline.py   # PMS
│   └── ai/
│       └── crog.py         # AI System
│
└── api/                # HTTP interface
    └── routes.py       # FastAPI endpoints
```

---

## 🔄 Request Flow

### Incoming SMS Webhook

```
1. SMS arrives at RueBaRue
   ↓
2. RueBaRue sends webhook to /webhooks/sms/incoming
   ↓
3. FastAPI route handler (routes.py)
   ↓
4. Generate trace_id for observability
   ↓
5. Parse webhook → Message (domain model)
   ↓
6. TrafficRouter.route_guest_message(message)
   ↓
7. Classify intent (WiFi? Access code?)
   ↓
8. Lookup reservation by phone number
   ↓
9. Make routing decision (Legacy, AI, Shadow?)
   ↓
10. Execute strategy:
    - Legacy: RueBaRueAdapter.send_message()
    - Shadow: Both Legacy + AI (compare)
    - AI: CrogAIAdapter.generate_response()
   ↓
11. Return MessageResponse to guest
   ↓
12. Log decision + outcome (structured JSON)
```

**Trace ID Flow**:

```
trace_id="abc123"
↓
[2024-01-15T10:30:00Z] intent_classified trace_id=abc123 intent=wifi_question
↓
[2024-01-15T10:30:01Z] reservation_found trace_id=abc123 reservation_id=RES123
↓
[2024-01-15T10:30:02Z] routing_decision_made trace_id=abc123 route_to=ai
↓
[2024-01-15T10:30:03Z] message_routed_successfully trace_id=abc123
```

---

## 🧩 Key Components

### TrafficRouter (The Strangler)

**Location**: `app/services/router.py`

**Responsibilities**:

1. Classify message intent
2. Lookup guest reservation
3. Make routing decision based on feature flags
4. Execute routing strategy (Legacy, AI, Shadow)
5. Log all decisions for audit trail

**Feature Flag Logic**:

```python
def _make_routing_decision(intent, has_reservation, trace_id):
    if settings.shadow_mode:
        return "shadow"  # Send to both Legacy + AI
    
    if settings.should_use_ai_for_intent(intent):
        return "ai"  # AI handles this intent
    
    return "legacy"  # Default: Pass-through
```

---

### SMSService Interface (Port)

**Location**: `app/core/interfaces.py`

**Contract**:

```python
class SMSService(ABC):
    @abstractmethod
    async def send_message(phone, body, trace_id) -> MessageResponse
    
    @abstractmethod
    async def receive_message(raw_payload, trace_id) -> Message
    
    @abstractmethod
    async def classify_intent(message, trace_id) -> MessageIntent
```

**Implementations**:

- `RueBaRueAdapter` (legacy)
- `TwilioAdapter` (future)
- `MockSMSAdapter` (testing)

---

### ReservationService Interface (Port)

**Location**: `app/core/interfaces.py`

**Contract**:

```python
class ReservationService(ABC):
    @abstractmethod
    async def get_reservation_by_phone(phone, trace_id) -> Reservation
    
    @abstractmethod
    async def get_access_code(reservation, trace_id) -> AccessCode
```

**Implementations**:

- `StreamlineVRSAdapter` (legacy PMS)
- `GuestyAdapter` (future)
- `MockPMSAdapter` (testing)

---

## 🔐 Security Architecture

### Secrets Management

All secrets are managed via **environment variables** (`.env`):

```bash
# NEVER hardcoded in source code
RUEBARUE_API_KEY=sk_live_abc123
STREAMLINE_API_KEY=pk_prod_xyz789
CROG_AI_API_KEY=token_def456
```

Validated at startup using `pydantic-settings`:

```python
class Settings(BaseSettings):
    ruebarue_api_key: str = Field(..., description="Required")
```

If missing, app fails to start (fail-fast).

---

### Input Validation

All external data passes through **Pydantic V2 models**:

```python
class Message(BaseModel):
    from_phone: str = Field(..., pattern=r"^\+1\d{10}$")  # E.164 format
    body: str = Field(..., min_length=1, max_length=1600)
```

Invalid data → 422 Unprocessable Entity (before hitting business logic).

---

## 📊 Observability

### Structured Logging (Structlog)

Every log entry is JSON with:

- `timestamp`: ISO8601
- `level`: INFO, WARNING, ERROR
- `event`: Log message
- `trace_id`: Request correlation ID
- `service`: "CROG Gateway"
- `environment`: development/staging/production

**Example**:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "event": "routing_decision_made",
  "trace_id": "abc123",
  "service": "CROG Gateway",
  "route_to": "ai",
  "intent": "wifi_question",
  "reason": "AI enabled for intent: wifi_question"
}
```

**Query logs**:

```bash
# Find all AI routes
cat logs/app.log | jq 'select(.route_to == "ai")'

# Trace a specific request
cat logs/app.log | jq 'select(.trace_id == "abc123")'
```

---

### Metrics to Track

| Metric                     | Description                             | Alert Threshold |
| -------------------------- | --------------------------------------- | --------------- |
| `route_decision_latency`   | Time to make routing decision           | > 500ms         |
| `sms_delivery_success_rate`| % of messages successfully delivered    | < 95%           |
| `ai_response_divergence`   | % of AI responses != Legacy (shadow)    | > 20%           |
| `intent_classification_acc`| % of intents correctly classified       | < 90%           |
| `reservation_lookup_errors`| Count of PMS lookup failures            | > 10/hour       |

---

## 🚀 Deployment Architecture

### Production Topology

```
┌─────────────────────────────────────────────────────┐
│              Load Balancer (NGINX/ALB)              │
└─────────────────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │  CROG    │   │  CROG    │   │  CROG    │
    │ Gateway  │   │ Gateway  │   │ Gateway  │
    │ Instance │   │ Instance │   │ Instance │
    │    1     │   │    2     │   │    3     │
    └──────────┘   └──────────┘   └──────────┘
          │              │              │
          └──────────────┼──────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │RueBaRue  │   │Streamline│   │ CROG AI  │
    │  API     │   │  VRS API │   │  Service │
    └──────────┘   └──────────┘   └──────────┘
```

### Docker Deployment

```yaml
# docker-compose.yml
services:
  crog-gateway:
    image: crog-gateway:latest
    replicas: 3
    resources:
      limits:
        cpus: '2'
        memory: 2G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

---

## 🧪 Testing Strategy

### Unit Tests

Test individual components in isolation using mocks:

```python
# tests/test_router.py
async def test_shadow_mode(traffic_router, sample_message, monkeypatch):
    monkeypatch.setattr(settings, "shadow_mode", True)
    
    response, decision = await traffic_router.route_guest_message(sample_message)
    
    assert decision.route_to == "shadow"
    assert response.provider == "ruebarue"  # Guest gets legacy
```

---

### Integration Tests

Test API endpoints with FastAPI TestClient:

```python
# tests/test_api.py
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
```

---

### Load Tests

Simulate peak traffic using Locust:

```python
# tests/load_test.py
class GuestBehavior(HttpUser):
    @task
    def send_sms_webhook(self):
        self.client.post("/webhooks/sms/incoming", json={
            "from": "+15551234567",
            "body": "What is the WiFi password?"
        })
```

Run:

```bash
locust -f tests/load_test.py --host http://localhost:8000 --users 100 --spawn-rate 10
```

---

## 🔧 Extensibility

### Adding a New SMS Provider (e.g., Twilio)

1. Create adapter:

```python
# app/adapters/sms/twilio.py
from app.core.interfaces import SMSService

class TwilioAdapter(SMSService):
    async def send_message(self, phone, body, trace_id):
        # Implement Twilio API call
        pass
```

2. Update dependency injection:

```python
# app/main.py
if settings.sms_provider == "twilio":
    legacy_sms = TwilioAdapter()
else:
    legacy_sms = RueBaRueAdapter()
```

3. No changes to TrafficRouter or business logic!

---

### Adding a New Intent

1. Add to enum:

```python
# app/models/domain.py
class MessageIntent(str, Enum):
    WIFI_QUESTION = "wifi_question"
    NEW_INTENT = "new_intent"  # Add here
```

2. Update intent classification:

```python
# app/adapters/legacy/ruebarue.py
if "new keyword" in body_lower:
    intent = MessageIntent.NEW_INTENT
```

3. Add AI handler:

```python
# app/adapters/ai/crog.py
async def _handle_new_intent(self, reservation, trace_id):
    # Implement logic
    pass
```

---

## 📈 Scalability

### Horizontal Scaling

CROG Gateway is **stateless** → Scale by adding instances:

```bash
docker-compose up --scale crog-gateway=5
```

### Async I/O

All external calls use `asyncio` (non-blocking):

- HTTP calls: `httpx.AsyncClient`
- Database queries: `asyncpg` (future)
- Message queues: `aio-pika` (future)

Single instance can handle **1000+ concurrent requests**.

---

## 🛠️ Troubleshooting

### Issue: High Latency

**Symptoms**: Response time > 1 second

**Debug**:

```bash
# Check which adapter is slow
grep "elapsed_ms" logs/app.log | jq '.adapter, .elapsed_ms'
```

**Solution**: Tune HTTP timeouts or add caching

---

### Issue: Shadow Mode Divergence

**Symptoms**: AI responses != Legacy responses

**Debug**:

```bash
# Find divergent responses
grep "shadow_comparison_complete" logs/app.log | \
  jq 'select(.responses_match == false)'
```

**Solution**: Improve AI prompt or add training data

---

## 📚 Further Reading

- [Strangler Fig Pattern](https://martinfowler.com/bliki/StranglerFigApplication.html) (Martin Fowler)
- [Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/) (Alistair Cockburn)
- [Domain-Driven Design](https://www.domainlanguage.com/ddd/) (Eric Evans)

---

**Questions?** See [README.md](README.md) or contact the CROG engineering team.
