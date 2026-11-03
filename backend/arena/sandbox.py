"""Docker-only submitted bot executor. No submitted Python executes on the host."""
from __future__ import annotations

import json
import base64
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import time
import uuid

IMAGE = "campus-arena-bot:local"
MODEL_IMAGE = "campus-arena-model:local"
MAX_SOURCE_BYTES = 102_400
MAX_OBSERVATION_BYTES = 60_000
MAX_REPLY_BYTES = 20_000

_BLUFF_CARD = re.compile(r"^[A23456789TJQK][cdhs]$")


def reply_validator_for(protocol: str):
    """Strict allow-lists for the action vocabularies of registered games."""
    if protocol == "poker":
        def validate(result):
            return type(result) is dict and result.get("action") in ("fold", "check", "call", "raise")
        return validate
    if protocol == "bluff":
        def validate(result):
            if type(result) is not dict:
                return False
            kind = result.get("type")
            if kind in ("challenge", "pass"):
                return True
            if kind == "play":
                cards = result.get("cards")
                return (type(cards) is list and 1 <= len(cards) <= 4 and
                        all(type(card) is str and _BLUFF_CARD.fullmatch(card) for card in cards))
            return False
        return validate
    raise ValueError(f"Unknown sandbox protocol '{protocol}'")


class BotError(RuntimeError):
    """A submitted agent failed, timed out, or the sandbox is unavailable."""


class SandboxDown(BotError):
    """The Docker sandbox itself is unavailable; not the bot's fault.

    Raised for daemon, spawn, and startup-transport failures so the engine can
    abort a doomed table instead of scoring a round full of meaningless folds.
    Bot-caused failures (timeouts, invalid actions, crashes) stay BotError.
    """


def docker_command() -> list[str]:
    command = ["docker"]
    context = os.environ.get("ARENA_DOCKER_CONTEXT", "").strip()
    if context:
        command.extend(["--context", context])
    return command


_status_cache: tuple[float, dict] | None = None


def sandbox_status() -> dict:
    global _status_cache
    if _status_cache and time.monotonic() - _status_cache[0] < 15:
        return dict(_status_cache[1])
    result = _sandbox_status_uncached()
    _status_cache = (time.monotonic(), result)
    return dict(result)


def _sandbox_status_uncached() -> dict:
    if not shutil.which("docker"):
        return {"available": False, "image": False, "error": "Docker CLI is not installed"}
    try:
        available = subprocess.run(
            docker_command() + ["info", "--format", "{{.ServerVersion}}"],
            capture_output=True, timeout=3, check=False,
        ).returncode == 0
        image = available and subprocess.run(
            docker_command() + ["image", "inspect", IMAGE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False,
        ).returncode == 0
        error = None if image else ("Sandbox image is not built" if available else "Docker is unavailable")
        return {"available": available, "image": bool(image), "error": error, "image_id": image_id()}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "image": False, "error": "Docker health check timed out or failed"}


def image_id(image: str = IMAGE) -> str | None:
    """Immutable local image id (sha256:...), so rounds can pin their runtime."""
    if not shutil.which("docker"):
        return None
    try:
        result = subprocess.run(
            docker_command() + ["image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    image_id_value = (result.stdout or "").strip()
    return image_id_value if result.returncode == 0 and image_id_value else None


class ContainerBot:
    """Fresh container/Agent per reset; strict trusted per-decision wall deadline.

    1 ms is measured *inside* the container, including OS scheduling and worker
    serialization. Busy machines may therefore fault even a fast bot. Docker
    startup has a separate 15 s transport allowance; Agent init is limited to
    2 s in-container. No automatic host fallback exists.
    """

    def __init__(self, source_path: Path, name: str, decision_ms: float = 1.0, image: str | None = None,
                 protocol: str = "poker"):
        self.source_path = Path(source_path)
        self.name = name
        if not math.isfinite(decision_ms) or not 0 < decision_ms <= 1000:
            raise ValueError("decision_ms must be in (0, 1000]")
        self.decision_ms = float(decision_ms)
        self.image_ref = image or IMAGE
        self.protocol = protocol
        self._validate_reply = reply_validator_for(protocol)
        self.last_elapsed_ms: float | None = None
        self._process: subprocess.Popen | None = None
        self._container: str | None = None
        self._buffer = bytearray()

    def _read(self, timeout: float) -> dict:
        process = self._process
        if process is None or process.stdout is None:
            raise BotError("Bot is not running; reset it before use")
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while b"\n" not in self._buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise BotError("Sandbox transport timed out")
                part = os.read(process.stdout.fileno(), 4096)
                if not part:
                    raise BotError("Sandbox exited; confirm Docker and the local sandbox image are available")
                self._buffer.extend(part)
                if len(self._buffer) > MAX_REPLY_BYTES:
                    raise BotError("Sandbox response exceeds protocol limit")
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = bytearray(rest)
        try:
            result = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise BotError("Invalid sandbox response") from exc
        if type(result) is not dict or result.get("ok") is not True:
            message = result.get("error", "Sandbox rejected bot") if type(result) is dict else "Invalid response"
            raise BotError(str(message)[:300])
        return result

    def _write(self, value: dict) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise BotError("Bot is not running; reset it before use")
        data = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        # Bounded nonblocking writes: a dead supervisor cannot hang an API job.
        deadline = time.monotonic() + 1.0
        view = memoryview(data)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise BotError("Sandbox input transport timed out")
                try:
                    written = os.write(process.stdin.fileno(), view)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    raise BotError("Sandbox input closed") from exc
                view = view[written:]

    def reset(self) -> None:
        self.close()
        try:
            config = self._initial_config()
        except (OSError, UnicodeError) as exc:
            raise BotError("Unable to read UTF-8 bot source") from exc
        self._container = f"arena-bot-{uuid.uuid4().hex}"
        command = docker_command() + [
            "run", "--rm", "-i", "--pull=never", "--name", self._container,
            "--network=none", "--read-only", "--cap-drop=ALL",
            "--cap-add=SETUID", "--cap-add=SETGID",
            "--security-opt=no-new-privileges", f"--memory={self.memory_mb}m", f"--memory-swap={self.memory_mb}m",
            "--pids-limit=32", "--cpus=1", "--ulimit=nofile=1024:1024",
            "--ulimit=core=0:0", "--user=0:0", "--ipc=none",
            f"--tmpfs=/tmp:rw,noexec,nosuid,nodev,size={self.tmpfs_mb}m,mode=1777",
            "--log-driver=none", self.image_ref,
        ]
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
            )
            os.set_blocking(self._process.stdin.fileno(), False)
            # Wait for Docker to start before the potentially >pipe-size source
            # is written: config write has a startup-specific transport budget.
            self._write_initial(config)
            try:
                ready = self._read(15)
            except BotError as exc:
                # Supervisor-rejected bots report ok:false lines (bot fault).
                # Process-level death or a stalled daemon leaves transport
                # silence, which is infrastructure and may abort a scored table.
                if "Sandbox exited" in str(exc) or "transport timed out" in str(exc):
                    raise SandboxDown(str(exc)) from exc
                raise
            if ready.get("ready") is not True:
                raise BotError("Sandbox did not initialize")
            self.last_elapsed_ms = None
        except (OSError, BotError, ValueError) as exc:
            self.close()
            if isinstance(exc, BotError):
                raise
            raise SandboxDown("Unable to start Docker sandbox") from exc

    def _initial_config(self):
        with self.source_path.open('rb') as source_file:
            raw = source_file.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise BotError('Bot source exceeds 100 KiB')
        return {'source': raw.decode('utf-8'), 'decision_ms': self.decision_ms,
                'protocol': self.protocol}

    memory_mb = 128
    tmpfs_mb = 16

    def _write_initial(self, value: dict) -> None:
        # Source is at most 100 KiB. Use the same bounded transport with a larger
        # startup budget without ever executing/importing the source here.
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        process = self._process
        deadline = time.monotonic() + 15
        view = memoryview(data)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise SandboxDown("Sandbox startup transport timed out")
                try:
                    view = view[os.write(process.stdin.fileno(), view):]
                except BlockingIOError:
                    continue

    def act(self, observation: dict) -> dict:
        if type(observation) is not dict:
            raise BotError("Observation must be an object")
        try:
            if len(json.dumps(observation, allow_nan=False).encode()) > MAX_OBSERVATION_BYTES:
                raise BotError("Observation exceeds 60 KB")
            self._write({"command": "act", "observation": observation})
            reply = self._read(1.0)
            result = reply.get("result")
            if not self._validate_reply(result):
                raise BotError("Invalid action from sandbox")
            self.last_elapsed_ms = reply.get("elapsed_ms")
            return result
        except (BotError, OSError, ValueError, TypeError) as exc:
            self.close()
            # A disappeared Docker daemon is infrastructure, not a bot fault.
            # A healthy daemon with a crashed/timed-out worker remains a bot fault.
            if isinstance(exc, BotError) and any(x in str(exc) for x in (
                'Sandbox exited', 'transport timed out', 'Sandbox input closed'
            )):
                status = _sandbox_status_uncached()
                if not status.get('available'):
                    raise SandboxDown('Docker became unavailable during a decision') from exc
            if isinstance(exc, BotError):
                raise
            raise BotError("Bot execution failed") from exc

    def close(self) -> None:
        process, container = self._process, self._container
        self._process = None
        self._container = None
        self._buffer.clear()
        if process is not None:
            if process.stdin:
                process.stdin.close()
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            if process.stdout:
                process.stdout.close()
        if container:
            try:
                subprocess.run(
                    docker_command() + ["rm", "-f", container],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass

    def __enter__(self):
        self.reset()
        return self

    def __exit__(self, *_):
        self.close()


class ModelContainerBot(ContainerBot):
    """A small, bounded multi-file project, streamed into the isolated runtime."""
    memory_mb = 512
    tmpfs_mb = 48

    def __init__(self, source_path: Path, name: str, decision_ms: float = 50.0, image: str | None = None,
                 protocol: str = "poker"):
        super().__init__(source_path, name, decision_ms, image or MODEL_IMAGE, protocol)

    def _initial_config(self):
        with self.source_path.open('rb') as project_file:
            raw = project_file.read(16_777_217)
        if len(raw) > 16_777_216:
            raise BotError('Model project exceeds 16 MiB')
        return {'project_zip': base64.b64encode(raw).decode('ascii'), 'decision_ms': self.decision_ms,
                'protocol': self.protocol}
