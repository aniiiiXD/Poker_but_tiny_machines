import json

import pytest
from fastapi.testclient import TestClient

from arena import db, worker
from arena.app import app

SOURCE = 'class Agent:\n    def act(self, observation):\n        return {"action": "check"}\n'

TMP = {'data': None}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('ARENA_TESTING', '1')
    monkeypatch.setattr(db, 'DATA', tmp_path)
    TMP['data'] = tmp_path
    db.initialize()
    return [TestClient(app) for _ in range(4)]


def register(client, name):
    response = client.post('/api/auth/register', json={'name': name, 'email': name.lower() + '@example.edu', 'password': 'password123', 'college': 'University'})
    # The local pilot gates submissions on a verified email; tests verify via
    # the outbox token immediately after registering.
    for f in sorted((TMP['data'] / 'outbox').glob('*.txt')):
        for line in f.read_text().splitlines():
            if '/verify?token=' in line:
                client.post('/api/auth/verify', json={'token': line.split('token=')[1]})
    return response


def team(client, name):
    response = client.post('/api/team', json={'name': name})
    assert response.status_code == 201, response.text
    return response.json()


def test_accounts_team_limit_and_private_data(clients):
    owner, partner, outsider, extra = clients
    for client, name in zip(clients, ['Owner', 'Partner', 'Outsider', 'Extra']):
        assert register(client, name).status_code == 201
    assert register(TestClient(app), 'Owner').status_code == 409
    group = team(owner, 'Study team')
    assert partner.post('/api/team/join', json={'code': group['join_code']}).status_code == 200
    assert extra.post('/api/team/join', json={'code': group['join_code']}).status_code == 409
    team(outsider, 'Other team')
    sub = owner.post('/api/submissions', json={'name': 'First', 'source': SOURCE})
    assert sub.status_code == 201, sub.text
    sid = sub.json()['id']
    assert len(partner.get('/api/submissions').json()['submissions']) == 1
    assert outsider.get('/api/submissions').json()['submissions'] == []
    assert outsider.post('/api/practice', json={'submission_id': sid}).status_code == 404
    job = owner.post('/api/practice', json={'hands': 1}).json()['job_id']
    assert partner.get('/api/jobs/' + job).status_code == 200
    assert outsider.get('/api/jobs/' + job).status_code == 404
    assert TestClient(app).get('/api/jobs/' + job).status_code == 404
    result = {'hands': 1, 'frames': [{'secret': 'test'}]}
    replay = worker.save_replay('private', result, 'practice', owner.get('/api/me').json()['user']['id'], group['id'])
    assert partner.get('/api/replays/' + replay).status_code == 200
    assert outsider.get('/api/replays/' + replay).status_code == 404
    assert TestClient(app).get('/api/replays/' + replay).status_code == 404
    assert not outsider.get('/api/replays').json()['replays']


def test_submission_validation_cooldown_and_no_execution(clients, tmp_path, monkeypatch):
    c = clients[0]
    assert register(c, 'Author').status_code == 201
    team(c, 'Authors')
    marker = tmp_path / 'executed'
    malicious = f"open({str(marker)!r}, 'w').write('bad')\n" + SOURCE
    assert c.post('/api/submissions', json={'name': 'Broken', 'source': 'class Agent: ???'}).status_code == 422
    first = c.post('/api/submissions', json={'name': 'First', 'source': malicious})
    assert first.status_code == 201 and not marker.exists()
    assert c.post('/api/submissions', json={'name': 'Second', 'source': SOURCE}).status_code == 429
    monkeypatch.setattr('arena.app.COOLDOWN', 0)
    second = c.post('/api/submissions', json={'name': 'Second', 'source': SOURCE})
    assert second.status_code == 201
    rows = c.get('/api/submissions').json()['submissions']
    assert {row['id'] for row in rows if row['active']} == {second.json()['id']}
    assert first.json()['source'] == malicious and not marker.exists()


def test_sponsor_and_admin_authorization(clients):
    c = clients[0]
    assert register(c, 'Student').status_code == 201
    assert c.get('/api/admin/inquiries').status_code == 403
    assert c.post('/api/admin/events', json={'title':'Event', 'description':'A valid event description'}).status_code == 403
    inquiry = {'name':'Pat Smith','email':'pat@example.com','company':'Example Inc','message':'Interested in supporting student teams.'}
    assert c.post('/api/sponsor-inquiries', json=inquiry).status_code == 201
    with db.connect(True) as conn:
        conn.execute("UPDATE users SET role='admin' WHERE email='student@example.edu'")
    saved = c.get('/api/admin/inquiries').json()['inquiries']
    assert len(saved) == 1 and saved[0]['message'] == inquiry['message']
    event = c.post('/api/admin/events', json={'title':'Test event', 'description':'A valid event description', 'round_count':2, 'tables_per_round':2, 'max_hands':3})
    assert event.status_code == 201
    assert c.get('/api/events/' + event.json()['id']).json()['event']['round_count'] == 2


def test_request_boundaries_and_normal_body(clients):
    c = clients[0]
    bad_origin = c.post('/api/auth/register', headers={'Origin': 'https://untrusted.example'}, json={'name':'No', 'email':'no@example.edu', 'password':'password123', 'college':'University'})
    assert bad_origin.status_code == 403
    too_large = c.post('/api/auth/register', content=b'x' * 130001, headers={'Content-Type': 'application/json'})
    assert too_large.status_code == 413
    valid = c.post('/api/auth/register', headers={'Origin': 'http://localhost:5173'}, json={'name':'Boundary', 'email':'boundary@example.edu', 'password':'password123', 'college':'University'})
    assert valid.status_code == 201
    assert c.get('/api/me').json()['user']['email'] == 'boundary@example.edu'


def test_exhibition_seeding_is_atomic_and_idempotent(clients, monkeypatch):
    def failure(*args, **kwargs):
        raise RuntimeError('simulation failed')
    monkeypatch.setattr(worker, 'play_table', failure)
    with pytest.raises(RuntimeError):
        worker.seed_exhibition()
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM events WHERE id='baseline-exhibition'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM rounds WHERE event_id='baseline-exhibition'").fetchone()[0] == 0
    def sample(*args, **kwargs):
        return {'points': [1]*8, 'faults': [0]*8, 'chips': [2000]*8, 'frames': [{'hand': 1}], 'hands': 1}
    monkeypatch.setattr(worker, 'play_table', sample)
    worker.seed_exhibition()
    worker.seed_exhibition()
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM events WHERE id='baseline-exhibition'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM rounds WHERE event_id='baseline-exhibition'").fetchone()[0] == 6
        assert c.execute("SELECT COUNT(*) FROM round_scores WHERE round_id LIKE 'exhibition-%'").fetchone()[0] == 48
        assert c.execute("SELECT COUNT(*) FROM replays WHERE source='exhibition'").fetchone()[0] == 1


def test_submission_cadence_is_visible(clients):
    c = clients[0]
    assert register(c, 'Cadence').status_code == 201
    team(c, 'Cadence team')
    assert c.get('/api/submissions').json()['cooldown_remaining'] == 0
    assert c.post('/api/submissions', json={'name': 'One', 'source': SOURCE}).status_code == 201
    blocked = c.post('/api/submissions', json={'name': 'Two', 'source': SOURCE})
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers['Retry-After']) <= 300
    remaining = c.get('/api/submissions').json()['cooldown_remaining']
    assert 1 <= remaining <= 300


def test_starter_kit_zip_ships_simulator_and_icm(clients):
    import io
    import zipfile
    bundle = zipfile.ZipFile(io.BytesIO(clients[0].get('/api/starter/download').content))
    assert {'agent.py', 'simulate.py', 'icm.py', 'README.md'} <= set(bundle.namelist())


def test_hand_logs_and_score_chain_admin_api(clients, monkeypatch):
    c = clients[0]
    import time as _time
    from arena import worker as _worker
    register(c, 'Organizer')
    with db.connect(True) as conn:
        conn.execute("UPDATE users SET role='admin' WHERE email='organizer@example.edu'")
        now = _time.time()
        conn.execute("INSERT INTO rounds VALUES(?,?,?,?,?,?,?)", ('r-log', 'e-log', 1, 'completed', now, now, 8))
        _worker.finish_job  # noqa - touch module
        conn.execute(
            "INSERT INTO hand_logs VALUES(?,?,?,?,?,?)",
            ('log-1', 'r-log', 0, 12345, now, json.dumps([{'hand': 1, 'actions': [{'seat': 0, 'action': 'raise', 'amount': 40, 'street': 'preflop'}]}])),
        )
        conn.execute("INSERT INTO round_scores VALUES(?,?,?,?,?,?,?,?)", ('r-log', 'team-x', 'Team X', 'U', 4.0, 0, 'bot-x', 0))
        import arena.db as _db
        _db.append_score_event(conn, 'round-score', 'r-log', 'team-x', {'score': 4.0})
    index = c.get('/api/admin/hand-logs', params={'round_id': 'r-log'}).json()
    assert len(index['logs']) == 1 and index['logs'][0]['seed'] == 12345
    detail = c.get('/api/admin/hand-logs/log-1').json()
    assert detail['log'][0]['actions'][0]['action'] == 'raise'
    chain = c.get('/api/admin/score-events', params={'round_id': 'r-log'}).json()
    assert chain['chain_valid'] is True and len(chain['events']) == 1
    fixed = c.post('/api/admin/scores/correct', json={'round_id': 'r-log', 'team_id': 'team-x', 'score': 5.0, 'reason': 'Scoring bug in round 1.'})
    assert fixed.json()['chain_valid'] is True
    after = c.get('/api/admin/score-events', params={'round_id': 'r-log'}).json()
    assert [e['kind'] for e in after['events']] == ['round-score', 'correction']
    from fastapi.testclient import TestClient as _TC
    outsider = _TC(app)
    outsider.post('/api/auth/register', json={'name': 'Peon', 'email': 'peon@example.edu', 'password': 'password123', 'college': 'University'})
    assert outsider.get('/api/admin/hand-logs').status_code == 403  # non-admin blocked


def test_unverified_users_cannot_submit(clients):
    c = clients[0]
    raw = client = c  # use a raw register, not the auto-verifying helper
    client.post('/api/auth/register', json={'name': 'Unverified', 'email': 'unverified@example.edu', 'password': 'password123', 'college': 'University'})
    team(c, 'Unverified team')
    blocked = c.post('/api/submissions', json={'name': 'Bot', 'source': SOURCE})
    assert blocked.status_code == 403
