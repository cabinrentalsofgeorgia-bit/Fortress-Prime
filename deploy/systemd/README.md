# Fortress systemd baseline

These units codify the currently working live stack:

- `fortress-backend.service` -> FastAPI on `:8100`
- `fortress-dashboard.service` -> `frontend-next` on `:3001` via `next start`
- `fortress-event-consumer.service` -> Redis queue consumer for automation rules
- `fortress-deadline-sweeper.timer` -> daily 06:00 emission of `deadline_approaching` legal events

Both services load runtime configuration from:

- `fortress-guest-platform/.env`
- `fortress-guest-platform/.env.dgx`
- `/home/admin/Fortress-Prime/.env.security`

## Install

```bash
cd /home/admin/Fortress-Prime
sudo ./deploy/systemd/install_fortress_services.sh
```

## Notes

- `DB_AUTO_CREATE_TABLES` should remain `false` in live DGX runtime overlays.
- The install script rebuilds `frontend-next` before restarting the dashboard
  service so `.next` stays aligned with the checked-in source.
