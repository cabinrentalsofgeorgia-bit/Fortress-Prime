# Fortress Prime Shadow Audit

Append-only comparison reports from `tools/cluster/shadow_mode_observer.py`.
Each entry compares the live legacy quote path against the shadow closer path
before the cluster becomes the source of truth.

## Comparison Report 2026-03-20T12:50:18Z

- Trace ID: `1f499166-8358-45f2-b76d-f7437ef74f21`
- Legacy Total: `$115.00`
- Sovereign Total: `$121.30`
- Drift Status: `CRITICAL_MISMATCH`
- HMAC Signature: `2822c995c33067e77a6af2c3d24c14f4642dd95cd856f8c04a1c06187bd3a500`
- Legacy Taxes: `$10.00`
- Sovereign Taxes: `$16.30`
- Tax Delta: `$6.30`
- Base Rate Drift: `0.0000%`

### Notes
- Shadow quote diverged beyond the accepted no-harm guardrail.

### Request Payload
```json
{
  "adults": 2,
  "base_rent": "100.00",
  "campaign": "async_smoke",
  "check_in": "2026-04-19",
  "check_out": "2026-04-21",
  "children": 0,
  "fees": "5.00",
  "guest_email": "async-smoke@crog-ai.com",
  "guest_name": "Async Smoke",
  "guest_phone": "555-0100",
  "pets": 0,
  "property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "target_keyword": null,
  "taxes": "10.00"
}
```

### Legacy Snapshot
```json
{
  "base_rent": "100.00",
  "check_in": "2026-04-19",
  "check_out": "2026-04-21",
  "fees": "5.00",
  "metadata": {
    "campaign": "async_smoke",
    "guest_email_present": true,
    "target_keyword": null
  },
  "nights": 2,
  "pricing_source": "manual_payload",
  "property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "property_name": "The Rivers Edge",
  "raw_total": "105.00",
  "requested_property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "taxes": "10.00",
  "total_amount": "115.00"
}
```

### Sovereign Snapshot
```json
{
  "base_rent": "100.00",
  "check_in": "2026-04-19",
  "check_out": "2026-04-21",
  "fees": "5.00",
  "metadata": {
    "closer_mode": "local_contract",
    "notes": [],
    "orchestrator": "spark-node-2-leader",
    "signed_record": {
      "hmac_sig": "40d9a9f1e6e44d15778feefa82dbee31082063a8ab71baafd6a10d025b1523db",
      "quote_id": "02aec20c-5051-4224-b39a-d968e10bf065",
      "quoted_total": "121.30",
      "raw_total": "105.00",
      "tax_total": "16.30",
      "timestamp": "2026-03-20T12:50:18Z",
      "trace_id": "b182cdc6-dc42-41ca-9175-93bcfa0216fa"
    },
    "tax_rule": "fannin_county_v1"
  },
  "nights": 2,
  "pricing_source": "manual_payload",
  "property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "property_name": "The Rivers Edge",
  "raw_total": "105.00",
  "requested_property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "taxes": "16.30",
  "total_amount": "121.30"
}
```

## Comparison Report 2026-03-20T12:54:02Z

- Trace ID: `a6e718f1-7dc4-4980-91e9-fcae0e05c1bf`
- Legacy Total: `$115.00`
- Sovereign Total: `$126.30`
- Drift Status: `CRITICAL_MISMATCH`
- HMAC Signature: `04aad16f03a258d57deefd7a550df41ed5173b2b8cda3ab2a9bec9e4aa0f1cb0`
- Legacy Taxes: `$10.00`
- Sovereign Taxes: `$21.30`
- Tax Delta: `$11.30`
- Base Rate Drift: `0.0000%`

### Notes
- Shadow quote diverged beyond the accepted no-harm guardrail.

### Request Payload
```json
{
  "adults": 2,
  "base_rent": "100.00",
  "campaign": "async_smoke_2",
  "check_in": "2026-05-04",
  "check_out": "2026-05-07",
  "children": 0,
  "fees": "5.00",
  "guest_email": "async-smoke@crog-ai.com",
  "guest_name": "Async Smoke 2",
  "guest_phone": "555-0101",
  "pets": 0,
  "property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "target_keyword": null,
  "taxes": "10.00"
}
```

### Legacy Snapshot
```json
{
  "base_rent": "100.00",
  "check_in": "2026-05-04",
  "check_out": "2026-05-07",
  "fees": "5.00",
  "metadata": {
    "campaign": "async_smoke_2",
    "guest_email_present": true,
    "target_keyword": null
  },
  "nights": 3,
  "pricing_source": "manual_payload",
  "property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "property_name": "The Rivers Edge",
  "raw_total": "105.00",
  "requested_property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "taxes": "10.00",
  "total_amount": "115.00"
}
```

### Sovereign Snapshot
```json
{
  "base_rent": "100.00",
  "check_in": "2026-05-04",
  "check_out": "2026-05-07",
  "fees": "5.00",
  "metadata": {
    "closer_mode": "local_contract",
    "notes": [],
    "orchestrator": "spark-node-2-leader",
    "signed_record": {
      "hmac_sig": "e913216a20d4c074599f2b20472b0684756bfe5c0164ecd130d4fc364b3e06cf",
      "quote_id": "d3b98687-0a97-4493-a91b-c3c94e95359e",
      "quoted_total": "126.30",
      "raw_total": "105.00",
      "tax_total": "21.30",
      "timestamp": "2026-03-20T12:54:02Z",
      "trace_id": "a29f002d-5a0f-4aad-8752-bd40dd1d76a1"
    },
    "tax_rule": "fannin_county_v1"
  },
  "nights": 3,
  "pricing_source": "manual_payload",
  "property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "property_name": "The Rivers Edge",
  "raw_total": "105.00",
  "requested_property_id": "f66def25-6b88-4a72-a023-efa575281a59",
  "taxes": "21.30",
  "total_amount": "126.30"
}
```
