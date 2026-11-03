# GitHub and model backend: implementation notes

This is a local implementation under development, not a public production deployment. GitHub authorization requires a real configured GitHub App; the end-to-end service has not been authenticated against one yet. The React workshop exposes GitHub connection and model upload flows; real GitHub authorization still needs configuration.

## GitHub sign-in and repository connection

Configure the six GitHub variables shown in `.env.example`. The private key is a local PEM file accessible to the API/worker account; OpenSSL must be installed. Set up a GitHub App with a webhook secret, callback URL, permission to read the user's verified email address and read-only repository contents, and push events. The App must be installed on the selected repositories. OAuth user access tokens are used only in the callback; they are not stored.

- `GET /api/github/login`: start GitHub login or link the current signed-in account. New accounts require a verified primary GitHub email. To prevent account takeover, an existing email/password account must log in before linking its GitHub identity.
- `GET /api/github/discover` starts an authorization flow; after it returns, `GET /api/github/discovered` lists accessible installations and repositories for ten minutes. The workshop lets users select from the discovered repositories.
- `POST /api/github/connect`: while signed in and on a team, send `installation_id`, `repository_id`, `branch`, and optional `track` (`classic` or `model`). The response has an authorization `url`; redirect the same browser to it. The callback verifies the user can access that installation and repository before connecting it.
- `GET /api/github/repositories` and `DELETE /api/github/repositories/{id}`: team-owned connections.
- `POST /api/github/repositories/{id}/sync`: snapshot and queue the selected branch's current commit. Subsequent matching, signed pushes also enqueue validation.
- `GET /api/github/jobs`: team-private validation status and commit.
- `POST /api/github/webhook`: signed GitHub push receiver; repeated delivery IDs are ignored.

A classic repo contains root `agent.py` with an `Agent.act` method. A model repo contains root `agent.py` plus its Python files and local weights. Model repos are fetched as a bounded Git tree, then placed in a deterministic ZIP. The worker records the Git commit, validates the project, runs a sandbox smoke game, and activates a successful latest submission. A tournament snapshot refers to the immutable submission ID and source/archive digest. Replays and score records retain their existing ownership rules.

## Model project API

`GET /api/models/tracks` describes current limits. `POST /api/models/submissions?name=...` accepts an `application/zip` request body for a verified, authenticated team and returns a validation job ID. Poll the existing `/api/jobs/{id}` endpoint. ZIPs have a 16 MiB compressed and uncompressed cap, max 100 files, no symlinks/encrypted entries or path traversal, and must include root `agent.py`. The archive can hold simple weights such as JSON or binary files. Submitted code can import Python standard-library modules, NumPy 2.1.3 and files within the project. CPU model execution is limited to 512 MB and has a 50 ms default decision budget in model practice; GPUs and external network access are unavailable.

After changing the supervisor, build both runtime images using `make sandbox` before running model jobs. An event created by the admin API can specify `track: "model"`; only an active accepted model bot is eligible for that event. The existing database has a single active submission per team, so a team cannot currently keep separate active classic and model submissions simultaneously.

`GET /api/models/starter/download` returns a NumPy example project. Teams can save an optional research profile with `PUT /api/models/showcase`; drafts remain private until `published` is true. `GET /api/models/showcase/mine` returns the team's own profile, and `GET /api/models/showcase` lists published profiles. `GET /api/events/{id}/metrics` reports per-round table counts and a simple standard error with an explicit caveat about correlated outcomes.

## Known limitations

- No GitHub App is configured, and no real GitHub OAuth/webhook integration test has been performed.
- The GitHub connection UI is implemented, but installation, discovery, authorization and real signed pushes have not yet been exercised against a configured GitHub App. The backend verifies repository access before binding.
- No S3, large-model support, arbitrary dependency installation, GPU execution, public deployment, multi-host queue is implemented. ZIP/model caps are intentionally small for this first CPU implementation.
- Manual ZIP upload is available alongside the GitHub model path. Uploaded or GitHub code runs only in the sandbox, but this container setup has not received a public adversarial security review.
- Build a new sandbox image before using model projects. Events pin an image at creation; existing events can point to an older image that cannot run model projects.
- Workers claim jobs with expiring SQLite leases and heartbeat them; expired jobs are failed and cannot publish fenced results. Legacy jobs already running without a lease need operator review. The recovery system still needs multi-process stress testing and is not a multi-host queue.
