# Fireclaw (Firecracker) cell

This directory documents the **guest rootfs** snippets that must be baked into `agent_rootfs.ext4` so the Fortress backend can run `execute_python` inside a microVM.

Host-side orchestration lives in:

- [`fortress-guest-platform/backend/scripts/fireclaw_run.py`](../../fortress-guest-platform/backend/scripts/fireclaw_run.py) — loop-mounts the payload ext4, writes Firecracker JSON, runs `firecracker --no-api --config-file …` (must run as **root**). `--no-api` avoids binding the default `/run/firecracker.socket` on concurrent runs. Supports `mode: execute_python` (writes `user_code.py`) or `mode: interrogate` (copies `payload_host_path` as the sole payload file).
- [`fortress-guest-platform/backend/services/fireclaw_runner.py`](../../fortress-guest-platform/backend/services/fireclaw_runner.py) — Backend: writes `request.json` and invokes the helper (`run_firecracker_python`, `run_firecracker_interrogate`).
- **Admin HTTP:** `POST /api/sandbox/fireclaw/interrogate` — multipart upload → staging file → `run_firecracker_interrogate` (see [`backend/api/fireclaw.py`](../../fortress-guest-platform/backend/api/fireclaw.py)).

## Rootfs layout

Copy the files under `rootfs-snippets/` into the mounted ext4 when building the image (after `docker export` or equivalent):

| Source | Target on guest |
|--------|------------------|
| `rootfs-snippets/sbin/init` | `/sbin/init` (mode 755) |
| `rootfs-snippets/opt/agent/exec_user.py` | `/opt/agent/exec_user.py` |
| `rootfs-snippets/opt/agent/interrogate.py` | `/opt/agent/interrogate.py` |
| vendored `pypdf` package | `/opt/agent/vendor/pypdf` |
| vendored `pypdf-*.dist-info` | `/opt/agent/vendor/pypdf-*.dist-info` |

`init`:

1. Mounts `proc`, `sysfs`, and `devtmpfs` on `/dev` (needed for `/dev/vdb`).
2. Mounts a **tmpfs** on `/mnt` (the virtio root ext4 is read-only in Fireclaw; you cannot mkdir on it).
3. Mounts the payload volume at `/mnt/payload`.
4. If `user_code.py` exists (Fortress `execute_python`), runs `exec_user.py` and prints a `FIRECLAW_RESULT{...}` line on the serial console.
5. Otherwise runs `interrogate.py`, which uses `pypdf` to extract and sanitize hostile PDF text and emits a **single-line JSON** object with `metadata` and `sanitized_content`.
6. Reboots the guest so Firecracker exits.

## Guest decontamination contract

`interrogate.py` must keep stdout to **one JSON line** so `fireclaw_serial.py` can parse it as the last JSON-looking line from the serial console.

Expected shape:

```json
{
  "status": "success",
  "metadata": {
    "file_name": "motion.pdf",
    "file_size_bytes": 12345,
    "pages": 7,
    "sha256_hash": "..."
  },
  "sanitized_content": "..."
}
```

## Vendoring `pypdf` into the guest

`pypdf` is not provided by the host backend environment; it must exist **inside** the guest rootfs. A simple host-side way to vendor it during image maintenance is:

```bash
python3 -m pip install --target /tmp/fireclaw-pypdf pypdf
sudo mkdir -p /tmp/fireclaw-mount/opt/agent/vendor
sudo cp -R /tmp/fireclaw-pypdf/* /tmp/fireclaw-mount/opt/agent/vendor/
```

That keeps the dependency pure-Python and avoids chrooting into the image.

## Kernel command line

Default in backend settings (overridable via `SANDBOX_KERNEL_BOOT_ARGS`):

```text
console=ttyS0 reboot=k panic=1 pci=off root=/dev/vda rw init=/sbin/init
```

## Privileges

`fireclaw_run.py` uses `mount -o loop`. Run the helper as root, e.g.:

```bash
sudo install -m 755 fortress-guest-platform/backend/scripts/fireclaw_run.py /usr/local/bin/fireclaw_run.py
```

Then configure `sudoers` so the Fortress backend user may execute `/usr/local/bin/fireclaw_run.py` with NOPASSWD, **only** that path.

## Firecracker JSON: `serial`

If your Firecracker build rejects `"serial": {"type": "Stdout"}`, check your version’s config-file schema and adjust `fireclaw_run.py` accordingly (or temporarily omit the `serial` block and use the API socket to attach serial).

## Live-fire checklist

See [LIVE_FIRE.md](./LIVE_FIRE.md).
