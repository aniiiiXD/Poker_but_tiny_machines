"""Trusted container PID 1. Never import submitted code in this process.

The worker has a different UID, no capabilities, no host mounts or network.
Only this supervisor measures decision time. Exiting PID 1 kills the entire
container's process namespace, including descendants of a hostile worker.
"""
import json
import base64
import io
import math
import os
import resource
import select
import socket
import stat
import sys
import time
import zipfile
from pathlib import PurePosixPath

MAX_SOURCE = 102_400
MAX_INIT = 24_000_000
MAX_REQUEST = 65_536
MAX_RESPONSE = 16_384


def emit(value):
    data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    os.write(1, data)


def fatal(message):
    try:
        emit({"ok": False, "error": message})
    finally:
        os._exit(1)


def line_from_stdin(limit):
    data = sys.stdin.buffer.readline(limit + 1)
    if not data:
        os._exit(0)
    if len(data) > limit or not data.endswith(b"\n"):
        fatal("Request exceeds protocol limit")
    return json.loads(data)


def drop_identity(uid):
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def worker(channel, source, project_dir=None):
    # All submitted code, including module-level code and Agent.__init__, runs
    # only after the privilege drop. Discard stdout/stderr before execution.
    drop_identity(65534)
    null = os.open("/dev/null", os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    keep = channel.fileno()
    # No inherited Docker stdin/stdout descriptors or supervisor socket end.
    for fd in range(3, 1024):
        if fd != keep:
            try:
                os.close(fd)
            except OSError:
                pass
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1_048_576, 1_048_576))
    try:
        filename = '<submitted_bot>'
        if project_dir:
            sys.path.insert(0, project_dir)
            filename = project_dir + '/agent.py'
        scope = {"__name__": "submitted_bot", "__file__": filename}
        exec(compile(source, filename, "exec"), scope)
        agent = scope["Agent"]()
        if not callable(getattr(agent, "act", None)):
            raise ValueError("Agent.act missing")
        channel.sendall(b'{"ready":true}\n')
        stream = channel.makefile("rb")
        while True:
            raw = stream.readline(MAX_REQUEST + 1)
            if not raw or len(raw) > MAX_REQUEST:
                os._exit(1)
            request = json.loads(raw)
            result = agent.act(request["observation"])
            response = json.dumps(
                {"nonce": request["nonce"], "result": result},
                allow_nan=False, separators=(",", ":"),
            ).encode() + b"\n"
            if len(response) > MAX_RESPONSE:
                os._exit(1)
            channel.sendall(response)
    except BaseException:
        # Never stringify an exception or execute submitted __repr__ in PID1.
        os._exit(1)


def receive(channel, deadline):
    data = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        readable, _, _ = select.select([channel], [], [], remaining)
        if not readable:
            raise TimeoutError
        part = channel.recv(min(4096, MAX_RESPONSE + 1 - len(data)))
        if not part:
            raise ValueError("worker exited")
        data.extend(part)
        if len(data) > MAX_RESPONSE:
            raise ValueError("oversized result")
        if b"\n" in data:
            # One response per request, never accept precomputed queued replies.
            if data.count(b"\n") != 1 or data[-1] != 10:
                raise ValueError("invalid framing")
            return bytes(data)


def valid_action(result, protocol="poker"):
    if type(result) is not dict:
        return False
    if protocol == "uno":
        kind = result.get("type")
        if kind in ("draw", "pass", "uno", "challenge"):
            return True
        return kind == "play" and type(result.get("card")) is str and 0 < len(result["card"]) <= 8
    if protocol == "hearts":
        kind = result.get("type")
        if kind == "play":
            card = result.get("card")
            return type(card) is str and len(card) == 2 and card[0] in "cdhs"
        if kind == "pass":
            cards = result.get("cards")
            return (type(cards) is list and len(cards) == 3 and
                    all(type(c) is str and len(c) == 2 and c[0] in "cdhs" and c[1] in "cdhs" for c in cards))
        return False
    if protocol == "rummy":
        kind = result.get("type")
        if kind == "draw":
            return result.get("from") in ("stock", "discard")
        if kind == "discard":
            card = result.get("card")
            return type(card) is str and 0 < len(card) <= 4
        if kind == "declare":
            hand = result.get("hand")
            return (type(hand) is list and 0 < len(hand) <= 32 and
                    all(type(c) is str and 0 < len(c) <= 4 for c in hand))
        return kind == "pass"
    if protocol == "hexchange":
        return (type(result) is dict and
                result.get("type") in ("build_road", "build_settlement", "build_city",
                                       "buy_dev", "play_dev", "bank_trade", "offer",
                                       "accept", "reject", "counter", "move_robber",
                                       "setup_settlement", "setup_road", "end_turn", "pass"))
    if protocol == "bluff":
        kind = result.get("type")
        if kind in ("challenge", "pass"):
            return True
        if kind == "play":
            cards = result.get("cards")
            return (type(cards) is list and 1 <= len(cards) <= 4 and
                    all(type(card) is str and len(card) == 2 and
                        card[0] in "A23456789TJQK" and card[1] in "cdhs" for card in cards))
        return False
    action = result.get("action")
    if action not in ("fold", "check", "call", "raise"):
        return False
    if action == "raise":
        amount = result.get("amount")
        return type(amount) is int and 0 <= amount <= 2**53 - 1
    return True


def clean_result(result, protocol="poker"):
    """Rebuild the reply from allow-listed fields only."""
    if protocol == "uno":
        kind = result["type"]
        return {"type": kind, "card": result["card"]} if kind == "play" else {"type": kind}
    if protocol == "hearts":
        kind = result["type"]
        if kind == "play":
            return {"type": "play", "card": result["card"]}
        return {"type": "pass", "cards": list(result["cards"])}
    if protocol == "rummy":
        kind = result["type"]
        if kind == "draw":
            return {"type": "draw", "from": result["from"]}
        if kind == "discard":
            return {"type": "discard", "card": result["card"]}
        if kind == "declare":
            return {"type": "declare", "hand": list(result["hand"])}
        return {"type": "pass"}
    if protocol == "hexchange":
        # Engine deep-validates; keep the bounded dict as-is (MAX_RESPONSE caps size).
        return dict(result)
    if protocol == "bluff":
        kind = result["type"]
        if kind == "play":
            return {"type": "play", "cards": list(result["cards"])}
        return {"type": kind}
    clean = {"action": result["action"]}
    if clean["action"] == "raise":
        clean["amount"] = result["amount"]
    return clean


def prepare_project(encoded):
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 16_777_216:
        raise ValueError('Project archive exceeds 16 MiB')
    target = '/tmp/arena-project'
    os.mkdir(target, 0o755)
    total, seen = 0, set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > 100:
            raise ValueError('Project has too many files')
        for item in infos:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (item.flag_bits & 1 or path.is_absolute() or not path.parts or
                any(part in ('..', '.') for part in path.parts) or '\\' in item.filename or
                stat.S_ISLNK(mode) or item.filename in seen):
                raise ValueError('Unsafe project path')
            seen.add(item.filename)
            total += item.file_size
            if total > 16_777_216:
                raise ValueError('Project expands beyond 16 MiB')
            dest = os.path.join(target, *path.parts)
            if item.is_dir():
                os.makedirs(dest, mode=0o755, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dest), mode=0o755, exist_ok=True)
            data = archive.read(item)
            if len(data) != item.file_size:
                raise ValueError('Invalid project file')
            with open(dest, 'xb') as f:
                f.write(data)
            os.chmod(dest, 0o644)
    with open(target + '/agent.py', encoding='utf-8') as f:
        source = f.read(MAX_SOURCE + 1)
    if len(source.encode()) > MAX_SOURCE:
        raise ValueError('agent.py exceeds source limit')
    return source, target


def main():
    config = line_from_stdin(MAX_INIT)
    source = config.get("source")
    project_dir = None
    if 'project_zip' in config:
        try:
            source, project_dir = prepare_project(config['project_zip'])
        except (ValueError, OSError, UnicodeError, zipfile.BadZipFile):
            fatal('Invalid model project archive')
    protocol = config.get("protocol", "poker")
    if protocol not in ("poker", "bluff", "uno", "hearts", "rummy", "hexchange"):
        fatal("Unsupported protocol")
    milliseconds = config.get("decision_ms")
    if not isinstance(source, str) or len(source.encode()) > MAX_SOURCE:
        fatal("Invalid source size")
    if type(milliseconds) not in (int, float) or not math.isfinite(milliseconds):
        fatal("Invalid deadline")
    if not 0 < milliseconds <= 1000:
        fatal("Invalid deadline")
    parent, child = socket.socketpair()
    pid = os.fork()
    if pid == 0:
        parent.close()
        worker(child, source, project_dir)
        os._exit(1)
    child.close()
    drop_identity(1000)
    parent.setblocking(False)
    try:
        ready = json.loads(receive(parent, time.monotonic() + 2.0))
        if ready != {"ready": True}:
            fatal("Bot initialization failed")
    except TimeoutError:
        fatal("Bot initialization exceeded 2 seconds")
    except (ValueError, OSError):
        fatal("Bot initialization failed")
    emit({"ok": True, "ready": True})
    while True:
        request = line_from_stdin(MAX_REQUEST)
        if request.get("command") != "act" or type(request.get("observation")) is not dict:
            fatal("Invalid command")
        nonce = os.urandom(16).hex()
        packet = json.dumps(
            {"nonce": nonce, "observation": request["observation"]},
            allow_nan=False, separators=(",", ":"),
        ).encode() + b"\n"
        if len(packet) > MAX_REQUEST:
            fatal("Observation exceeds protocol limit")
        # Deadline includes worker scheduling, input parsing, Agent.act and
        # output serialization/socket delivery, but excludes Docker transport.
        start = time.monotonic()
        deadline = start + milliseconds / 1000
        try:
            parent.sendall(packet)
            raw = receive(parent, deadline)
            completed = time.monotonic()
            if completed > deadline:
                raise TimeoutError
            response = json.loads(raw)
            if response.get("nonce") != nonce or not valid_action(response.get("result"), protocol):
                fatal("Bot returned an invalid action")
            result = response["result"]
            clean = clean_result(result, protocol)
            emit({"ok": True, "result": clean, "elapsed_ms": (completed - start) * 1000})
        except TimeoutError:
            fatal(f"Decision exceeded {milliseconds:g} ms wall deadline")
        except (ValueError, OSError, AttributeError, TypeError):
            fatal("Bot failed or returned invalid protocol data")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        fatal("Sandbox supervisor stopped")
