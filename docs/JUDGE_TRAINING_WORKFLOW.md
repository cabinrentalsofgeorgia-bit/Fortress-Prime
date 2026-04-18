# Judge Training Workflow

Phase 4e.3 — Step-by-step guide for training the first judge after labels accumulate.

## Prerequisites

1. Labels have accumulated: `SELECT task_type, COUNT(*) FROM capture_labels WHERE final_decision IS NOT NULL GROUP BY task_type;`
2. Godhead labeling is running (Phase 4e.1 timer active)
3. Base model `qwen2.5:7b` is accessible (it's already in Ollama — see step 3 below)

## Step 1: Check label volume

```sql
-- Confirm enough labels for target task type
SELECT task_type, COUNT(*) AS labeled, COUNT(*) FILTER (WHERE qc_reviewed_at IS NOT NULL) AS gary_reviewed
FROM capture_labels
WHERE final_decision IS NOT NULL
GROUP BY task_type
ORDER BY labeled DESC;
```

Need ≥ 50 labels per judge (JUDGE_MIN_EXAMPLES). For legal judges: aim for 200+ for quality.

## Step 2: Build training dataset

```bash
cd ~/Fortress-Prime/fortress-guest-platform

python3 -m src.judge.build_judge_dataset \
    --judge-name vrs_concierge_judge \
    --task-types vrs_concierge \
    --since "30 days ago" \
    --output /mnt/fortress_nas/judge-training/vrs_concierge_judge-$(date +%Y-%m-%d).jsonl \
    --dry-run   # check counts first

# Remove --dry-run when satisfied
python3 -m src.judge.build_judge_dataset \
    --judge-name vrs_concierge_judge \
    --task-types vrs_concierge \
    --since "30 days ago" \
    --output /mnt/fortress_nas/judge-training/vrs_concierge_judge-$(date +%Y-%m-%d).jsonl
```

## Step 3: Prepare base model in HF format

`qwen2.5:7b` is in Ollama (GGUF) but the trainer needs HuggingFace safetensors format.

**Option A: Download from HuggingFace** (if network allows):
```bash
source fortress-guest-platform/.env
huggingface-cli download Qwen/Qwen2.5-7B-Instruct \
    --local-dir /mnt/fortress_nas/models/Qwen2.5-7B-Instruct
```

**Option B: Already have it** — check:
```bash
python3 -m src.judge.base_model_locator qwen2.5:7b
```

## Step 4: Train the judge

```bash
# Dry run first
python3 -m src.judge.train_judge \
    --judge-name vrs_concierge_judge \
    --base-model qwen2.5:7b \
    --training-data /mnt/fortress_nas/judge-training/vrs_concierge_judge-$(date +%Y-%m-%d).jsonl \
    --output-dir /mnt/fortress_nas/judge-artifacts/vrs_concierge_judge-$(date +%Y-%m-%d)/ \
    --dry-run

# Real training (runs on GPU, ~20-30 min for 500 examples on GB10)
python3 -m src.judge.train_judge \
    --judge-name vrs_concierge_judge \
    --base-model qwen2.5:7b \
    --training-data /mnt/fortress_nas/judge-training/vrs_concierge_judge-$(date +%Y-%m-%d).jsonl \
    --output-dir /mnt/fortress_nas/judge-artifacts/vrs_concierge_judge-$(date +%Y-%m-%d)/
```

Check manifest after training:
```bash
cat /mnt/fortress_nas/judge-artifacts/vrs_concierge_judge-*/training_manifest.json | python3 -m json.tool
```

Quality gate: `final_loss < 0.3` (adjust based on baseline).

## Step 5: Deploy to spark-4

```bash
# Dry run
python3 -m src.judge.deploy_judge \
    --judge-name vrs_concierge_judge \
    --adapter /mnt/fortress_nas/judge-artifacts/vrs_concierge_judge-$(date +%Y-%m-%d)/ \
    --target-node 192.168.0.106 \
    --base-ollama-model qwen2.5:7b \
    --dry-run

# Deploy
python3 -m src.judge.deploy_judge \
    --judge-name vrs_concierge_judge \
    --adapter /mnt/fortress_nas/judge-artifacts/vrs_concierge_judge-$(date +%Y-%m-%d)/ \
    --target-node 192.168.0.106 \
    --base-ollama-model qwen2.5:7b
```

## Step 6: Verify on target node

```bash
ssh admin@192.168.0.106 "ollama list | grep vrs_concierge_judge"

# Quick smoke test
ssh admin@192.168.0.106 "ollama run vrs_concierge_judge:$(date +%Y%m%d) \
    'Prompt: When is checkout?\n\nResponse: 11am.\n\nEvaluate.'"
# Expected: JSON with decision and reasoning
```

## Step 7: Enable the judge

```bash
# Add to .env.dgx (so systemd picks it up)
echo "JUDGE_ENABLED=true" >> fortress-guest-platform/.env.dgx

# Restart backend
sudo systemctl restart fortress-backend

# Watch first judge evaluations in journal
sudo journalctl -u fortress-backend -f | grep -i "judge"
```

## Step 8: Monitor judge accuracy

```sql
-- Judge decision distribution
SELECT judge_decision, COUNT(*) FROM llm_training_captures
WHERE task_type = 'vrs_concierge' AND judge_decision IS NOT NULL
GROUP BY judge_decision;

-- Escalation rate (target < 30%)
SELECT
    ROUND(100.0 * COUNT(*) FILTER (WHERE judge_decision='escalate') / COUNT(*), 1) AS escalation_pct
FROM llm_training_captures
WHERE task_type = 'vrs_concierge' AND judge_decision IS NOT NULL;
```

Target: escalation rate 10-30%. Below 10% = judge too lenient. Above 30% = judge over-escalating.

## Rollback

```bash
echo "JUDGE_ENABLED=false" >> fortress-guest-platform/.env.dgx
sudo systemctl restart fortress-backend
```
