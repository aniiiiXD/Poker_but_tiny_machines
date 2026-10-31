# Submitted Python isolation

Build from the backend folder:

```sh
docker build -t campus-arena-bot:local sandbox
ARENA_DOCKER_CONTEXT=colima-bot-arena uv run pytest tests/test_sandbox.py
```

`ContainerBot.reset()` starts a fresh container and Agent for a table. Source
is bounded to 100 KiB and streamed through stdin; **no host files or sockets are
mounted**. The host never imports or executes submitted Python. Missing Docker
or image fails closed. `ARENA_DOCKER_CONTEXT` is optional; otherwise the active
Docker context is used.

Docker provides a private PID namespace, no external network, read-only root,
128 MB memory and swap ceiling, 32 process limit, one CPU, and a 16 MB temporary
filesystem. All capabilities are dropped except SETUID/SETGID during startup.
Trusted PID 1 forks the worker, which drops to UID/GID 65534 before compiling
the source. PID 1 drops to 1000, so the worker cannot signal or ptrace it. Both
lose effective capabilities. Docker's default seccomp profile remains enabled
and no-new-privileges prevents acquiring privileges through exec.

The supervisor measures the **wall-clock** interval from dispatch to complete
worker reply. Default budget is 1 ms, including scheduling, JSON parsing and
serialization. Docker/host transport is excluded; no worker-reported duration
is trusted. This is deliberately strict: a busy host can fault a fast bot.
Module import/constructor gets a separate two-second budget. Docker startup
gets a separate 15-second transport allowance. The act transport is bounded to
one second per write/read. Requests and responses have fixed size limits.

On a timeout, exception, or invalid action, PID 1 exits and the host forcibly
removes the container. Descendants cannot survive container termination. A new
table requires a fresh reset. Worker stdout/stderr goes to `/dev/null`; only
the distinct supervisor can emit host protocol messages. Each request uses an
unpredictable nonce to reject stale or prequeued worker replies.

This is container isolation, not a claim that Docker is a hardware security
boundary. For public adversarial tournaments run the Docker worker on a
dedicated patched host/VM, separate from application credentials and database.
Do not expose the Docker daemon, use privileged mode, or add host mounts.
