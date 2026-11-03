# Stack Theory

An online Python bot-building competition for college students. A new independent
project in this directory, with its frontend and backend kept separate from
Passkarwado and from each other.

The backend also contains a GitHub App integration and an initial CPU model
project track. GitHub requires a configured GitHub App; the workshop provides
repository connection and model upload screens. See [backend integration notes](plans/GITHUB_MODEL_BACKEND.md), the
[AWS and Vercel deployment plan](plans/AWS_VERCEL_ARCHITECTURE.md), and the
[games and GPU kernel challenge report](plans/GAMES_AND_GPU_KERNELS_REPORT.md).

## Open the application

Built website: **http://127.0.0.1:8001**
Development website: **http://127.0.0.1:5173**
API and API documentation: **http://127.0.0.1:8001/docs**

Open `bot-arena.code-workspace` in your editor for the complete workspace.

Requirements: Python 3.12, uv, Node.js, pnpm, and a running Docker-compatible engine.
On this Mac, a dedicated Colima profile named `bot-arena` has been created.

```sh
colima start --profile bot-arena --cpu 2 --memory 3 --disk 12
make install
make sandbox
make dev
```

On other machines, start your Docker engine instead of Colima. If several Docker
contexts exist, set `ARENA_DOCKER_CONTEXT` before starting the backend. Bot source
is streamed into the container; no host directories or Docker socket are mounted
inside bot containers. Ctrl-C stops both application processes launched by `make dev`.

For a single-process local preview of the production frontend bundle:

```sh
make serve
# Website now served by FastAPI at http://127.0.0.1:8001
```

## What works

- Three public destinations: Arena, Sponsors, Contact. The arena has a procedural
  interactive 3D table, illustrative dealing, motion control, and a static fallback.
  Real exhibition replays and all competition tools remain inside the arena.
  No invented human entrants or partner endorsements.
- Registration/login/logout with hashed passwords and revocable HTTP-only sessions.
- Solo/two-person teams, private invitation codes, event entry and profiles.
- Python workshop with local drafts, downloadable starter kit, saved versions,
  source validation and a five-minute submission cooldown.
- Real sandboxed Python bot execution. No network or external model/API calls.
  A trusted supervisor enforces the configured decision deadline; the submitted
  agent never runs in the API process.
- Queued practice tables with progress/errors, results, faults and private team replays.
  Anonymous practice uses built-in strategies and its completed replays are public.
- Replay playback, stepping, hand selection, action history and retrospective cards.
- Real no-limit Hold'em rules through PokerKit, side pots, rotating positions,
  elimination scoring and exact ICM allocation at a hand cap.
- Scheduled build phases and six-round events, immutable per-round submission
  snapshots, random tables, non-scoring filler copies, weighted results and rankings.
- Operator API/CLI for events, starting rounds, and reading sponsor inquiries.
- SQLite persistence for accounts, teams, source versions, runs, events and results.
  Workers use expiring leases and heartbeats; expired claimed jobs are marked
  failed, and an operator can retry a failed round. Jobs already running before
  the lease migration need operator review.
- GitHub App OAuth, repository connection, signed push webhooks and commit-based
  validation APIs, once an App is configured. An initial CPU-only model track
  accepts bounded multi-file projects and local weights. Both have workshop UI;
  GitHub requires an App to be configured.

## Try the complete student flow

1. Open the website and create an account (no paid services are needed).
2. Create a team, even when competing solo. A teammate can join with your code.
3. Open Workshop, edit the supplied Python agent, and save a submission.
4. Run **Practice with my bot**. Open the resulting replay and inspect the decisions.
5. Join **Stack Theory Open · Founding round**. The operator can start its build phase
   and scored rounds using the commands in `OPERATIONS.md`.

The exhibition leaderboard comes from actual built-in bot games. Student results
appear after a scored event. The opening event is a **local pilot**, using eight
iterations per round and a 50-hand cap; each event displays its configuration.
Operators can configure up to 10,000 iterations and a 200-hand cap. Large runs
are resource-intensive and run serially in this initial coordinator.

## Project structure

```text
frontend/                   React + TypeScript + Vite website and arena
backend/arena/app.py         HTTP API and optional built frontend serving
backend/arena/db.py          SQLite schema and transactions
backend/arena/security.py    Passwords, sessions and request limits
backend/arena/engine.py      PokerKit table orchestration and ICM
backend/arena/baselines.py   Eight built-in reference strategies
backend/arena/worker.py      Durable queue, schedule, snapshots and scoring
backend/arena/sandbox.py     Host Docker transport; never imports submitted code
backend/sandbox/             Isolated supervisor, Dockerfile and security notes
backend/starter-kit/         Agent, protocol smoke test and guide
backend/tests/               Engine, API, worker and actual Docker tests
backend/data/                Local database and accepted sources (gitignored)
scripts/dev.py              Development process launcher
```

## Validate

```sh
make test
```

Docker integration tests run when Docker and `campus-arena-bot:local` are present;
otherwise they are explicitly skipped. The suite covers gameplay conservation,
known hands/side pots, observation privacy, invalid/failing bots, sandbox isolation,
timeouts, authentication/ownership, team size, frozen submissions, scoring, and a
complete real sandboxed round. See `backend/sandbox/README.md` for timing details.

## Scope and operating limits

This is a functioning **local pilot**, not a deployed public service. No cloud
resources, payment accounts, sponsor emails or paid model APIs are connected.
Sponsor inquiries are stored locally for the operator; no email is sent.
University affiliation is self-reported. Email verification and password reset
are implemented; without SMTP their links are written to the local outbox.
Distributed workers, production monitoring and public hosting are not configured.
Use the single-process local setup until the new worker leases have been
stress-tested with multiple processes.

The classic track's 1 ms default is a supervisor-enforced wall-time cutoff inside the sandbox,
including worker scheduling and serialization. This is not a hard real-time system;
load can produce timeouts. Initialization and Docker startup have separate limits.
Each table resets the agent using a new container. Students submit a single source
file up to **100 KiB** with standard-library dependencies. The initial model track
accepts project archives up to 16 MiB (compressed and uncompressed), includes Python and NumPy 2.1.3, and supports CPU inference with local weights. It has a
512 MB sandbox memory limit and a 50 ms practice decision budget. External model
APIs, other third-party ML libraries, large model artifacts and GPU execution are not
supported by this pilot.

Stack Theory is inspired by the publicly described bot-building format; it is
not affiliated with Sequoia, OpenAI, or Citadel Securities and does not claim to
implement their private starter kit or unreleased poker variant. Source references
are in `REFERENCES.md`.
