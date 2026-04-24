# Fortress secrets — `pass`-backed runtime loader

Runtime credentials (mailbox passwords, OAuth refresh tokens, API keys
that should never live in `.env`) are stored in
[pass](https://www.passwordstore.org/) and resolved into the worker's
process environment by `fortress-load-secrets` at service start.

## Files in this directory

| File | Installed to | Mode |
|---|---|---|
| `fortress-load-secrets.sh` | `/usr/local/bin/fortress-load-secrets` | `0755` |
| `secrets.manifest` | `/etc/fortress/secrets.manifest` | `0640` (root:root) |
| `../systemd/fortress-arq-worker.service.d/00-secrets.conf` | `/etc/systemd/system/fortress-arq-worker.service.d/00-secrets.conf` | `0644` |
| `install.sh` | (run from repo, not installed) | `0755` |

## Install / upgrade

```bash
sudo bash deploy/secrets/install.sh
```

Idempotent — re-run after pulling repo updates.

## Adding a new secret

1. Append a row to `deploy/secrets/secrets.manifest`:
   ```
   MY_NEW_VAR    fortress/category/entry-name
   ```
2. Store the value:
   ```
   pass insert fortress/category/entry-name
   ```
3. Reinstall the manifest + restart:
   ```
   sudo bash deploy/secrets/install.sh
   sudo systemctl restart fortress-arq-worker
   ```

## gpg-agent — persistent passphrase cache

`fortress-load-secrets` runs as the `admin` user via the worker
service (`User=admin` in the unit). For systemd to decrypt pass
entries unattended, the GPG key's passphrase must be cached **for
that user's gpg-agent**, and that cache must survive long enough to
cover service restarts.

Configure once as the admin user:

```bash
mkdir -p ~/.gnupg
chmod 700 ~/.gnupg
cat >> ~/.gnupg/gpg-agent.conf <<EOF
default-cache-ttl 34560000
max-cache-ttl     34560000
EOF
gpg-connect-agent reloadagent /bye
```

`34560000` seconds ≈ 400 days. Pass-through over a host reboot is
**not** automatic — gpg-agent state is in memory only. After a host
reboot, re-prime the cache:

```bash
pass show fortress/mailboxes/legal-cpanel >/dev/null   # enter passphrase once
```

Until you do, `systemctl restart fortress-arq-worker` will fail
ExecStartPre with `gpg: decryption failed: No secret key`. The worker
will not enter its poll loop — preferred to silently running with
stale or missing secrets.

## How the systemd drop-in works

```
[Service]
RuntimeDirectory=fortress
RuntimeDirectoryMode=0700
ExecStartPre=/usr/local/bin/fortress-load-secrets --output /run/fortress/secrets.env
EnvironmentFile=-/run/fortress/secrets.env
```

`/run` is tmpfs — secrets never touch the disk. `RuntimeDirectory`
gives systemd ownership of the dir, including auto-cleanup on stop.
`EnvironmentFile=` is re-read on every service start, so a manifest
update + restart cycle picks up new entries with no code change.

If `pass show` fails for any entry, ExecStartPre exits non-zero,
systemd skips ExecStart, and the journal records which variable failed
(by name only — never the value). The previous worker process keeps
running until it dies on its own or you intervene.

## Removing the loader

```bash
sudo rm /etc/systemd/system/fortress-arq-worker.service.d/00-secrets.conf
sudo systemctl daemon-reload
sudo systemctl restart fortress-arq-worker
```

The worker reverts to reading only `fortress-guest-platform/.env`.
