# Local event operations

Run commands from `backend/` while the application server is running. These
commands act only on this project's local database. There is no preset admin
password, no automatic first-user admin promotion, and no public round control.

## Operator access

Register your own account in the website, then grant it operator access locally:

```sh
uv run python -m arena.cli make-admin your-email@example.com
```

This account can call `/api/admin/*` through its authenticated cookie. API
schemas are at `/docs`. Normal student accounts receive 403 responses.

## Run the founding event

```sh
uv run python -m arena.cli events
uv run python -m arena.cli start-build campus-open-001
```

Teams enter while registration/build is open. At the end of the build window,
the worker freezes every entered team's latest accepted submission and starts
round 1. Subsequent rounds start at the configured interval after the initial
build end, once the previous round is complete. Teams without an accepted bot
are excluded from that round. Later accepted submissions apply to later rounds.

For a local demonstration or retry of a failed round:

```sh
uv run python -m arena.cli run-round campus-open-001
```

This queues one real round immediately. Repeat only after it finishes; the CLI
rejects overlapping rounds. After the sixth round the event becomes completed.
The leaderboard uses round means weighted by round number. Exact ties share a
rank. No prize money or discretionary tie-break challenge is configured.

## Create an event

```sh
uv run python -m arena.cli create-event 'College Open' \
  --tables 8 --hands 50 --rounds 6 --build-minutes 60 --interval 1200 --starts-in 60
```

`--tables` is the number of iterations: every eligible team is seated once per
iteration, randomized into groups of eight. Empty seats are filled by copies of
submitted bots, which do not earn extra points. A larger event can use
`--tables 10000 --hands 200`; measure runtime and provide sufficient worker
capacity before advertising that scale. This pilot processes queued work serially.

`--sponsor 'Your confirmed sponsor'` sets a plain display name for an actual
sponsor. The platform has no invented partner names or logos.

## Sponsor inquiries

```sh
uv run python -m arena.cli inquiries
```

These are private locally stored submissions, not outgoing emails. Contact a
prospective sponsor through your own authorized channel when appropriate.

## Persistence and recovery

Back up `backend/data/` when the server is stopped, or use SQLite's backup API.
Sources are immutable version files in `data/bots`. Completed replays show all
cards retrospectively; opponents' cards are never provided in live observations.
Practice replays from signed-in users are accessible only to that user/team.
Exhibition, completed tournament and anonymous baseline-demo replays are public.

Restart the API after changing backend code. Startup recovers interrupted jobs
as failed and preserves queued jobs. Retry a failed scored round with run-round;
it freezes currently active sources again. Preserve logs if investigating a dispute.

The production frontend bundle can be served by `make serve`. For a public
rollout, configure a real domain/TLS, `ARENA_ORIGINS`, secure cookies, university
verification, email/recovery, backups, telemetry, and separate worker hosts before
accepting untrusted internet-scale traffic. The current setup intentionally binds
only to 127.0.0.1.
