# Production backlog

Must-haves before hosting a real event, then integrity, polish, scale. Marked `[x]` as they land.

## First priority: GitHub login and bot submissions

Local backend implemented for GitHub App OAuth, repository discovery/authorization, signed push webhooks, commit snapshots and queued sandbox validation. The GitHub App and UI still need setup and a real end-to-end test; see [implementation notes](plans/GITHUB_MODEL_BACKEND.md).

- [ ] Let participants sign in with GitHub and create or link their Campus Arena account. Keep repository access separate from login.
- [ ] Provide a starter repository with the bot interface and instructions. Let a team connect a selected public or private repository and branch through a GitHub App with only the permissions needed.
- [ ] On a push to the connected branch, verify the webhook signature, fetch the exact commit, and create a team-owned submission tied to the repository, branch, and immutable commit SHA. Handle duplicate deliveries safely.
- [ ] Run a simple server-side validation pipeline: check the submission against the event's file and resource limits, then run a smoke test in the isolated bot sandbox. Show queued, testing, accepted, and failed states with useful errors.
- [ ] Allow an accepted commit to be used for practice and freeze the exact accepted commit for each scheduled tournament round. Show the commit and results in the arena; later pushes must not change an in-progress round.
- [ ] Run official games on Arena workers using the existing poker engine and sandbox. Keep GitHub credentials out of bot execution; GitHub Actions checks may be offered separately but do not determine official results.
- [ ] Fix worker startup recovery so starting another API or worker process cannot mark an active job owned by another process as failed. Verify retries, scheduling, and the full login-to-replay flow before public launch.

The initial category uses the existing single-file Python limits. Larger codebases and model artifacts need separately defined categories, storage, validation, and worker resources.

## Second priority: model-based poker competition

Give participants a way to submit their own poker-playing model projects, beyond the single-file Python bot category. They can train models themselves and submit code plus an inference artifact; the arena runs inference during games. An initial CPU-only, standard-library project track with a 16 MiB ZIP limit is implemented locally. Larger projects, external ML libraries, GPUs and public deployment remain future work.

- [ ] Define tracks with published, equal rules within each event: a lightweight CPU track and a larger model track. Decide resource limits, eligible model types, dependency policies, decision time, hardware, and whether GPU inference is supported before opening each track.
- [ ] Extend GitHub submissions to accept a structured project and a versioned model artifact. Record the exact code commit, artifact checksum, runtime image, and category rules for reproducibility; never fetch arbitrary model files during a live game.
- [ ] Build an isolated, resource-limited execution environment for multi-file projects and model inference. Validate artifact size and format, bound startup, memory, compute and decision time, and keep network access and platform credentials unavailable to submitted code during play.
- [ ] Add practice against published baselines and evaluation across many seeded games, opponent styles and seating positions. Report uncertainty, poker performance, runtime, memory usage, failures and compute cost alongside replay links. Freeze submissions before scored runs.
- [ ] Design an engaging competition experience: ranked seasons, team profiles, public rules, challenge events and a research showcase where participants can explain their approach without being required to disclose private code or model weights.
- [ ] Develop optional partner-ready challenges around efficient inference, decision-making under uncertainty, robustness and constrained compute. Offer transparent aggregate results and an opt-in demo or research showcase; only name sponsors or promise prizes after an agreement.
- [ ] Test the complete submission-to-scoring flow, verify that participants have rights to submitted artifacts, document data retention and acceptable use, and establish capacity and cost limits before opening the track publicly.

Model training happens outside the live tournament in the initial design. GPU access, training credits and external model API calls are future choices, not promised capabilities.

## Must-have before a real event
- [x] 1. Email verification + password reset (mailer with SMTP-or-outbox fallback, verify/reset flows, gate submissions on verified email)
- [x] 2. Standalone worker process (`python -m arena.worker`), atomic job claims, safe restart
- [x] 3. Worker pool (`ARENA_WORKERS=N` threads, atomic claiming, no double-scoring)
- [x] 4. Sandbox image digest pinned per event (rounds run the pinned image id, not a mutable tag)
- [x] 5. Hand logs as first-class artifacts (`log_` rows: seed, seating, per-hand actions, per table, always)
- [x] 6. Append-only scoring log (hash-chained `score_events`, corrections append, never mutate)
- [x] 7. Deployment story (systemd units for api+workers, TLS reverse proxy, backups, env config docs)

## Integrity & trust
- [ ] 8. Plagiarism detection (sha256 cross-team match + AST similarity report)
- [ ] 9. Anti-abuse telemetry (per-bot timeout/memory-kill/fault stats for organizers)
- [ ] 10. Audit dashboard (frozen submissions per round, seat maps, dispute replay from seed)
- [ ] 11. API tokens per team (hashed, rotatable, scoped) for CLI submission
- [ ] 12. Account deletion preserving anonymous round history

## Product polish
- [ ] 13. Real-device mobile pass
- [ ] 14. Frontend smoke tests (auth/submit/practice flows)
- [ ] 15. Live round spectating (websocket feed)
- [ ] 16. Accessibility audit post-rebuild
- [ ] 17. Retry-After handling everywhere a 429 lands

## Scale & ambition
- [ ] 18. Compiled mass-simulator (seed-parity-tested against the Python engine)
- [ ] 19. Pluggable poker variants (PokerKit, revealed at build start)
- [ ] 20. Email sending service in production config
- [ ] 21. Sponsor inquiry workflow for organizers
