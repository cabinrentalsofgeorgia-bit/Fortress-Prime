# Model NAS Storage Runbook

**Principle 3 of Iron Dome v6.1** — NAS-canonical model storage.
Every model (Ollama, NIM, HuggingFace) lands on NAS first. Nodes are caches.

---

## NAS layout convention

```
/mnt/fortress_nas/nim-cache/
  nim/                          # NIM Docker containers + weight caches
    <model-name>/
      <tag>/
        image.tar               # docker save output — full container image
        image.sha256            # digest for integrity check
      nim-weights-cache/        # mounted at /opt/nim/.cache inside the container
        <model-uuid>/           # NIM downloads weights here on first start
          ...
  ollama/                       # Ollama model blobs (future — when NAS-first enforced)
    <model-name>/
      <digest>/
        ...
  huggingface/                  # HuggingFace checkpoints
    <org>/<model>/
      ...
```

Current NIM model directories:
- `nim/nvidia-nemotron-nano-9b-v2/` — Deployment A (VRS concierge, spark-4)
- `nim/nemotron-nano-12b-v2-vl/` — Deployment C (Vision-language, spark-3)
- `nim/nemotron-3-nano-30b-a3b/` — Deployment B (Deliberation, DEFERRED)

---

## How to pull a NIM to NAS

```bash
# 1. Pull to local Docker daemon (run from any spark node with docker + NGC auth)
NGC_API_KEY=$(cat /etc/fortress/nim.env | grep NGC_API_KEY | cut -d= -f2)
echo "$NGC_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin

docker pull nvcr.io/nim/nvidia/<model-name>:<tag>

# 2. Save to NAS (creates a portable tar — node-independent)
NAS_DIR=/mnt/fortress_nas/nim-cache/nim/<model-name>/<tag>
mkdir -p "$NAS_DIR"
docker save "nvcr.io/nim/nvidia/<model-name>:<tag>" \
  | gzip > "$NAS_DIR/image.tar.gz"

# 3. Record digest for integrity
docker inspect "nvcr.io/nim/nvidia/<model-name>:<tag>" \
  --format '{{.Id}}' > "$NAS_DIR/image.sha256"

echo "Saved to $NAS_DIR"
```

Concrete examples:
```bash
# Deployment A — 9B VRS concierge
docker pull nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:latest
docker save nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:latest \
  | gzip > /mnt/fortress_nas/nim-cache/nim/nvidia-nemotron-nano-9b-v2/latest/image.tar.gz

# Deployment C — 12B Vision-Language
docker pull nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:latest
docker save nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:latest \
  | gzip > /mnt/fortress_nas/nim-cache/nim/nemotron-nano-12b-v2-vl/latest/image.tar.gz
```

NIM weight caches are handled automatically: the systemd unit mounts
`/mnt/fortress_nas/nim-cache/nim/<model>/nim-weights-cache` to `/opt/nim/.cache`
inside the container. NIM downloads weights on first start; subsequent starts
find them already present.

---

## How to re-hydrate a node from NAS

Use this when a node is rebuilt, repurposed, or the Docker image layer cache is lost.
No registry auth required — all data comes from NAS.

```bash
# On the target node (spark-4 for VRS, spark-3 for Vision):
NAS_DIR=/mnt/fortress_nas/nim-cache/nim/nvidia-nemotron-nano-9b-v2/latest

# Load image from NAS tar
docker load < "$NAS_DIR/image.tar.gz"

# Verify
docker images | grep nvidia-nemotron-nano-9b-v2

# Start service (weights already in NAS-mounted cache)
sudo systemctl start fortress-nim-vrs-concierge
```

---

## How to update (new tag/version)

Registry pulls are for UPDATES ONLY — not recovery.

```bash
# 1. Pull new version to NAS first
NEW_TAG=1.1  # example
NAS_DIR=/mnt/fortress_nas/nim-cache/nim/<model-name>/$NEW_TAG
mkdir -p "$NAS_DIR"
docker pull nvcr.io/nim/nvidia/<model-name>:$NEW_TAG
docker save nvcr.io/nim/nvidia/<model-name>:$NEW_TAG | gzip > "$NAS_DIR/image.tar.gz"

# 2. Verify integrity before deploying
# 3. Update the systemd unit to use new tag
# 4. Reload from NAS on target node (no registry pull on target)

# Old version NAS copy stays — do NOT delete until explicitly decided.
```

---

## Retention policy

NAS copies are kept **indefinitely** until Gary makes an explicit prune decision.

Never delete from NAS just because a model was removed from a node.
A pruned NAS copy means re-downloading from NVIDIA registry, which requires
authentication and network access. NAS is the single source of truth for
deployed models.

Estimated NAS space per model:
- nvidia-nemotron-nano-9b-v2: ~18GB image + ~18GB weights = ~36GB total
- nemotron-nano-12b-v2-vl: ~24GB image + ~24GB weights = ~48GB total
- nemotron-3-nano-30b-a3b (deferred): ~60GB + ~60GB = ~120GB

Current NAS capacity: 54TB total, 9.3TB used, 44TB free. No space concern.
