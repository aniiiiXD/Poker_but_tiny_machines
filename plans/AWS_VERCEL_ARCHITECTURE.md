# Campus Arena: AWS + Vercel deployment plan

Status: design only. No infrastructure has been provisioned. The AWS CLI currently has no usable credentials, and no existing Passkarwado permissions have been inspected. Do not reuse another product's IAM user or broad credentials for this project.

```text
Participant browser
       |
       v
Vercel: static React frontend + same-origin /api rewrite
       |
       v
AWS HTTPS load balancer / reverse proxy
       |
       v
AWS application service: FastAPI + GitHub webhook endpoint
       |                  |                 |
       v                  v                 v
PostgreSQL           private S3         email provider
users/events/jobs    submissions       verify/reset mail
       |
       v
Scheduler + queue --> isolated worker fleet --> game results / replays
                            |
                            +--> CPU poker/model workers
                            +--> future GPU kernel workers (separate fleet)
```

## Initial pilot

The present implementation is SQLite + local files + a Docker host. A single dedicated AWS EC2 instance with private persistent EBS storage can run the existing FastAPI process and a **single worker process** while Vercel hosts the static frontend. Set Vercel's `/api/*` rewrite to the public HTTPS API origin; preserve cookies and GitHub webhook bodies. Terminate TLS at an AWS load balancer or an appropriate reverse proxy. Use a real email transport, the GitHub App secrets, and a private EBS volume. Keep the database and submissions outside the checkout.

This is a pilot topology, not a reviewed security architecture for arbitrary public adversarial code. Run code execution on isolated compute rather than on a machine holding production secrets before public launch. Existing deployment unit files start multiple API workers and worker services; **do not use that configuration as-is**. Workers now have local SQLite leases, heartbeats and basic fencing; validate the new recovery behavior under realistic concurrent load before using multiple processes. Jobs that were already running before the lease migration have no lease and need operator review.

## Scale-ready target

1. Replace SQLite-specific access, schema and transactions with PostgreSQL and tested migrations; use RDS or another explicitly chosen managed PostgreSQL. Do not share SQLite WAL files between hosts.
2. Move immutable submission archives, code snapshots and replay artifacts from local paths into private, versioned S3. Validate size and checksums; use scoped, short-lived upload/download access. Current code does not yet implement S3.
3. Replace the local SQLite queue with a durable, visibility-timeout queue (for example SQS), preserving leases, heartbeats, fencing and idempotent result publication across hosts. Schedule rounds with a single elected coordinator or EventBridge Scheduler; persist deterministic round IDs and protect against duplicate scheduling. Current workers use SQLite jobs, not SQS.
4. Use dedicated ephemeral EC2 worker instances, separate instance roles and security groups. The current sandbox starts Docker containers via a host Docker daemon. ECS Fargate does not provide Docker-in-Docker or privileged containers; this worker cannot be moved there unchanged. See AWS [Fargate security considerations](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-security-considerations.html).
5. Isolate each untrusted execution at a suitable VM boundary; block network and instance metadata; do not expose the host Docker socket, AWS credentials, GitHub keys or database credentials to contestant code. Harden, patch, set quotas and review the threat model before launch. GPU device drivers need their own isolation and reset strategy.
6. Use separate roles for deployment, API, scheduler, artifact access and workers. Scope resource ARNs and actions to the minimum required. Keep the GitHub private key and webhook secret in a secrets manager; application environment must not be copied into bot sandboxes. Avoid static IAM keys on laptops.
7. Add monitoring, alerts, cost budgets, request/queue limits, tested backup and restore, audit logs and incident response. Establish a budget and workload estimate before choosing instance sizes.

## Auth, network and deployment

GitHub App: configure an OAuth callback at `https://<public-host>/api/github/callback`, a webhook at `/api/github/webhook`, user email read access, selected-repository content read access, push webhook events, a webhook secret and a private key. Restrict the installation to selected repositories. Confirm permission details against the [GitHub App documentation](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app).

Use `ARENA_SECURE_COOKIE=1`, exact `ARENA_ORIGINS`, `ARENA_PUBLIC_URL`, and GitHub configuration listed in `.env.example`. The API is stateful today: do not run it as a Vercel Function with local SQLite or local bot files and expect persistence. Vercel frontend hosting is compatible with the proposed API split, but no production rewrite or deployed project has been configured.

## Required engineering before launch

- Stress-test worker leases and fencing across process crashes, multiple workers and duplicate deliveries; migrate the queue for multiple hosts.
- Complete GitHub setup/connection UI and verify real GitHub App installation, login and webhook end to end.
- Migrate persistence and job queues before running API and workers on separate hosts.
- Add authentication/abuse limits around submissions and webhooks, instance isolation, observability, backup/restore and full end-to-end tests.
- Model projects currently run Python standard-library CPU inference only, with a 16 MiB project limit. GPU workers, package images and large model artifacts are not implemented.
- Budget controls and approval for AWS resource creation must be decided before provisioning; this document is not a deployment.
