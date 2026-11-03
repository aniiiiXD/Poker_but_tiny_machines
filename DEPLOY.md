# Running Stack Theory in production

**Status:** This older single-host guide is not a production-readiness guarantee.
For the current AWS/Vercel design, GitHub integration, worker lease limitations,
model runtime and remaining launch work, see [the deployment plan](plans/AWS_VERCEL_ARCHITECTURE.md)
and [backend integration notes](plans/GITHUB_MODEL_BACKEND.md). Do not start the
multi-process services below as a public deployment without the testing and
isolation described there.

One machine is enough for a pilot: the API serves the built frontend and the
database; separate worker processes claim jobs from the queue and drive Docker.

## Layout

```
/srv/arena            repo checkout (uv venvs inside backend/, dist inside frontend/)
/srv/arena-data       ARENA_DATA_DIR: arena.sqlite, bots/, outbox/, replays media
```

## Environment (backend)

| Variable | Meaning |
|---|---|
| `ARENA_DATA_DIR` | data directory (default `backend/data`) — put it outside the repo |
| `ARENA_ORIGINS` | allowed CORS origins, comma-separated (your public origin) |
| `ARENA_SECURE_COOKIE` | `1` when serving over HTTPS |
| `ARENA_PUBLIC_URL` | public base URL used in verification/reset links |
| `ARENA_EMBEDDED_WORKER` | `0` in production: jobs run in standalone worker services |
| `ARENA_WORKERS` | execution slots per worker service (start with 4) |
| `ARENA_SUBMISSION_COOLDOWN` | seconds between submissions per team (default 300) |
| `ARENA_SMTP_HOST/PORT/USER/PASS`, `ARENA_MAIL_FROM` | real email; unset = local outbox |
| `ARENA_ADMIN_KEY` | not used by the app; organizer accounts are `role='admin'` in the DB |

## Build + first run

```bash
cd backend && uv sync --python 3.12
cd ../frontend && pnpm install --frozen-lockfile && pnpm build
cd ../backend && uv run python -c "from arena import db; db.initialize()"
```

Create the organizer: register through the UI, then
`sqlite3 $ARENA_DATA_DIR/arena.sqlite "UPDATE users SET role='admin' WHERE email='you@example.edu'"`.

Build the sandbox image **before creating events** (the digest is pinned at
event creation): `make sandbox`.

## Services

`deploy/arena-api.service` and `deploy/arena-worker@.service` are systemd
units. Install:

```bash
sudo cp deploy/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arena-api
sudo systemctl enable --now arena-worker@1 arena-worker@2
```

Each `arena-worker@N` runs `python -m arena.worker --workers 4`; jobs are
claimed atomically, so any number of worker services can share the database.
The API must run with `ARENA_EMBEDDED_WORKER=0` when workers are external.

## TLS

`deploy/Caddyfile` is a minimal reverse proxy: automatic HTTPS for one domain,
proxying to the API on 127.0.0.1:8001, WebSocket-safe. nginx equivalents: proxy
`/` to 8001 with `proxy_set_header Host $host;` and standard upgrade headers.

## Backups

`deploy/backup.sh` runs an online `sqlite3 .backup` plus a copy of `bots/`,
keeps 14 days. Cron it daily:

```cron
30 4 * * * /srv/arena/deploy/backup.sh >> /var/log/arena-backup.log 2>&1
```

Restore: stop services, replace `arena.sqlite` + `bots/`, start services.

## Updates

```bash
cd /srv/arena && git pull
cd backend && uv sync --python 3.12
cd ../frontend && pnpm install --frozen-lockfile && pnpm build
cd .. && make sandbox
sudo systemctl restart arena-api arena-worker@1 arena-worker@2
```

Schema migrations run automatically on API/worker boot (`db.initialize()` is
idempotent, columns and tables are added in place).

## Health & operations

- `GET /api/health` → API up, Docker up, sandbox image present.
- Worker logs: `journalctl -u arena-worker@1 -f` (claims, completions, faults).
- Score history is append-only: `score_events` is hash-chained;
  `GET /api/admin/score-events` returns `chain_valid`.
- Disputes: `GET /api/admin/hand-logs?round_id=...` → per-table seed + actions;
  combined with the frozen submission sha256 this reproduces any table exactly.
- Never rebuild the sandbox image while a round is running: events pin the
  image id, but the running container is the one that finishes the table.
