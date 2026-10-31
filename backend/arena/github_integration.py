"""GitHub identity and team-owned, immutable bot submissions.

OAuth user tokens are used only during the callback and are never persisted.
The GitHub App's private key is used to mint short-lived installation tokens.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import db
from .security import current_user, digest_token, hash_password, new_session, require_team

router = APIRouter(prefix='/api/github', tags=['github'])
API = 'https://api.github.com'
SHA = re.compile(r'^[0-9a-f]{40}$')


def config(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if not value:
        raise HTTPException(503, f'GitHub integration is not configured ({name}).')
    return value


def request_json(url: str, *, token: str | None = None, data: dict | None = None, max_bytes: int = 300_000) -> dict:
    headers = {'Accept': 'application/json', 'User-Agent': 'CampusArena',
               'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = None if data is None else json.dumps(data).encode()
    if body is not None:
        headers['Content-Type'] = 'application/json'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=15) as response:
            raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError('GitHub response is too large')
        result = json.loads(raw)
        if not isinstance(result, (dict, list)):
            raise TypeError('Unexpected GitHub response')
        return result
    except (urllib.error.URLError, ValueError, TypeError, OSError) as exc:
        raise HTTPException(502, 'GitHub request failed; try again or reconnect the app.') from exc


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def installation_token(installation_id: int) -> str:
    now = int(time.time())
    header = b64(b'{"alg":"RS256","typ":"JWT"}')
    payload = b64(json.dumps({'iat': now - 60, 'exp': now + 540,
                              'iss': config('ARENA_GITHUB_APP_ID')}, separators=(',', ':')).encode())
    message = f'{header}.{payload}'
    try:
        signed = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', config('ARENA_GITHUB_PRIVATE_KEY_PATH')],
                                input=message.encode(), capture_output=True, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(503, 'GitHub App signing key is unavailable.') from exc
    jwt = message + '.' + b64(signed.stdout)
    result = request_json(f'{API}/app/installations/{int(installation_id)}/access_tokens', token=jwt, data={})
    if not isinstance(result.get('token'), str):
        raise HTTPException(502, 'GitHub did not issue an installation token.')
    return result['token']


def _set_session(response, token):
    response.set_cookie('arena_session', token, httponly=True,
                        secure=os.environ.get('ARENA_SECURE_COOKIE') == '1',
                        samesite='lax', max_age=604800, path='/')


@router.get('/login')
def login_start(request: Request):
    return _start(request, None)


@router.get('/discover')
def discover_start(request: Request):
    require_team(request)
    return _start(request, {'action': 'discover'})


@router.get('/discovered')
def discovered(request: Request):
    user = require_team(request)
    with db.connect() as c:
        row = c.execute('SELECT * FROM github_discoveries WHERE user_id=? AND expires_at>?',
                        (user['id'], time.time())).fetchone()
    if not row:
        raise HTTPException(404, 'Authorize GitHub repository discovery first.')
    return {'repositories': json.loads(row['repositories'])}


class ConnectRepository(BaseModel):
    installation_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    branch: str = Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9._/-]+$')
    track: str = Field(default='classic', pattern=r'^(classic|model)$')


@router.post('/connect')
def connect_start(body: ConnectRepository, request: Request, response: Response):
    user = require_team(request)
    if not user['email_verified']:
        raise HTTPException(403, 'Verify your email before connecting a repository.')
    if '..' in body.branch or body.branch.startswith('/') or body.branch.endswith('/'):
        raise HTTPException(422, 'Invalid branch name.')
    url, state = _authorization_url(request, {'installation_id': body.installation_id,
            'repository_id': body.repository_id, 'branch': body.branch, 'track': body.track}, user)
    _state_cookie(response, state)
    return {'url': url}


def _start(request, payload):
    url, state = _authorization_url(request, payload, current_user(request))
    response = RedirectResponse(url, status_code=302)
    _state_cookie(response, state)
    return response


def _state_cookie(response, state):
    response.set_cookie('arena_github_state', state, httponly=True,
                        secure=os.environ.get('ARENA_SECURE_COOKIE') == '1',
                        samesite='lax', max_age=600, path='/api/github/callback')


def _authorization_url(request, payload, user):
    client_id = config('ARENA_GITHUB_CLIENT_ID')
    config('ARENA_GITHUB_CLIENT_SECRET')
    redirect_uri = config('ARENA_GITHUB_CALLBACK_URL')
    state = secrets.token_urlsafe(32)
    with db.connect(True) as c:
        c.execute('DELETE FROM github_oauth_states WHERE expires_at<?', (time.time(),))
        c.execute('INSERT INTO github_oauth_states VALUES(?,?,?,?)',
                  (digest_token(state), user['id'] if user else None, time.time() + 600,
                   json.dumps(payload) if payload else None))
    return 'https://github.com/login/oauth/authorize?' + urllib.parse.urlencode({
        'client_id': client_id, 'redirect_uri': redirect_uri, 'state': state,
    }), state


@router.get('/callback')
def callback(request: Request, code: str = '', state: str = ''):
    if not code or not state:
        raise HTTPException(400, 'GitHub authorization was cancelled or missing.')
    if not hmac.compare_digest(request.cookies.get('arena_github_state', ''), state):
        raise HTTPException(400, 'GitHub authorization does not match this browser.')
    # Atomically consume state, and ensure linking stays with the initiating session.
    with db.connect(True) as c:
        row = c.execute('SELECT * FROM github_oauth_states WHERE state_hash=?', (digest_token(state),)).fetchone()
        c.execute('DELETE FROM github_oauth_states WHERE state_hash=?', (digest_token(state),))
    if not row or row['expires_at'] < time.time():
        raise HTTPException(400, 'GitHub authorization expired or was already used.')
    user = current_user(request)
    if row['user_id'] and (not user or user['id'] != row['user_id']):
        raise HTTPException(403, 'Sign in to the initiating account before linking GitHub.')
    token_response = request_json('https://github.com/login/oauth/access_token', data={
        'client_id': config('ARENA_GITHUB_CLIENT_ID'), 'client_secret': config('ARENA_GITHUB_CLIENT_SECRET'),
        'code': code, 'redirect_uri': config('ARENA_GITHUB_CALLBACK_URL'),
    })
    token = token_response.get('access_token')
    if not token:
        raise HTTPException(400, 'GitHub authorization failed.')
    profile = request_json(API + '/user', token=token)
    github_id = profile.get('id')
    if type(github_id) is not int:
        raise HTTPException(502, 'GitHub did not return a user identity.')
    login_name = str(profile.get('login') or '')[:100]
    payload = db.json_value(row['payload'])
    if payload and payload.get('action') == 'discover':
        if not user or not user['team_id']:
            raise HTTPException(403, 'A team is required.')
        found = []
        installations = request_json(API + '/user/installations?per_page=100', token=token).get('installations', [])
        for installation in installations[:100]:
            install_id = installation.get('id')
            if type(install_id) is not int:
                continue
            for page in range(1, 11):
                repos = request_json(f'{API}/user/installations/{install_id}/repositories?per_page=100&page={page}', token=token).get('repositories', [])
                found.extend({'installation_id': install_id, 'repository_id': r.get('id'),
                              'full_name': r.get('full_name'), 'private': r.get('private'),
                              'default_branch': r.get('default_branch')} for r in repos)
                if len(repos) < 100 or len(found) >= 1000:
                    break
            if len(found) >= 1000:
                break
        with db.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO github_discoveries VALUES(?,?,?)',
                      (user['id'], json.dumps(found[:1000]), time.time() + 600))
        response = RedirectResponse('/workshop?github=discovered', status_code=303)
        response.delete_cookie('arena_github_state', path='/api/github/callback')
        return response
    if payload:
        if not user or not user['team_id']:
            raise HTTPException(403, 'A team is required.')
        found = None
        # GitHub checks both the user's and the App's access to the installation.
        for page in range(1, 11):
            result = request_json(f"{API}/user/installations/{payload['installation_id']}/repositories?per_page=100&page={page}", token=token)
            repos = result.get('repositories', [])
            found = next((r for r in repos if r.get('id') == payload['repository_id']), None)
            if found or len(repos) < 100:
                break
        if not found:
            raise HTTPException(403, 'Repository is not accessible to your GitHub account and app installation.')
        name = str(found.get('full_name') or '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
            raise HTTPException(400, 'Invalid repository name from GitHub.')
        with db.connect(True) as c:
            c.execute('INSERT OR IGNORE INTO github_repositories(id,team_id,installation_id,repository_id,full_name,branch,created_at,track) VALUES(?,?,?,?,?,?,?,?)',
                      (uuid.uuid4().hex, user['team_id'], payload['installation_id'], payload['repository_id'], name, payload['branch'], time.time(), payload.get('track', 'classic')))
        response = RedirectResponse('/workshop?github=connected', status_code=303)
        response.delete_cookie('arena_github_state', path='/api/github/callback')
        return response
    with db.connect() as c:
        linked = c.execute('SELECT user_id FROM github_identities WHERE github_id=?', (github_id,)).fetchone()
    if linked and user and linked['user_id'] != user['id']:
        raise HTTPException(409, 'This GitHub identity is already linked to another account.')
    if linked:
        user_id = linked['user_id']
    elif user:
        user_id = user['id']
    else:
        emails = request_json(API + '/user/emails', token=token)
        email = next((e['email'].lower() for e in emails if e.get('primary') and e.get('verified') and e.get('email')), None)
        if not email:
            raise HTTPException(400, 'A verified primary GitHub email is required.')
        with db.connect(True) as c:
            if c.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
                raise HTTPException(409, 'Sign in to your existing account first to link GitHub.')
            user_id = uuid.uuid4().hex
            c.execute('INSERT INTO users(id,name,email,password,college,role,team_id,created_at,email_verified) VALUES(?,?,?,?,?,?,?,?,1)',
                      (user_id, str(profile.get('name') or login_name)[:70], email,
                       hash_password(secrets.token_urlsafe(32)), 'Not provided', 'student', None, time.time()))
    with db.connect(True) as c:
        existing = c.execute('SELECT github_id FROM github_identities WHERE user_id=?', (user_id,)).fetchone()
        if existing and existing['github_id'] != github_id:
            raise HTTPException(409, 'This account is already linked to a different GitHub identity.')
        c.execute('INSERT INTO github_identities VALUES(?,?,?,?,?) ON CONFLICT(github_id) DO UPDATE SET login=excluded.login,updated_at=excluded.updated_at',
                  (github_id, user_id, login_name, '', time.time()))
        session = new_session(c, user_id)
    response = RedirectResponse('/workshop?github=signed-in', status_code=303)
    _set_session(response, session)
    response.delete_cookie('arena_github_state', path='/api/github/callback')
    return response


@router.get('/repositories')
def repositories(request: Request):
    user = require_team(request)
    with db.connect() as c:
        rows = c.execute('SELECT id,full_name,branch,track,repository_id,installation_id,created_at FROM github_repositories WHERE team_id=? ORDER BY created_at DESC', (user['team_id'],)).fetchall()
    return {'repositories': [dict(r) for r in rows]}


@router.get('/jobs')
def validation_jobs(request: Request):
    user = require_team(request)
    with db.connect() as c:
        rows = c.execute("""SELECT id,status,progress,error,result,created_at,payload FROM jobs
            WHERE kind='github_validation' AND team_id=? ORDER BY created_at DESC LIMIT 50""",
                         (user['team_id'],)).fetchall()
    jobs = []
    for row in rows:
        payload = db.json_value(row['payload'])
        jobs.append({'id': row['id'], 'status': row['status'], 'progress': row['progress'],
                     'error': row['error'], 'result': db.json_value(row['result']),
                     'created_at': row['created_at'], 'repository': payload['full_name'],
                     'branch': payload['branch'], 'commit_sha': payload['commit_sha']})
    return {'jobs': jobs}


@router.post('/repositories/{connection_id}/sync', status_code=202)
def sync_repository(connection_id: str, request: Request):
    user = require_team(request)
    with db.connect() as c:
        row = c.execute('SELECT * FROM github_repositories WHERE id=? AND team_id=?',
                        (connection_id, user['team_id'])).fetchone()
    if not row:
        raise HTTPException(404, 'Connection not found.')
    token = installation_token(row['installation_id'])
    branch = urllib.parse.quote(row['branch'], safe='/')
    ref = request_json(f"{API}/repos/{row['full_name']}/git/ref/heads/{branch}", token=token)
    sha = ref.get('object', {}).get('sha', '')
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise HTTPException(502, 'GitHub did not return a valid branch commit.')
    job_id = uuid.uuid4().hex
    payload = {'connection_id': row['id'], 'team_id': row['team_id'], 'repository_id': row['repository_id'],
               'installation_id': row['installation_id'], 'full_name': row['full_name'], 'branch': row['branch'],
               'commit_sha': sha, 'delivery_id': 'manual-' + job_id, 'track': row['track']}
    with db.connect(True) as c:
        # The repository may have been disconnected during the GitHub request.
        updated = c.execute('UPDATE github_repositories SET latest_job_id=? WHERE id=? AND team_id=?',
                            (job_id, connection_id, user['team_id'])).rowcount
        if not updated:
            raise HTTPException(404, 'Connection not found.')
        c.execute('INSERT INTO jobs(id,kind,status,team_id,owner_id,created_at,payload) VALUES(?,?,?,?,?,?,?)',
                  (job_id, 'github_validation', 'queued', user['team_id'], user['id'], time.time(), json.dumps(payload)))
    return {'job_id': job_id, 'commit_sha': sha}


@router.delete('/repositories/{connection_id}')
def disconnect(connection_id: str, request: Request):
    user = require_team(request)
    with db.connect(True) as c:
        deleted = c.execute('DELETE FROM github_repositories WHERE id=? AND team_id=?', (connection_id, user['team_id'])).rowcount
    if not deleted:
        raise HTTPException(404, 'Connection not found.')
    return {'ok': True}


@router.post('/webhook')
async def webhook(request: Request):
    secret = config('ARENA_GITHUB_WEBHOOK_SECRET')
    body = await request.body()
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get('x-hub-signature-256', '')):
        raise HTTPException(401, 'Invalid webhook signature.')
    delivery = request.headers.get('x-github-delivery', '')
    if not delivery or len(delivery) > 100:
        raise HTTPException(400, 'Missing delivery ID.')
    if request.headers.get('x-github-event') != 'push':
        return {'ignored': True}
    try:
        event = json.loads(body)
        repo_id = int(event['repository']['id'])
        install_id = int(event['installation']['id'])
        ref = event['ref']
        sha = event['after']
        if not isinstance(ref, str) or not ref.startswith('refs/heads/') or not SHA.fullmatch(sha):
            raise ValueError('Invalid push')
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(400, 'Invalid push payload.') from None
    if sha == '0' * 40:
        return {'ignored': True}
    branch = ref[len('refs/heads/'):]
    jobs = []
    with db.connect(True) as c:
        if c.execute('SELECT 1 FROM github_deliveries WHERE delivery_id=?', (delivery,)).fetchone():
            return {'duplicate': True}
        c.execute('INSERT INTO github_deliveries VALUES(?,?)', (delivery, time.time()))
        rows = c.execute('SELECT * FROM github_repositories WHERE repository_id=? AND installation_id=? AND branch=?',
                         (repo_id, install_id, branch)).fetchall()
        for row in rows:
            if c.execute('SELECT 1 FROM github_pushes WHERE connection_id=? AND commit_sha=?',
                         (row['id'], sha)).fetchone():
                continue
            if c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('running','queued')").fetchone()[0] >= 20:
                raise HTTPException(503, 'Validation queue is full; retry delivery later.')
            job_id = uuid.uuid4().hex
            payload = {'connection_id': row['id'], 'team_id': row['team_id'], 'repository_id': repo_id,
                       'installation_id': install_id, 'full_name': row['full_name'], 'branch': branch,
                       'commit_sha': sha, 'delivery_id': delivery, 'track': row['track']}
            c.execute('INSERT INTO jobs(id,kind,status,team_id,created_at,payload) VALUES(?,?,?,?,?,?)',
                      (job_id, 'github_validation', 'queued', row['team_id'], time.time(), json.dumps(payload)))
            c.execute('UPDATE github_repositories SET latest_job_id=? WHERE id=?', (job_id, row['id']))
            c.execute('INSERT INTO github_pushes VALUES(?,?,?)', (row['id'], sha, job_id))
            jobs.append(job_id)
    return {'queued': len(jobs)}


def fetch_source(payload):
    token = installation_token(payload['installation_id'])
    name, sha = payload['full_name'], payload['commit_sha']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name) or not SHA.fullmatch(sha):
        raise ValueError('Invalid repository or commit.')
    result = request_json(f'{API}/repos/{name}/contents/agent.py?ref={sha}', token=token)
    if result.get('encoding') != 'base64' or not isinstance(result.get('content'), str):
        raise ValueError('Repository must contain agent.py at its root.')
    try:
        source = base64.b64decode(result['content'], validate=False).decode('utf-8')
    except (ValueError, UnicodeError) as exc:
        raise ValueError('agent.py must be valid UTF-8.') from exc
    if len(source.encode()) > 102400:
        raise ValueError('agent.py exceeds 100 KiB.')
    tree = ast.parse(source)
    if not any(isinstance(n, ast.ClassDef) and n.name == 'Agent' and
               any(isinstance(m, ast.FunctionDef) and m.name == 'act' for m in n.body) for n in tree.body):
        raise ValueError('agent.py must define class Agent with an act method.')
    return source


def fetch_model_project(payload):
    """Build a bounded ZIP from the immutable Git tree using installation access."""
    from .model_projects import MAX_PROJECT, validate_archive
    token = installation_token(payload['installation_id'])
    name, sha = payload['full_name'], payload['commit_sha']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name) or not SHA.fullmatch(sha):
        raise ValueError('Invalid repository or commit.')
    tree = request_json(f'{API}/repos/{name}/git/trees/{sha}?recursive=1', token=token)
    if tree.get('truncated') or not isinstance(tree.get('tree'), list):
        raise ValueError('Project tree is too large or unavailable.')
    files = [entry for entry in tree['tree'] if entry.get('type') != 'tree']
    if len(files) > 100:
        raise ValueError('Project must contain at most 100 files.')
    total = 0
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for entry in files:
            size, blob_sha = entry.get('size'), entry.get('sha')
            if (entry.get('type') != 'blob' or entry.get('mode') not in ('100644', '100755') or
                type(size) is not int or size < 0 or not isinstance(blob_sha, str) or not SHA.fullmatch(blob_sha)):
                raise ValueError('Project contains unsupported files, symlinks or submodules.')
            total += size
            if total > MAX_PROJECT:
                raise ValueError('Project exceeds the 16 MiB uncompressed limit.')
            blob = request_json(f'{API}/repos/{name}/git/blobs/{blob_sha}', token=token,
                                max_bytes=24_000_000)
            if blob.get('encoding') != 'base64':
                raise ValueError('Unable to read a project file.')
            raw = base64.b64decode(blob.get('content', ''), validate=False)
            if len(raw) != size:
                raise ValueError('Project file length does not match its Git tree.')
            item = zipfile.ZipInfo(entry.get('path', ''), date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(item, raw)
    raw = out.getvalue()
    source = validate_archive(raw)
    return raw, source
