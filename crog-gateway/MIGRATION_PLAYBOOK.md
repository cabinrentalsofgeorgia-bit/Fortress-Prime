# CROG Gateway - Migration Playbook

> **A step-by-step guide for safely migrating guest communication from legacy systems to AI.**

## 🎯 Migration Philosophy

The Strangler Fig Pattern allows you to migrate **incrementally** with **zero downtime** and **minimal risk**. You don't flip a switch and pray—you validate, test, and expand gradually.

---

## 📊 Migration Phases

### Phase 1: Pass-through (Week 1)

**Goal**: Deploy CROG Gateway with zero behavioral changes. Legacy handles everything.

**Configuration**:

```bash
ENABLE_AI_REPLIES=false
SHADOW_MODE=false
AI_INTENT_FILTER=
```

**Actions**:

1. Deploy `crog-gateway` to production
2. Route SMS webhooks through the gateway
3. Verify all messages flow correctly through legacy path
4. Monitor logs for errors

**Success Criteria**:

- ✅ Zero guest impact
- ✅ All messages delivered via legacy systems
- ✅ Structured logs include `trace_id` for all requests

**Rollback Plan**: Point webhooks directly to legacy system

---

### Phase 2: Shadow Mode (Weeks 2-4)

**Goal**: Validate AI accuracy by comparing responses to legacy. Guests still receive legacy responses.

**Configuration**:

```bash
ENABLE_AI_REPLIES=false
SHADOW_MODE=true
AI_INTENT_FILTER=
```

**Actions**:

1. Enable shadow mode
2. AI processes ALL messages in parallel (guest never sees AI responses)
3. Analyze `ShadowResult` logs for divergence:

```bash
# Query logs for divergence
grep "shadow_comparison_complete" logs/app.log | jq '.responses_match'
```

4. Calculate AI accuracy:

```bash
# Accuracy = matches / total
awk '/shadow_comparison_complete/ {total++; if ($0 ~ /"responses_match":true/) matches++} END {print "Accuracy:", (matches/total)*100"%"}' logs/app.log
```

**Success Criteria**:

- ✅ AI accuracy > 95% for target intents
- ✅ No increase in guest complaints
- ✅ Response time delta < 500ms

**Rollback Plan**: Disable shadow mode (`SHADOW_MODE=false`)

---

### Phase 3: Cutover - Low-Risk Intents (Weeks 5-6)

**Goal**: Let AI handle WiFi and check-in questions ONLY. These are low-risk, high-volume.

**Configuration**:

```bash
ENABLE_AI_REPLIES=true
SHADOW_MODE=false
AI_INTENT_FILTER=WIFI_QUESTION,CHECKIN_QUESTION
```

**Actions**:

1. Enable AI for specific intents
2. Monitor guest satisfaction (NPS, reply times, escalations)
3. Watch for edge cases where AI fails:

```bash
# Monitor AI failures
grep "ai_generation_failed" logs/app.log
```

4. Collect feedback from support team

**Success Criteria**:

- ✅ AI handles 80%+ of WiFi/check-in questions without escalation
- ✅ Guest satisfaction stable or improved
- ✅ Support team reports fewer repetitive questions

**Rollback Plan**: Remove intents from filter or disable AI

---

### Phase 4: Expand to Medium-Risk Intents (Weeks 7-10)

**Goal**: Add access codes, amenity questions, and checkout.

**Configuration**:

```bash
ENABLE_AI_REPLIES=true
SHADOW_MODE=false
AI_INTENT_FILTER=WIFI_QUESTION,CHECKIN_QUESTION,ACCESS_CODE_REQUEST,AMENITY_QUESTION,CHECKOUT_QUESTION
```

**Actions**:

1. Add one intent per week (gradual expansion)
2. Monitor error rates per intent:

```bash
# Intent-specific error analysis
grep "intent_classified" logs/app.log | jq '.intent' | sort | uniq -c
```

3. Re-enable shadow mode for new intents if needed

**Success Criteria**:

- ✅ AI handles 90%+ of target intents
- ✅ Zero security incidents (access codes)
- ✅ Maintenance requests properly escalated

**Rollback Plan**: Remove problematic intents from filter

---

### Phase 5: Full Cutover (Week 11+)

**Goal**: AI handles ALL guest communication. Legacy is strangled.

**Configuration**:

```bash
ENABLE_AI_REPLIES=true
SHADOW_MODE=false
AI_INTENT_FILTER=  # Empty = AI handles everything
```

**Actions**:

1. Remove intent filter (AI handles all)
2. Keep legacy systems online (fallback)
3. Monitor for 2 weeks before decommissioning legacy

**Success Criteria**:

- ✅ AI handles 95%+ of all communication
- ✅ Guest satisfaction improved by 10%+
- ✅ Support team capacity increased 30%+

**Rollback Plan**: Re-add intent filter or disable AI entirely

---

## 🔍 Key Metrics to Monitor

### Response Quality

```bash
# Shadow mode divergence rate
grep "shadow_comparison_complete" logs/app.log | \
  jq -r 'select(.responses_match == false) | .divergence_details'
```

### Performance

```bash
# Average response time per route
grep "message_routed_successfully" logs/app.log | \
  jq '.route' | sort | uniq -c
```

### Error Rates

```bash
# Errors by adapter
grep "error" logs/app.log | jq '.adapter' | sort | uniq -c
```

### Guest Impact

- **NPS Score**: Survey guests post-interaction
- **Escalation Rate**: % of messages requiring human intervention
- **Response Time**: Time from SMS received to reply sent

---

## 🚨 Incident Response

### Scenario 1: AI Sends Incorrect Access Code

**Detection**:

```bash
grep "access_code_request" logs/app.log | grep "route_to\":\"ai"
```

**Response**:

1. Immediately disable AI for access codes:

```bash
AI_INTENT_FILTER=WIFI_QUESTION,CHECKIN_QUESTION  # Remove ACCESS_CODE_REQUEST
```

2. Contact affected guest via legacy system
3. Root cause analysis on AI logic
4. Re-enable after fix + shadow mode validation

### Scenario 2: SMS Provider Outage (RueBaRue down)

**Detection**: Spike in `ruebarue_api_error` logs

**Response**:

1. Automatic retries will handle transient issues (tenacity)
2. If sustained outage (> 5 minutes):
   - Failover to backup SMS provider (if configured)
   - Alert on-call engineer

### Scenario 3: Streamline VRS API Degradation

**Detection**: Slow response times in reservation lookups

**Response**:

1. Monitor retry attempts:

```bash
grep "retry" logs/app.log | wc -l
```

2. If retries exhausted, return generic response:
   - "We're experiencing technical difficulties. Please contact support."
3. Scale back to pass-through mode if needed

---

## 📈 Success Metrics by Phase

| Phase           | AI Handles | Guest Satisfaction | Support Load | Risk   |
| --------------- | ---------- | ------------------ | ------------ | ------ |
| Pass-through    | 0%         | Baseline           | Baseline     | None   |
| Shadow          | 0%         | Baseline           | Baseline     | None   |
| Cutover (Low)   | 30%        | +5%                | -20%         | Low    |
| Cutover (Med)   | 70%        | +8%                | -40%         | Medium |
| Full Cutover    | 95%        | +10%               | -60%         | Medium |

---

## 🛡️ Safety Guardrails

### 1. Circuit Breaker (Future)

If AI error rate > 10% in 5 minutes, auto-rollback to legacy.

### 2. Rate Limiting

Prevent AI from overwhelming guests with responses.

### 3. Human-in-the-Loop

High-risk intents (cancellations, refunds) always require human approval.

### 4. A/B Testing

Route 10% of traffic to AI, 90% to legacy for validation.

---

## 📚 Runbook: Common Commands

### Check Current Configuration

```bash
curl http://localhost:8000/config
```

### Enable Shadow Mode

```bash
# Update .env
SHADOW_MODE=true

# Restart service
docker-compose restart crog-gateway
```

### Analyze Shadow Results

```bash
# Export shadow results for analysis
grep "shadow_comparison_complete" logs/app.log | jq -c '{
  trace_id,
  intent: .intent,
  match: .responses_match,
  divergence: .divergence_details
}' > shadow_analysis.jsonl
```

### Monitor Live Traffic

```bash
# Tail logs with intent classification
tail -f logs/app.log | jq 'select(.event == "routing_decision_made") | {
  time: .timestamp,
  intent: .intent,
  route: .route_to,
  reason: .reason
}'
```

### Rollback to Legacy

```bash
# Emergency rollback: Disable AI entirely
export ENABLE_AI_REPLIES=false
export SHADOW_MODE=false
docker-compose restart crog-gateway
```

---

## 🤝 Stakeholder Communication

### Weekly Update Template

```
**CROG Gateway Migration - Week X Update**

**Current Phase**: Shadow Mode
**AI Accuracy**: 96.2% (target: 95%)
**Guest Impact**: Zero (still on legacy responses)
**Next Steps**: Enable AI for WiFi questions next week

**Risks**: None
**Blockers**: None
**Questions**: Should we expand to access codes sooner?
```

---

## ✅ Pre-Deployment Checklist

Before enabling each new phase:

- [ ] Code reviewed by 2+ engineers
- [ ] Unit tests passing (> 90% coverage)
- [ ] Load tested at 2x peak traffic
- [ ] Runbook updated with rollback steps
- [ ] On-call engineer briefed
- [ ] Monitoring dashboards configured
- [ ] Stakeholders notified (product, support, executive)

---

**Remember**: The Strangler Pattern is about **patience and validation**. It's better to migrate slowly and safely than quickly and recklessly.

**Next**: Ready to deploy? See [README.md](README.md) for installation instructions.
