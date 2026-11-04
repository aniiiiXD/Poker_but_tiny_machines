# Hosting design — Stack Theory pilot and beyond

Designed 2026-11-04 against the real deploy artifacts (`deploy/*.service`,
`Caddyfile`, `backup.sh`) and the app's actual constraints: one FastAPI API,
standalone workers that drive **Docker sandboxes on the same host**, SQLite in
WAL mode, no external service dependencies.

## Architecture (pilot)

```
                    ┌──────────────────────────────┐
  users ── HTTPS ──▶│  Caddy :443 (auto-TLS)       │
                    │   └─ reverse_proxy :8001     │
                    ├──────────────────────────────┤
                    │  arena-api.service           │  FastAPI · 2 uvicorn workers
                    │  arena-worker@1..2.service   │  2 workers · Docker sandboxes
                    │  Docker: campus-arena-bot    │  ── one container per bot match
                    │  SQLite (WAL) /srv/arena-data│  ── single writer, daily backup
                    │  cron: backup → offsite      │
                    └──────────────────────────────┘
        one VPS · 4 vCPU · 8 GB · Ubuntu 24.04 · Mumbai/your region
```

**Why one box, not Kubernetes/serverless:** the sandbox needs a Docker daemon
on bare metal; matches are stateful and CPU-bound; the pilot is 20–50 users.
One well-configured VPS beats a distributed system you can't debug. The
systemd units already exist — this is a provision-and-run, not a rewrite.

**Sizing:** 4 vCPU / 8 GB runs 2 concurrent sandbox matches (each `--cpus=1`,
128 MB) plus the API with headroom. `ARENA_WORKERS=2` on the worker units.
Scale = bigger box or a second worker box later (SQLite holds until ~ pilot
scale; the migration path is documented, not needed now).

**Provider options**

| Path | Cost | When |
|---|---|---|
| **A. Self-serve VPS** (Hetzner CPX31 / DO 4GB / Lightsail 4GB) | ~$12–25/mo | **Recommended** — you control it today; AWS EC2 perms are currently denied |
| B. AWS EC2 (per `plans/AWS_ACCESS_REQUEST.md`) | ~$25–40/mo | When the admin grants `ec2:RunInstances`; same runbook, AMI instead of ISO |

## Security posture (pilot)

- SSH keys only, root login disabled, `ufw`: 22/80/443 only
- Services run as user `arena`; systemd hardening already in the units
  (`NoNewPrivileges`, `ProtectSystem=strict`)
- Caddy: automatic Let's Encrypt, HSTS
- Secrets in `/etc/arena/arena.env` (chmod 600) — never in the repo
- Sandbox containers: `--network=none --cap-drop=ALL --read-only` (already
  enforced by `arena/sandbox.py` — the host only needs Docker)
- `unattended-upgrades` on; Docker log rotation (`max-size: 10m, max-file: 3`)
- Backups: `backup.sh` daily cron **+ offsite copy** (rclone to any S3/B2
  bucket — a VPS alone is not a backup)

## Email

`ARENA_SMTP_*` is already wired in `mailer.py`. Pilot: any transactional SMTP
(Resend/Mailgun/SES). Verify-domain once, set the five env vars, done.

## Monitoring (minimum viable)

- `healthchecks.io` free ping: cron curls `/api/health` every 5 min; silence =
  email. That's the whole on-call stack for a pilot.

## Deploy flow

`deploy/deploy.sh` (new): SSH to the box → `git pull` → `uv sync` → rebuild
sandbox images → `alembic`-less migrations run on app start (`db.initialize`)
→ restart services → curl `/api/health`. Rollback = `git checkout <prev>` +
rerun. See the runbook in this file.
