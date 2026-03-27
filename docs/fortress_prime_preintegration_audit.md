# Fortress Prime Pre-Integration Audit

Date: 2026-03-19

## Cluster Hardware Snapshot

- Nodes reached: `spark-node-1` (`192.168.0.104`), `spark-node-2` (`10.10.10.2`), `spark-3` (`10.10.10.3`), `Spark-4` (`10.10.10.4`)
- GPU topology (`nvidia-smi topo -m`): each node reports one `NVIDIA GB10` and four RoCE NICs (`rocep1s0f0`, `rocep1s0f1`, `roceP2p1s0f0`, `roceP2p1s0f1`) with `NODE/PIX` adjacency.
- Host memory per node: ~`121 GiB`

## RoCE Remediation Result

After `tools/cluster/remediate_roce.sh`:

- `spark-node-2`: all 4 links reached `ACTIVE/LINK_UP`, but 2 links later dropped due no partner on forced speed test.
- `spark-node-1`, `spark-3`, `Spark-4`: 2 links (`rocep1s0f0`, `roceP2p1s0f0`) consistently `ACTIVE/LINK_UP`; secondary links remain `DOWN/DISABLED`.
- Active links validate at `200000Mb/s` where partner is present.

## Capacity Result (Nemotron-3 120B target)

Using `python3 tools/cluster/model_capacity.py --node-mem-gib 121 --nodes 4 --reserve-os-gib 128 --model-target-gib 380`:

- Cluster total: `484 GiB`
- Reserved for OS/DB: `128 GiB`
- Usable for model + KV: `356 GiB`
- Target: `380 GiB`
- Result: `FAIL` with `24 GiB` shortfall

## Operational Recommendation

- Keep local-first inference path and cloud fallback redaction enabled.
- Treat dual-link-per-node (`2 x 200GbE`) as the minimum stable baseline before enabling high-throughput multi-node inference.
- If `380 GiB` model+KV budget is mandatory, add memory capacity or reduce model footprint via quantization/sharding and tighter KV policy.

## Focused Smoke Test Evidence

Executed against updated backend on `http://127.0.0.1:8110`:

- Tool discovery endpoint check:
  - `GET /api/v1/properties/availability?check_in=2026-04-10&check_out=2026-04-13&guests=2`
  - Response keys verified: `check_in`, `check_out`, `guests`, `results`
- Privacy router redaction check:
  - Input payload included `guest_name: "John Doe"`
  - Sanitized payload verified as `guest_name: "GUEST_ALPHA"`
- Chain of custody check (mock redirect patch):
  - `POST /api/v1/seo/redirects` with `source_path=/smoke-test-old`
  - Matching OpenShell audit row (`action=seo.redirect.write`) found
  - `entry_hash`: `86b9215bb3f0c8c08da6dde676d80f5522f0ec58510fda3369592de2d7a96325`
  - `signature` (HMAC): `6244015ec60bd5c1a205b3c44bad24dd32a9ad7d6693d33e36d48ce74e0035bb`
  - `prev_hash`: `f1309cb7e6edbcf6603a0a5c0136b260953bda7459c7c1b3851370ad3a282c74`
