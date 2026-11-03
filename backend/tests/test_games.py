"""Multi-game foundation + Bluff vertical slice: API, activation, rounds."""
import json
import time
import zipfile
import io

import pytest
from fastapi.testclient import TestClient

from arena import db, worker
from arena.app import app, leaderboard


BLUFF_SOURCE = (db.DATA.parent / "starter-bluff" / "agent.py").read_text()
POKER_SOURCE = (db.DATA.parent / "starter-kit" / "agent.py").read_text()


TMP = {"data": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_TESTING", "1")
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr("arena.app.COOLDOWN", 0)
    TMP["data"] = tmp_path
    db.initialize()
    return TestClient(app)


def make_team(client, name="T1"):
    client.post("/api/auth/register", json={
        "name": name, "email": f"{name.lower()}@test.edu", "password": "password1",
        "college": "Test College"})
    # The pilot gates submissions on verified email; consume the outbox token.
    for path in sorted((TMP["data"] / "outbox").glob("*.txt")):
        for line in path.read_text().splitlines():
            if "/verify?token=" in line:
                client.post("/api/auth/verify", json={"token": line.split("token=")[1]})
    client.post("/api/team", json={"name": name})
    return client.get("/api/me").json()["user"]


def test_games_endpoint_lists_only_implemented_games(client):
    games = {g["id"]: g for g in client.get("/api/games").json()["games"]}
    assert set(games) == {"poker", "bluff"}
    assert games["bluff"]["rules_version"] == 1
    assert games["bluff"]["seats"] == [4]
    assert "classic" in games["bluff"]["tracks"] and "model" in games["bluff"]["tracks"]


def test_bluff_practice_baseline_demo_without_docker(client):
    make_team(client)
    job_id = client.post("/api/practice", json={"game": "bluff", "matches": 2}).json()["job_id"]
    with db.connect() as c:
        job = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    result = worker.practice(job)
    assert result["matches"] == 2 and result["hands"] == 2
    assert result["game"] == "bluff"
    assert len(result["scores"]) == 4
    assert all(0.0 <= s["points"] <= 1.0 for s in result["scores"])
    assert result["scores"][0]["name"] == "Honest"  # baseline demo has no user bot first
    # Replay carries the versioned wrapper and no hidden cards.
    detail = client.get(f"/api/replays/{result['replay_id']}").json()
    assert "log" not in detail["summary"]
    assert detail["game"] == "bluff"
    assert detail["frames"]["game"] == "bluff" and detail["frames"]["protocol"] == 1
    assert set(detail["frames"]["names"]) == {"Honest", "Random", "Counter", "Liar"}
    for frame in detail["frames"]["frames"]:
        assert "hand" not in frame and "cards" not in frame
        if frame.get("revealed") is not None:
            assert frame.get("challenged_by") is not None


def test_legacy_bluff_replay_summary_is_filtered_for_anonymous_users(client):
    from arena.games.bluff.baselines import make_bluff_baselines
    from arena.games.bluff.engine import play_bluff_match

    result = play_bluff_match(make_bluff_baselines(4), seed=7, decision_cap=4, capture=True)
    replay_id = worker.save_replay('Legacy', result, 'tournament', game_id='bluff')
    # Simulate a replay saved by the old code, which persisted private log data.
    with db.connect(True) as c:
        c.execute('UPDATE replays SET summary=? WHERE id=?',
                  (json.dumps({**result, 'private_seed': 7}), replay_id))
    response = TestClient(app).get('/api/replays/' + replay_id)
    assert response.status_code == 200
    detail = response.json()
    assert 'log' not in detail['summary'] and 'private_seed' not in detail['summary']
    assert 'hands' not in detail['summary'] or isinstance(detail['summary']['hands'], int)
    assert all('cards' not in frame for frame in detail['frames']['frames'])


def test_bluff_submission_activation_is_scoped_per_game(client):
    make_team(client)
    poker = client.post("/api/submissions", json={"name": "Poker bot", "source": POKER_SOURCE}).json()
    bluff = client.post("/api/submissions", json={"name": "Bluff bot", "source": BLUFF_SOURCE,
                                                  "game": "bluff"}).json()
    assert poker["game"] == "poker" and bluff["game"] == "bluff"
    assert poker["active"] is True and bluff["active"] is True
    listed = {s["name"]: s for s in client.get("/api/submissions").json()["submissions"]}
    assert listed["Poker bot"]["active"] and listed["Bluff bot"]["active"]
    # A new poker submission deactivates only the poker bot.
    client.post("/api/submissions", json={"name": "Poker bot 2", "source": POKER_SOURCE})
    listed = {s["name"]: s for s in client.get("/api/submissions").json()["submissions"]}
    assert listed["Poker bot"]["active"] is False
    assert listed["Poker bot 2"]["active"] is True
    assert listed["Bluff bot"]["active"] is True


def test_practice_rejects_cross_game_submission(client):
    make_team(client)
    client.post("/api/submissions", json={"name": "Poker bot", "source": POKER_SOURCE})
    response = client.post("/api/practice", json={"game": "bluff", "submission_id": "missing"})
    assert response.status_code == 404  # poker bot is not a valid bluff submission


def test_unknown_games_are_rejected_everywhere(client):
    make_team(client)
    assert client.post("/api/submissions", json={"name": "X", "source": POKER_SOURCE,
                                                 "game": "chess"}).status_code == 422
    assert client.post("/api/practice", json={"game": "chess"}).status_code == 422
    assert client.get("/api/starter", params={"game": "chess"}).status_code == 422
    assert client.get("/api/starter/download", params={"game": "chess"}).status_code == 422
    assert client.get("/api/leaderboard", params={"game": "chess"}).status_code == 422


def test_starter_per_game(client):
    bluff = client.get("/api/starter", params={"game": "bluff"}).json()
    assert bluff["game"] == "bluff" and "class Agent" in bluff["source"]
    assert "challenge" in bluff["guide"].lower()
    poker = client.get("/api/starter").json()  # legacy call defaults to poker
    assert "hole_cards" in poker["source"] or "poker" in poker["guide"].lower()
    download = client.get("/api/starter/download", params={"game": "bluff"})
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
        assert "agent.py" in bundle.namelist()


def test_leaderboard_keeps_games_scoped(client):
    now = time.time()
    with db.connect(True) as c:
        c.execute("""INSERT INTO events(id,title,description,status,variant,build_starts_at,
            build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
            decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('poker-ev', 'Poker', 'd', 'completed', 'NLHE', now, now, 1, 1, 1, 1, 1.0, None, 0, None, 'poker', 1))
        c.execute("""INSERT INTO events(id,title,description,status,variant,build_starts_at,
            build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
            decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('bluff-ev', 'Bluff', 'd', 'completed', 'Bluff v1', now, now, 1, 1, 1, 1, 1.0, None, 0, None, 'bluff', 1))
        for event in ('poker-ev', 'bluff-ev'):
            c.execute("INSERT INTO rounds VALUES(?,?,?,?,?,?,?)", (event + '-r1', event, 1, 'completed', now, now, 1))
            c.execute("""INSERT INTO round_scores(round_id,team_id,team_name,college,score,faults,
                submission_id,is_baseline) VALUES(?,?,?,?,?,?,?,?)""",
                (event + '-r1', 't1', 'Team 1', 'C', 1.0, 0, None, 0))
    default = {row["team_id"]: row for row in client.get("/api/leaderboard").json()["leaderboard"]}
    bluff = client.get("/api/leaderboard", params={"game": "bluff"}).json()["leaderboard"]
    # Poker event is weighted by round number; bluff event must not leak in.
    assert default["t1"]["total_score"] == pytest.approx(1.0)
    assert any(row["team_id"] == "t1" for row in bluff)


def test_bluff_round_freezes_the_game_specific_bot(client):
    make_team(client)
    client.post("/api/submissions", json={"name": "Poker bot", "source": POKER_SOURCE})
    client.post("/api/submissions", json={"name": "Bluff bot", "source": BLUFF_SOURCE, "game": "bluff"})
    now = time.time()
    with db.connect(True) as c:
        team_id = c.execute("SELECT team_id FROM users LIMIT 1").fetchone()[0]
        c.execute("""INSERT INTO events(id,title,description,status,variant,build_starts_at,
            build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
            decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('bluff-ev', 'Bluff open', 'Bluff event', 'building', 'Bluff v1', now - 10, now - 1,
             60, 1, 1, 1, 1.0, None, 0, None, 'bluff', 1))
        c.execute("INSERT INTO entries VALUES(?,?,?)", ('bluff-ev', team_id, now))
    job_id = worker.enqueue_round('bluff-ev', manual=True)
    with db.connect() as c:
        payload = json.loads(c.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()[0])
    assert payload["game_id"] == "bluff" and payload["rules_version"] == 1
    assert payload["seats"] == [4]
    assert [t["name"] for t in payload["teams"]] == ["T1"]
    assert payload["teams"][0]["submission_id"] != "missing"
    # The frozen submission is the bluff bot, not the poker one.
    with db.connect() as c:
        frozen = c.execute("SELECT name,game_id FROM submissions WHERE id=?",
                           (payload["teams"][0]["submission_id"],)).fetchone()
    assert frozen["game_id"] == "bluff"


class FakeSeatBot:
    """In-process stand-in for a sandboxed bluff bot (legal, passive play)."""

    def __init__(self, path, name, decision_ms, image=None, protocol=None):
        self.name, self.path, self.image, self.protocol = name, path, image, protocol

    def reset(self):
        pass

    def act(self, observation):
        if observation["turn"]["type"] == "play":
            return {"type": "play", "cards": [observation["hand"][0]]}
        return {"type": "pass"}

    def close(self):
        pass


@pytest.mark.parametrize('entrants', [4, 5, 8])
def test_full_and_partial_bluff_tables_score_each_entrant(client, monkeypatch, entrants):
    now = time.time()
    with db.connect(True) as c:
        c.execute("""INSERT INTO events(id,title,description,status,variant,build_starts_at,
            build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
            decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('ev', 'Bluff event', 'description', 'building', 'Bluff', now - 2, now - 1,
             60, 1, 1, 1, 1.0, None, 0, None, 'bluff', 1))
        for i in range(entrants):
            team = f'team-{i}'
            c.execute('INSERT INTO teams VALUES(?,?,?,?)', (team, team, f'code-{i}', now))
            c.execute('INSERT INTO users(id,name,email,password,college,team_id,created_at) VALUES(?,?,?,?,?,?,?)',
                      (f'u{i}', f'u{i}', f'{i}@example.org', 'x', 'College', team, now))
            c.execute('INSERT INTO entries VALUES(?,?,?)', ('ev', team, now))
            c.execute("""INSERT INTO submissions(id,team_id,name,source,sha256,created_at,status,
                         error,active,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (f's{i}', team, 'bot', 'source', 'sha', now, 'accepted', None, 1, 'bluff', 1))
    monkeypatch.setattr(worker, 'ContainerBot', FakeSeatBot)
    monkeypatch.setattr(worker, 'sandbox_status', lambda: {'available': True, 'image': True, 'error': None})
    job_id = worker.enqueue_round('ev', manual=True)
    with db.connect() as c:
        job = dict(c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
    result = worker.score_round(job)
    with db.connect() as c:
        scores = c.execute('SELECT team_id FROM round_scores WHERE round_id=?', (result['round_id'],)).fetchall()
        logs = c.execute('SELECT seating FROM hand_log_metadata').fetchall()
    assert len(scores) == entrants and len({r['team_id'] for r in scores}) == entrants
    assert sum(not seat['scoring'] for row in logs for seat in json.loads(row['seating'])) == (-entrants % 4)


def test_bluff_leaderboard_uses_match_weighted_mean(client):
    now = time.time()
    with db.connect(True) as c:
        c.execute("""INSERT INTO events(id,title,description,status,variant,build_starts_at,
            build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
            decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('ev', 'Bluff', 'description', 'completed', 'Bluff', now, now, 60, 2, 1, 1, 1, None, 0, None, 'bluff', 1))
        for number, score, matches in [(1, 1.0, 1), (2, 0.0, 3)]:
            round_id = f'r{number}'
            c.execute('INSERT INTO rounds VALUES(?,?,?,?,?,?,?)', (round_id, 'ev', number, 'completed', now, now, 1))
            c.execute('INSERT INTO round_scores VALUES(?,?,?,?,?,?,?,?)', (round_id, 'team', 'Team', 'C', score, 0, None, 0))
            c.execute('INSERT INTO round_metrics VALUES(?,?,?,?)', (round_id, 'team', matches, None))
    assert client.get('/api/events/ev').json()['leaderboard'][0]['total_score'] == 0.25
    assert client.get('/api/leaderboard?game=bluff').json()['leaderboard'][0]['total_score'] == 0.25


def test_newer_submissions_are_scoped_to_game_and_track(client):
    with db.connect(True) as c:
        c.execute("INSERT INTO jobs(id,kind,status,team_id,created_at,payload) VALUES(?,?,?,?,?,?)",
                  ('bluff-job', 'github_validation', 'queued', 't', 20,
                   json.dumps({'game_id': 'bluff', 'track': 'classic'})))
        assert not worker.has_newer_submission(c, 't', 10, 'poker', 'model')
        assert not worker.has_newer_submission(c, 't', 10, 'bluff', 'model')
        assert worker.has_newer_submission(c, 't', 10, 'bluff', 'classic')
        c.execute("INSERT INTO jobs(id,kind,status,team_id,created_at,payload) VALUES(?,?,?,?,?,?)",
                  ('model-job', 'model_validation', 'queued', 't', 21, json.dumps({'game_id': 'poker'})))
        assert worker.has_newer_submission(c, 't', 10, 'poker', 'model')
        assert not worker.has_newer_submission(c, 't', 10, 'poker', 'classic')


def test_bluff_round_scores_averages_and_labels_fillers(client, monkeypatch):
    make_team(client, name="Solo")
    # A second team in its own session so registrations do not swap cookies.
    duo = TestClient(app)
    duo.post("/api/auth/register", json={"name": "Duo", "email": "duo@test.edu",
                                         "password": "password1", "college": "Test College"})
    duo.post("/api/team", json={"name": "Duo"})
    client.post("/api/submissions", json={"name": "Bluff bot A", "source": BLUFF_SOURCE, "game": "bluff"})
    now = time.time()
    with db.connect(True) as c:
        team_id = c.execute("SELECT team_id FROM users WHERE name='Solo'").fetchone()[0]
        c.execute("""INSERT INTO events(id,title,description,status,variant,build_starts_at,
            build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
            decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('bluff-ev', 'Bluff open', 'Bluff event', 'building', 'Bluff v1', now - 10, now - 1,
             60, 1, 1, 1, 1.0, None, 0, None, 'bluff', 1))
        c.execute("INSERT INTO entries VALUES(?,?,?)", ('bluff-ev', team_id, now))
        duo_team = c.execute("SELECT team_id FROM users WHERE name='Duo'").fetchone()[0]
        c.execute("INSERT INTO entries VALUES(?,?,?)", ('bluff-ev', duo_team, now))
        c.execute("INSERT INTO submissions(id,team_id,name,source,sha256,created_at,status,error,active,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,'bluff',1)",
                  ('duo-bot', duo_team, 'Bluff bot B', BLUFF_SOURCE, 'sha', now, 'accepted', None, 1))

    monkeypatch.setattr(worker, "ContainerBot", FakeSeatBot)
    monkeypatch.setattr(worker, "sandbox_status", lambda: {"available": True, "image": True, "error": None})
    job_id = worker.enqueue_round('bluff-ev', manual=True)
    with db.connect() as c:
        job = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    result = worker.score_round(job)
    assert result["teams_scored"] == 2
    with db.connect() as c:
        scores = c.execute("SELECT team_id,score,faults FROM round_scores WHERE round_id=?",
                           (result["round_id"],)).fetchall()
        assert len(scores) == 2
        assert team_id in {row["team_id"] for row in scores}
        for row in scores:
            assert 0.0 <= row["score"] <= 1.0
        logs = c.execute("SELECT seed FROM hand_logs WHERE round_id=?", (result["round_id"],)).fetchall()
        assert logs and all(row["seed"] is not None for row in logs)
        seating = c.execute("""SELECT m.seating FROM hand_logs l JOIN hand_log_metadata m
            ON m.hand_log_id=l.id WHERE l.round_id=?""", (result["round_id"],)).fetchone()[0]
        seats = json.loads(seating)
        assert len(seats) == 4
        assert sum(1 for seat in seats if seat["scoring"]) == 2  # two entrants, two filler seats
        assert any(seat["team_id"] is None and not seat["scoring"] for seat in seats)
        replays = c.execute("SELECT game_id FROM replays WHERE source='tournament'").fetchall()
        assert replays and all(row["game_id"] == "bluff" for row in replays)
        payload = c.execute("""SELECT payload FROM score_events WHERE round_id=? LIMIT 1""",
                            (result["round_id"],)).fetchone()[0]
        assert json.loads(payload)["game_id"] == "bluff"


def test_bluff_smoke_requires_both_decision_types():
    from arena.games import get_game

    adapter = get_game("bluff").adapter

    class PlayOnly:
        name = "PlayOnly"

        def reset(self):
            pass

        def act(self, observation):
            return {"type": "play", "cards": [observation["hand"][0]]}

    with pytest.raises(ValueError, match="challenge"):
        adapter.smoke(PlayOnly())

    class Legal:
        name = "Legal"

        def reset(self):
            pass

        def act(self, observation):
            if observation["turn"]["type"] == "play":
                return {"type": "play", "cards": [observation["hand"][0]]}
            return {"type": "pass"}

    adapter.smoke(Legal())  # must not raise


def test_live_bluff_sandbox_validation(tmp_path, monkeypatch):
    """Real Docker: a bluff submission passes smoke (play + challenge) in the sandbox."""
    from arena.sandbox import sandbox_status

    if not sandbox_status()["image"]:
        pytest.skip("Build the local Docker sandbox image to run live bluff validation")
    monkeypatch.setenv("ARENA_TESTING", "1")
    monkeypatch.setattr(db, "DATA", tmp_path)
    db.initialize()
    from arena.games import get_game

    adapter = get_game("bluff").adapter
    path = tmp_path / "bluff-bot.py"
    path.write_text(BLUFF_SOURCE)
    from arena.sandbox import ContainerBot

    bot = ContainerBot(path, "Live bluff bot", decision_ms=1.0, protocol="bluff")
    try:
        adapter.smoke(bot)
        adapter.validation_match(bot)
    finally:
        bot.close()


@pytest.mark.parametrize('track', ['classic', 'model'])
def test_live_bluff_submission_practice_and_round(client, monkeypatch, track):
    from pathlib import Path
    from arena.games import get_game
    from arena.sandbox import MODEL_IMAGE, image_id, sandbox_status

    if not sandbox_status()['image'] or (track == 'model' and not image_id(MODEL_IMAGE)):
        pytest.skip('Required local sandbox image is unavailable')
    user = make_team(client)
    monkeypatch.setitem(get_game('bluff').adapter.decision_ms, 'classic', 50.0)
    if track == 'classic':
        submission = client.post('/api/submissions', json={
            'name': 'Bluff bot', 'source': BLUFF_SOURCE, 'game': 'bluff'}).json()
        submission_id = submission['id']
    else:
        project = io.BytesIO()
        starter = Path(__file__).resolve().parents[1] / 'starter-model-bluff'
        with zipfile.ZipFile(project, 'w') as archive:
            for filename in ('agent.py', 'weights.json'):
                archive.write(starter / filename, filename)
        response = client.post('/api/models/submissions?name=Bluff%20model&game=bluff',
                               content=project.getvalue(), headers={'Content-Type': 'application/zip'})
        assert response.status_code == 202, response.text
        item = response.json()
        worker._run_claimed(worker.claim_job())
        job_result = client.get('/api/jobs/' + item['job_id']).json()
        assert job_result['status'] == 'completed', job_result
        submission_id = item['submission_id']

    response = client.post('/api/practice', json={'game': 'bluff', 'submission_id': submission_id})
    assert response.status_code == 202, response.text
    with db.connect() as c:
        job = dict(c.execute('SELECT * FROM jobs WHERE id=?', (response.json()['job_id'],)).fetchone())
    result = worker.practice(job)
    assert result['scores'][0]['faults'] == 0, result['scores'][0]
    assert 'log' not in client.get('/api/replays/' + result['replay_id']).json()['summary']

    now = time.time()
    with db.connect(True) as c:
        c.execute("""INSERT INTO events(id,title,description,status,variant,build_starts_at,
            build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
            decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('live-ev', 'Bluff live', 'description', 'building', 'Bluff', now - 2, now - 1,
             60, 1, 1, 1, 50, None, 0, None, 'bluff', 1))
        c.execute('INSERT INTO event_tracks VALUES(?,?)', ('live-ev', track))
        c.execute('INSERT INTO entries VALUES(?,?,?)', ('live-ev', user['team_id'], now))
    job_id = worker.enqueue_round('live-ev', manual=True)
    with db.connect() as c:
        job = dict(c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
    scored = worker.score_round(job)
    with db.connect() as c:
        score = c.execute('SELECT * FROM round_scores WHERE round_id=?', (scored['round_id'],)).fetchone()
    assert score['submission_id'] == submission_id and score['faults'] == 0
