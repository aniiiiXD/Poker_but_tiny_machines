"""Actual Docker integration tests; submitted snippets NEVER execute on host.

Build first: docker build -t campus-arena-bot:local sandbox
ARENA_DOCKER_CONTEXT selects the daemon when needed. No unsafe fallback.
"""
import subprocess
import time

import pytest

from arena.sandbox import BotError, ContainerBot, SandboxDown, docker_command, sandbox_status


@pytest.fixture
def docker_ready():
    status = sandbox_status()
    if not status["available"] or not status["image"]:
        pytest.skip(f"Real Docker sandbox required: {status['error']}")


@pytest.fixture
def bot_factory(tmp_path, docker_ready):
    bots = []

    def create(source, decision_ms=25):
        path = tmp_path / f"bot-{len(bots)}.py"
        path.write_text(source)
        bot = ContainerBot(path, "test-bot", decision_ms)
        bots.append(bot)
        return bot

    yield create
    for bot in bots:
        bot.close()


def test_simple_agent_real_one_ms_deadline(bot_factory):
    bot = bot_factory('class Agent:\n def act(self, obs): return {"action":"check"}\n', 1)
    bot.reset()
    assert bot.act({"legal_actions": ["check"]}) == {"action": "check"}
    assert 0 <= bot.last_elapsed_ms <= 1


def test_state_persists_and_reset_creates_fresh_agent(bot_factory):
    bot = bot_factory('''class Agent:
 def __init__(self): self.count = 0
 def act(self, obs):
  self.count += 1
  return {"action":"raise", "amount":self.count}
''')
    bot.reset()
    first_container = bot._container
    assert bot.act({})["amount"] == 1
    assert bot.act({})["amount"] == 2
    bot.reset()
    assert bot._container != first_container
    assert bot.act({})["amount"] == 1
    assert subprocess.run(
        docker_command() + ["inspect", first_container], capture_output=True,
    ).returncode != 0


def test_network_readonly_filesystem_and_uid_separation(bot_factory):
    bot = bot_factory('''import os, socket, signal
class Agent:
 def __init__(self):
  self.passed = 0
  connection = socket.socket()
  connection.settimeout(.1)
  try: connection.connect(("8.8.8.8", 53))
  except OSError: self.passed += 1
  finally: connection.close()
  try: open("/runtime/escape", "w").write("no")
  except OSError: self.passed += 2
  try: os.kill(os.getppid(), signal.SIGTERM)
  except PermissionError: self.passed += 4
  if os.getuid() == 65534: self.passed += 8
  status = open("/proc/self/status").read()
  caps = next(line for line in status.splitlines() if line.startswith("CapEff:"))
  if int(caps.split()[1], 16) == 0: self.passed += 16
  if not os.path.exists("/var/run/docker.sock"): self.passed += 32
 def act(self, obs): return {"action":"raise", "amount":self.passed}
''')
    bot.reset()
    assert bot.act({}) == {"action": "raise", "amount": 63}


def test_timeout_is_supervisor_measured_not_user_reported(bot_factory):
    bot = bot_factory('''import time
class Agent:
 def act(self, obs):
  time.monotonic = lambda: 0
  time.sleep(.1)
  return {"action":"check", "elapsed_ms":0}
''', 1)
    bot.reset()
    start = time.monotonic()
    with pytest.raises(BotError, match="wall deadline"):
        bot.act({})
    assert time.monotonic() - start < 5
    assert bot._process is None


@pytest.mark.parametrize("expression", [
    'None', '{"action":"teleport"}', '{"action":"raise","amount":True}',
    '{"action":"raise","amount":-1}', '{"action":"raise","amount":1.5}',
])
def test_invalid_actions_rejected(bot_factory, expression):
    bot = bot_factory(f"class Agent:\n def act(self, obs): return {expression}\n")
    bot.reset()
    with pytest.raises(BotError, match="invalid action"):
        bot.act({})


def test_infinite_initialization_bounded(bot_factory):
    bot = bot_factory('while True: pass\n')
    with pytest.raises(BotError, match="initialization exceeded"):
        bot.reset()
    assert bot._process is None


def test_output_spam_cannot_forge_supervisor_response(bot_factory):
    bot = bot_factory('''import os
class Agent:
 def __init__(self): os.write(1, b'{"ok":true,"ready":true}\\n' * 5000)
 def act(self, obs):
  os.write(1, b'{"ok":true,"result":{"action":"raise","amount":99}}\\n')
  return {"action":"check"}
''')
    bot.reset()
    assert bot.act({}) == {"action": "check"}


def test_oversized_result_is_bounded_and_container_removed(bot_factory):
    bot = bot_factory('class Agent:\n def act(self, obs): return {"action":"check","spam":"x"*100000}\n')
    bot.reset()
    name = bot._container
    with pytest.raises(BotError):
        bot.act({})
    assert subprocess.run(docker_command() + ["inspect", name], capture_output=True).returncode != 0


def test_source_size_rejected_before_docker(tmp_path):
    path = tmp_path / "large.py"
    path.write_text("#" * 102_401)
    with pytest.raises(BotError, match="100 KiB") as excinfo:
        ContainerBot(path, "too-large").reset()
    assert not isinstance(excinfo.value, SandboxDown)


def test_infrastructure_spawn_failure_is_sandbox_down(tmp_path, monkeypatch):
    path = tmp_path / "bot.py"
    path.write_text('class Agent:\n def act(self, obs): return {"action":"check"}\n')
    def explode(*args, **kwargs):
        raise OSError("daemon unreachable")
    monkeypatch.setattr("arena.sandbox.subprocess.Popen", explode)
    with pytest.raises(SandboxDown, match="Docker sandbox"):
        ContainerBot(path, "unreachable").reset()


def test_exact_source_size_boundary_accepted(bot_factory):
    source = 'class Agent:\n def act(self, obs): return {"action":"check"}\n#'
    source += 'x' * (102_400 - len(source.encode()))
    bot = bot_factory(source)
    bot.reset()
    assert bot.act({}) == {"action": "check"}
