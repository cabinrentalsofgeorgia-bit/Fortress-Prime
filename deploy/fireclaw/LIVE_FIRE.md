# Fireclaw live-fire validation (DGX / bare metal)

Run these on the host after kernel (`vmlinux.bin`) and rootfs (`agent_rootfs.ext4`) exist under `/srv/fortress/fireclaw/` (or your paths).

## Architecture note (x86_64 vs aarch64)

DGX Spark is often **aarch64**. The x86_64 kernel URL in older runbooks 404s on that hardware. List available guest kernels:

```bash
wget -q -O - "http://spec.ccfc.min.s3.amazonaws.com/?prefix=firecracker-ci/v1.7/$(uname -m)/vmlinux-&list-type=2" \
  | grep -oE 'firecracker-ci/v1\.7/[^<]+vmlinux-[^<]+' | head -20
```

Example aarch64 download (HTTP avoids some TLS proxy issues):

```bash
sudo wget --no-check-certificate -O /srv/fortress/fireclaw/vmlinux.bin \
  "http://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.7/aarch64/vmlinux-5.10.209"
```

Match the Firecracker **release tarball** to the same architecture (e.g. `firecracker-v1.7.0-aarch64.tgz` from GitHub releases).

## 1) Prerequisites

- `firecracker` binary on `PATH` or at `SANDBOX_FIRECRACKER_BIN`
- `python3`, `dd`, `mkfs.ext4`, `mount`
- Helper installed and runnable as root: `/usr/local/bin/fireclaw_run.py` (or repo path)
- Fortress `.env.dgx` (or environment) sets `SANDBOX_RUNTIME=firecracker`, `SANDBOX_*` paths — see `fortress-guest-platform/.env.dgx.example`
- **Backend user → root:** install a tight `sudoers` rule so the API user can run **only** `fireclaw_run.py` with `NOPASSWD`, then set `SANDBOX_FIRECRACKER_HELPER` to `backend/scripts/fireclaw_run_sudo.sh` (see that script).
- `pypdf` must be vendored into the guest image under `/opt/agent/vendor/` before PDF decontamination works.

## 1.5) Patch the guest image with `pypdf` and the latest `interrogate.py`

```bash
sudo mkdir -p /tmp/fireclaw-mount
sudo mount /srv/fortress/fireclaw/agent_rootfs.ext4 /tmp/fireclaw-mount
python3 -m pip install --target /tmp/fireclaw-pypdf pypdf
sudo mkdir -p /tmp/fireclaw-mount/opt/agent/vendor
sudo cp -R /tmp/fireclaw-pypdf/* /tmp/fireclaw-mount/opt/agent/vendor/
sudo install -m 755 deploy/fireclaw/rootfs-snippets/opt/agent/interrogate.py /tmp/fireclaw-mount/opt/agent/interrogate.py
sudo umount /tmp/fireclaw-mount
sudo rm -rf /tmp/fireclaw-mount /tmp/fireclaw-pypdf
```

## 2) Direct helper smoke test (no FastAPI)

Create a workdir and `request.json`:

```bash
sudo mkdir -p /tmp/fireclaw-smoke/run1
sudo tee /tmp/fireclaw-smoke/run1/request.json >/dev/null <<'EOF'
{
  "kernel": "/srv/fortress/fireclaw/vmlinux.bin",
  "rootfs": "/srv/fortress/fireclaw/agent_rootfs.ext4",
  "firecracker_bin": "/usr/bin/firecracker",
  "workdir": "/tmp/fireclaw-smoke/run1",
  "code": "print('hello from guest')",
  "timeout_seconds": 60,
  "vcpu_count": 1,
  "memory_mib": 512,
  "boot_args": "console=ttyS0 reboot=k panic=1 pci=off root=/dev/vda rw init=/sbin/init",
  "payload_size_mb": 32
}
EOF
sudo python3 /usr/local/bin/fireclaw_run.py /tmp/fireclaw-smoke/run1/request.json | tail -20
```

Expect a line containing `FIRECLAW_RESULT` with JSON and `exit_code` 0.

## 3) FastAPI `execute_python` path

With the backend service running under the same env:

- Trigger any flow that causes the orchestrator to call the `execute_python` tool with trivial code (e.g. `print(1+1)`).
- Confirm logs show `fireclaw_run_complete` and stdout contains `2` or the wrapped result.

## 4) Interrogate mode (PDF / single file, no `user_code.py`)

The helper supports **`"mode": "interrogate"`** and **`payload_host_path`** (absolute path to a file on the host). The file is copied as the **only** entry on the guest payload volume; `/sbin/init` runs `/opt/agent/interrogate.py`.

Example:

```bash
printf '%%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%%%EOF\n' > /tmp/dummy.pdf
sudo mkdir -p /tmp/fc-interrogate/run1
sudo tee /tmp/fc-interrogate/run1/request.json >/dev/null <<EOF
{
  "mode": "interrogate",
  "kernel": "/srv/fortress/fireclaw/vmlinux.bin",
  "rootfs": "/srv/fortress/fireclaw/agent_rootfs.ext4",
  "firecracker_bin": "/srv/fortress/fireclaw/firecracker",
  "workdir": "/tmp/fc-interrogate/run1",
  "payload_host_path": "/tmp/dummy.pdf",
  "code": "",
  "timeout_seconds": 120,
  "vcpu_count": 1,
  "memory_mib": 512,
  "boot_args": "console=ttyS0 reboot=k panic=1 pci=off root=/dev/vda rw init=/sbin/init",
  "payload_size_mb": 32
}
EOF
sudo python3 /path/to/fortress-guest-platform/backend/scripts/fireclaw_run.py /tmp/fc-interrogate/run1/request.json | tail -5
```

**API:** `POST /api/sandbox/fireclaw/interrogate` with multipart file upload — same guest path; staging files live under `SANDBOX_WORK_DIR/interrogate-staging/`. The route accepts an admin JWT **or** the trusted internal bearer configured by `INTERNAL_API_TOKEN` (falling back to `SWARM_API_KEY`).

## 4.5) Queue a synthetic hostile filing event

```bash
curl -X POST http://127.0.0.1:8100/api/rules/events/emit-docket-updated \
  -H "Authorization: Bearer $SWARM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "case_number": "SUV2026000013",
    "document_path": "/tmp/dummy.pdf",
    "filing_name": "dummy.pdf",
    "persist_to_vault": true
  }'
```

The VRS consumer should pick up the queued `docket_updated` event, call Fireclaw, then POST sanitized text to `/api/agent/tools/legal-threat-assessor`.

## 5) Cleanup

```bash
sudo rm -rf /tmp/fireclaw-smoke
```
