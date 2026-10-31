import hashlib
import hmac
import io
import json
import time
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from arena import db, github_integration, worker
from arena.app import app
from arena.model_projects import validate_archive
from arena.sandbox import ModelContainerBot, sandbox_status

SOURCE = '''from pathlib import Path\nimport json\nclass Agent:\n    def __init__(self):\n        self.model = json.loads(Path(__file__).with_name("weights.json").read_text())\n    def act(self, observation):\n        return {"action": "check" if "check" in observation["legal_actions"] else "fold"}\n'''


def archive(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, value in files.items():
            z.writestr(name, value)
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ARENA_TESTING', '1')
    monkeypatch.setenv('ARENA_GITHUB_CLIENT_ID', 'client')
    monkeypatch.setenv('ARENA_GITHUB_CLIENT_SECRET', 'secret')
    monkeypatch.setenv('ARENA_GITHUB_CALLBACK_URL', 'http://testserver/api/github/callback')
    monkeypatch.setenv('ARENA_GITHUB_WEBHOOK_SECRET', 'test-secret')
    monkeypatch.setattr(db, 'DATA', tmp_path)
    db.initialize()
    return TestClient(app)


def signup(client, email='one@example.com'):
    r = client.post('/api/auth/register', json={'name': 'User One', 'email': email,
                    'password': 'password123', 'college': 'University'})
    assert r.status_code == 201, r.text
    with db.connect(True) as c:
        c.execute('UPDATE users SET email_verified=1 WHERE email=?', (email,))
    r = client.post('/api/team', json={'name': email.split('@')[0] + ' team'})
    assert r.status_code == 201, r.text
    return r.json()['id']


def test_github_oauth_state_is_browser_bound_and_single_use(client, monkeypatch):
    def fake_request(url, **kwargs):
        if 'access_token' in url:
            return {'access_token': 'ephemeral'}
        if url.endswith('/user'):
            return {'id': 12, 'login': 'player', 'name': 'Player'}
        if url.endswith('/user/emails'):
            return [{'email': 'player@example.com', 'primary': True, 'verified': True}]
        raise AssertionError(url)
    monkeypatch.setattr(github_integration, 'request_json', fake_request)
    start = client.get('/api/github/login', follow_redirects=False)
    state = parse_qs(urlparse(start.headers['location']).query)['state'][0]
    stranger = TestClient(app)
    assert stranger.get('/api/github/callback', params={'code': 'abc', 'state': state}).status_code == 400
    response = client.get('/api/github/callback', params={'code': 'abc', 'state': state}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get('/api/me').json()['user']['email'] == 'player@example.com'
    assert client.get('/api/github/callback', params={'code': 'abc', 'state': state}).status_code == 400
    with db.connect() as c:
        assert c.execute('SELECT access_token FROM github_identities').fetchone()[0] == ''


def test_signed_webhook_is_deduplicated_and_team_private(client):
    team_id = signup(client)
    outsider = TestClient(app)
    with db.connect(True) as c:
        c.execute('INSERT INTO github_repositories(id,team_id,installation_id,repository_id,full_name,branch,created_at) VALUES(?,?,?,?,?,?,?)',
                  ('c1', team_id, 5, 7, 'owner/bot', 'arena', time.time()))
    body = json.dumps({'installation': {'id': 5}, 'repository': {'id': 7},
                       'ref': 'refs/heads/arena', 'after': 'a' * 40}).encode()
    headers = {'X-GitHub-Event': 'push', 'X-GitHub-Delivery': 'delivery1',
               'X-Hub-Signature-256': 'sha256=' + hmac.new(b'test-secret', body, hashlib.sha256).hexdigest(),
               'Content-Type': 'application/json'}
    assert outsider.post('/api/github/webhook', content=body, headers={**headers, 'X-Hub-Signature-256': 'bad'}).status_code == 401
    assert outsider.post('/api/github/webhook', content=body, headers=headers).json() == {'queued': 1}
    assert outsider.post('/api/github/webhook', content=body, headers=headers).json() == {'duplicate': True}
    job = client.get('/api/github/jobs').json()['jobs'][0]
    assert job['commit_sha'] == 'a' * 40
    assert outsider.get('/api/jobs/' + job['id']).status_code == 404


def test_model_archive_rejects_traversal_and_enforces_structure(client):
    valid = archive({'agent.py': SOURCE, 'weights.json': '{"x":1}'})
    assert 'class Agent' in validate_archive(valid)
    with pytest.raises(ValueError):
        validate_archive(archive({'agent.py': SOURCE, '../escape': 'bad'}))
    with pytest.raises(ValueError):
        validate_archive(archive({'weights.json': '{}'}))


def test_model_upload_queues_and_stays_private(client):
    signup(client)
    raw = archive({'agent.py': SOURCE, 'weights.json': '{"x":1}'})
    response = client.post('/api/models/submissions?name=Model', content=raw, headers={'Content-Type': 'application/zip'})
    assert response.status_code == 202, response.text
    item = response.json()
    assert item['sha256'] == hashlib.sha256(raw).hexdigest()
    assert TestClient(app).get('/api/jobs/' + item['job_id']).status_code == 404
    assert client.post('/api/practice', json={'submission_id': item['submission_id']}).status_code == 404
    assert client.get('/api/submissions').json()['submissions'][0]['track'] == 'model'


def test_model_project_executes_in_real_sandbox(client, tmp_path):
    if not sandbox_status()['image']:
        pytest.skip('Sandbox image unavailable')
    path = tmp_path / 'model.zip'
    path.write_bytes(archive({'agent.py': SOURCE, 'weights.json': '{"x":1}'}))
    bot = ModelContainerBot(path, 'model', decision_ms=100)
    try:
        bot.reset()
        assert bot.act({'legal_actions': ['check', 'fold']}) == {'action': 'check'}
    finally:
        bot.close()


def test_initializing_database_does_not_fail_another_workers_job(client):
    with db.connect(True) as c:
        c.execute('INSERT INTO jobs(id,kind,status,created_at,payload) VALUES(?,?,?,?,?)',
                  ('active', 'practice', 'running', time.time(), '{}'))
    db.initialize()
    with db.connect() as c:
        assert c.execute('SELECT status FROM jobs WHERE id=?', ('active',)).fetchone()[0] == 'running'


def test_expired_worker_lease_is_failed_and_cannot_publish(client):
    with db.connect(True) as c:
        c.execute("INSERT INTO jobs(id,kind,status,created_at,payload) VALUES(?,?,?,?,?)",
                  ('expired', 'practice', 'queued', time.time(), '{}'))
    job = worker.claim_job()
    with db.connect(True) as c:
        c.execute('UPDATE jobs SET lease_until=? WHERE id=?', (time.time() - 1, job['id']))
    assert worker.claim_job() is None
    worker.finish_job(job['id'], 'practice', result={'should_not_publish': True}, lease_owner=job['lease_owner'])
    with db.connect() as c:
        row = c.execute('SELECT status,result FROM jobs WHERE id=?', (job['id'],)).fetchone()
    assert row['status'] == 'failed'
    assert row['result'] is None


def test_model_upload_validation_and_practice_use_real_sandbox(client):
    if not sandbox_status()['image']:
        pytest.skip('Sandbox image unavailable')
    signup(client)
    raw = archive({'agent.py': SOURCE, 'weights.json': '{"x":1}'})
    submitted = client.post('/api/models/submissions?name=Model', content=raw,
                            headers={'Content-Type': 'application/zip'}).json()
    job = worker.claim_job()
    worker._run_claimed(job)
    assert client.get('/api/jobs/' + submitted['job_id']).json()['status'] == 'completed'
    entry = client.get('/api/submissions').json()['submissions'][0]
    assert entry['status'] == 'accepted' and entry['active'] and entry['track'] == 'model'
    practice = client.post('/api/practice', json={'submission_id': entry['id'], 'hands': 1})
    assert practice.status_code == 202, practice.text
    job = worker.claim_job()
    worker._run_claimed(job)
    result = client.get('/api/jobs/' + practice.json()['job_id']).json()
    assert result['status'] == 'completed'
    assert result['result']['scores'][0]['faults'] == 0
    assert client.get('/api/replays/' + result['result']['replay_id']).status_code == 200


def test_model_github_project_is_deterministic_and_checked(client, monkeypatch):
    files = {'agent.py': SOURCE.encode(), 'weights.json': b'{"x":1}'}
    blobs = {'a' * 40: files['agent.py'], 'b' * 40: files['weights.json']}
    monkeypatch.setattr(github_integration, 'installation_token', lambda _: 'token')
    def fake_request(url, **kwargs):
        import base64
        if '/git/trees/' in url:
            return {'truncated': False, 'tree': [
                {'type': 'blob', 'mode': '100644', 'path': name, 'size': len(data), 'sha': sha}
                for (name, data), sha in zip(files.items(), blobs)
            ]}
        if '/git/blobs/' in url:
            return {'encoding': 'base64', 'content': base64.b64encode(blobs[url.rsplit('/', 1)[1]]).decode()}
        raise AssertionError(url)
    monkeypatch.setattr(github_integration, 'request_json', fake_request)
    payload = {'installation_id': 1, 'full_name': 'owner/repo', 'commit_sha': 'c' * 40}
    first, source = github_integration.fetch_model_project(payload)
    second, _ = github_integration.fetch_model_project(payload)
    assert first == second
    assert source == SOURCE


def test_repository_connection_requires_github_user_access(client, monkeypatch):
    signup(client)
    authorized = {'allowed': False}
    def fake_request(url, **kwargs):
        if 'access_token' in url:
            return {'access_token': 'ephemeral'}
        if url.endswith('/user'):
            return {'id': 25, 'login': 'player'}
        if '/user/installations/' in url:
            return {'repositories': [{'id': 7, 'full_name': 'owner/bot'}] if authorized['allowed'] else []}
        raise AssertionError(url)
    monkeypatch.setattr(github_integration, 'request_json', fake_request)
    def attempt():
        start = client.post('/api/github/connect', json={'installation_id': 5, 'repository_id': 7,
                            'branch': 'arena', 'track': 'model'})
        state = parse_qs(urlparse(start.json()['url']).query)['state'][0]
        return client.get('/api/github/callback', params={'code': 'abc', 'state': state}, follow_redirects=False)
    assert attempt().status_code == 403
    assert client.get('/api/github/repositories').json()['repositories'] == []
    authorized['allowed'] = True
    assert attempt().status_code == 303
    repo = client.get('/api/github/repositories').json()['repositories'][0]
    assert (repo['full_name'], repo['branch'], repo['track']) == ('owner/bot', 'arena', 'model')


def test_model_track_round_scores_real_project(client):
    if not sandbox_status()['image']:
        pytest.skip('Sandbox image unavailable')
    team_id = signup(client)
    raw = archive({'agent.py': SOURCE, 'weights.json': '{"x":1}'})
    item = client.post('/api/models/submissions?name=Model', content=raw,
                       headers={'Content-Type': 'application/zip'}).json()
    worker._run_claimed(worker.claim_job())
    now = time.time()
    with db.connect(True) as c:
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  ('model-event', 'Model Event', 'model test event', 'building', 'Holdem', now - 2, now - 1,
                   60, 1, 1, 1, 50.0, None, 0, None))
        c.execute('INSERT INTO event_tracks VALUES(?,?)', ('model-event', 'model'))
        c.execute('INSERT INTO entries VALUES(?,?,?)', ('model-event', team_id, now))
    job_id = worker.enqueue_round('model-event', manual=True)
    worker._run_claimed(worker.claim_job())
    with db.connect() as c:
        score = c.execute('SELECT * FROM round_scores WHERE submission_id=?', (item['submission_id'],)).fetchone()
        job = c.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
    assert job['status'] == 'completed'
    assert score is not None
    assert client.get('/api/events/model-event/metrics').json()['metrics'][0]['tables_played'] == 1


def test_model_project_allows_weights_over_previous_two_mib_limit(client, tmp_path):
    if not sandbox_status()['image']:
        pytest.skip('Sandbox image unavailable')
    source = '''from pathlib import Path\nclass Agent:\n    def __init__(self):\n        assert Path(__file__).with_name("weights.bin").stat().st_size == 3 * 1024 * 1024\n    def act(self, observation):\n        return {"action": "check"}\n'''
    raw = archive({'agent.py': source, 'weights.bin': b'x' * (3 * 1024 * 1024)})
    validate_archive(raw)
    path = tmp_path / 'large-model.zip'
    path.write_bytes(raw)
    bot = ModelContainerBot(path, 'model', decision_ms=100)
    try:
        bot.reset()
        assert bot.act({'legal_actions': ['check']}) == {'action': 'check'}
    finally:
        bot.close()


def test_model_starter_download_contains_valid_project(client):
    response = client.get('/api/models/starter/download')
    assert response.status_code == 200
    assert 'class Agent' in validate_archive(response.content)
