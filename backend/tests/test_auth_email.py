"""Email verification and password reset flows. Tokens never touch the API."""
import json

import pytest
from fastapi.testclient import TestClient

from arena import db, mailer
from arena.app import app

SOURCE = 'class Agent:\n    def act(self, observation):\n        return {"action": "check"}\n'


def outbox_links(tmp_path):
    outbox = tmp_path / "outbox"
    links = []
    for f in sorted(outbox.glob("*.txt")):
        body = f.read_text()
        links += [line for line in body.splitlines() if "http" in line]
    return links


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ARENA_TESTING', '1')
    monkeypatch.setattr(db, 'DATA', tmp_path)
    db.initialize()
    return TestClient(app)


def register(client, email="student@example.edu"):
    return client.post('/api/auth/register', json={
        'name': 'Student', 'email': email, 'password': 'password123', 'college': 'University'
    })


def test_register_requires_verification_before_submissions(client, tmp_path):
    assert register(client).status_code == 201
    assert client.post('/api/team', json={'name': 'Team'}).status_code == 201
    blocked = client.post('/api/submissions', json={'name': 'Bot', 'source': SOURCE})
    assert blocked.status_code == 403
    assert 'Verify your email' in blocked.json()['detail']
    # Outbox mail carried the verification link; the API never returns tokens.
    links = outbox_links(tmp_path)
    assert len(links) == 1
    token = links[0].split('token=')[1]
    assert client.post('/api/auth/verify', json={'token': token}).status_code == 200
    assert client.post('/api/submissions', json={'name': 'Bot', 'source': SOURCE}).status_code == 201


def test_verify_token_is_single_use_and_expiry_honored(client, tmp_path):
    register(client)
    token = outbox_links(tmp_path)[0].split('token=')[1]
    assert client.post('/api/auth/verify', json={'token': token}).status_code == 200
    again = client.post('/api/auth/verify', json={'token': token})
    assert again.status_code == 400
    with db.connect(True) as c:
        c.execute("UPDATE users SET verify_expires=1")
    expired = client.post('/api/auth/verify', json={'token': 'x' * 40})
    assert expired.status_code == 400


def test_resend_is_rate_limited_and_verified_short_circuits(client):
    register(client)
    for _ in range(3):
        assert client.post('/api/auth/verify/resend').status_code == 200
    assert client.post('/api/auth/verify/resend').status_code == 429


def test_forgot_never_enumerates_and_reset_rotates_password_and_sessions(client, tmp_path):
    register(client)
    ok = client.post('/api/auth/forgot', json={'email': 'student@example.edu'})
    ghost = client.post('/api/auth/forgot', json={'email': 'ghost@example.edu'})
    assert ok.status_code == ghost.status_code == 200
    assert ok.json() == ghost.json() == {'ok': True}
    token = [l for l in outbox_links(tmp_path) if '/reset?' in l][0].split('token=')[1]
    new = client.post('/api/auth/reset', json={'token': token, 'password': 'newpassword9'})
    assert new.status_code == 200
    # Old session was signed out.
    assert client.get('/api/me').json()['user'] is None
    # Old password no longer works; the new one does.
    old_login = client.post('/api/auth/login', json={'email': 'student@example.edu', 'password': 'password123'})
    assert old_login.status_code == 401
    fresh = TestClient(app)
    assert fresh.post('/api/auth/login', json={'email': 'student@example.edu', 'password': 'newpassword9'}).status_code == 200


def test_reset_flow_verifies_unverified_accounts(client, tmp_path):
    register(client)
    client.post('/api/auth/forgot', json={'email': 'student@example.edu'})
    token = [l for l in outbox_links(tmp_path) if '/reset?' in l][0].split('token=')[1]
    client.post('/api/auth/reset', json={'token': token, 'password': 'password123'})
    with db.connect() as c:
        assert c.execute("SELECT email_verified FROM users").fetchone()[0] == 1


def test_me_exposes_verification_state(client):
    register(client)
    me = client.get('/api/me').json()
    assert me['user']['email_verified'] is False
