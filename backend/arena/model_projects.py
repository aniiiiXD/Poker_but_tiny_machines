"""Bounded multi-file CPU model projects. Nothing submitted runs in the API."""
from __future__ import annotations

import ast
import hashlib
import io
import json
import stat
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import db
from .security import rate_limit, require_team

router = APIRouter(prefix='/api/models', tags=['model-projects'])
MAX_PROJECT = 16_777_216


class Showcase(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=10, max_length=4000)
    repository_url: str | None = Field(default=None, max_length=250)
    published: bool = False


@router.put('/showcase')
def save_showcase(body: Showcase, request: Request):
    user = require_team(request)
    if body.repository_url:
        url = urllib.parse.urlparse(body.repository_url)
        if (url.scheme != 'https' or url.netloc.lower() != 'github.com' or
            not url.path.strip('/') or url.query or url.fragment):
            raise HTTPException(422, 'Repository link must be a clean https://github.com URL.')
    with db.connect(True) as c:
        c.execute('''INSERT INTO research_showcases VALUES(?,?,?,?,?,?)
            ON CONFLICT(team_id) DO UPDATE SET title=excluded.title,description=excluded.description,
            repository_url=excluded.repository_url,published=excluded.published,updated_at=excluded.updated_at''',
                  (user['team_id'], body.title.strip(), body.description.strip(), body.repository_url,
                   int(body.published), time.time()))
    return {'ok': True, 'published': body.published}


@router.get('/showcase')
def list_showcases():
    with db.connect() as c:
        rows = c.execute('''SELECT t.id AS team_id,t.name AS team_name,r.title,r.description,
            r.repository_url,r.updated_at FROM research_showcases r JOIN teams t ON t.id=r.team_id
            WHERE r.published=1 ORDER BY r.updated_at DESC LIMIT 100''').fetchall()
    return {'projects': [dict(row) for row in rows]}


@router.get('/showcase/mine')
def my_showcase(request: Request):
    user = require_team(request)
    with db.connect() as c:
        row = c.execute('SELECT * FROM research_showcases WHERE team_id=?', (user['team_id'],)).fetchone()
    return {'project': dict(row) if row else None}


@router.get('/starter/download')
def download_starter(game: str = 'poker'):
    from .games import GameError, get_game

    try:
        spec = get_game(game)
    except GameError as exc:
        raise HTTPException(422, str(exc)) from None
    directory = 'starter-model' if spec.game_id == 'poker' else f'starter-model-{spec.game_id}'
    root = Path(__file__).resolve().parents[1] / directory
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('agent.py', 'weights.json', 'README.md'):
            z.write(root / name, name)
    output.seek(0)
    return StreamingResponse(output, media_type='application/zip',
                             headers={'Content-Disposition': f'attachment; filename="stack-theory-{spec.game_id}-model-starter.zip"'})


def validate_archive(raw: bytes):
    if not raw or len(raw) > MAX_PROJECT:
        raise ValueError('Project archive must be at most 16 MiB.')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos = z.infolist()
            if len(infos) > 100:
                raise ValueError('Project must contain at most 100 files.')
            total, seen = 0, set()
            for item in infos:
                path = PurePosixPath(item.filename)
                if (item.flag_bits & 1 or path.is_absolute() or not path.parts or
                    any(part in ('.', '..') for part in path.parts) or '\\' in item.filename or
                    stat.S_ISLNK(item.external_attr >> 16) or item.filename in seen):
                    raise ValueError('Unsafe or duplicate project path.')
                seen.add(item.filename)
                total += item.file_size
                if total > MAX_PROJECT:
                    raise ValueError('Uncompressed project must be at most 16 MiB.')
            if 'agent.py' not in seen:
                raise ValueError('Project must include agent.py at its root.')
            info = z.getinfo('agent.py')
            if info.file_size > 102400:
                raise ValueError('agent.py must be at most 100 KiB.')
            source = z.read(info).decode('utf-8')
            tree = ast.parse(source)
            if not any(isinstance(n, ast.ClassDef) and n.name == 'Agent' and
                       any(isinstance(m, ast.FunctionDef) and m.name == 'act' for m in n.body)
                       for n in tree.body):
                raise ValueError('agent.py must define class Agent with an act method.')
    except (zipfile.BadZipFile, UnicodeError, SyntaxError, KeyError, RuntimeError) as exc:
        raise ValueError('Invalid ZIP or Python source.') from exc
    return source


@router.get('/tracks')
def tracks():
    return {'tracks': [
        {'id': 'classic', 'format': 'single Python file', 'max_source_bytes': 102400,
         'default_decision_ms': 1, 'network': False},
        {'id': 'model', 'format': 'ZIP with agent.py and local model files',
         'max_archive_bytes': MAX_PROJECT, 'max_uncompressed_bytes': MAX_PROJECT,
         'max_files': 100, 'memory_mb': 512, 'runtime': 'Python 3.12 and NumPy 2.1.3',
         'default_decision_ms': 50, 'gpu': False, 'network': False},
    ]}


@router.post('/submissions', status_code=202)
async def submit_model(request: Request, name: str = 'Model bot', game: str = 'poker'):
    from .games import GameError, get_game

    user = require_team(request)
    if not user['email_verified']:
        raise HTTPException(403, 'Verify your email before submitting bots.')
    try:
        spec = get_game(game)
    except GameError as exc:
        raise HTTPException(422, str(exc)) from None
    if not 2 <= len(name.strip()) <= 60:
        raise HTTPException(422, 'Model name must be 2–60 characters.')
    rate_limit('model-submit:' + user['team_id'], 20, 3600)
    raw = await request.body()
    try:
        source = validate_archive(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    sid, jid = uuid.uuid4().hex, uuid.uuid4().hex
    path = db.DATA / 'bots' / (sid + '.zip')
    path.write_bytes(raw)
    checksum = hashlib.sha256(raw).hexdigest()
    try:
        with db.connect(True) as c:
            if c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('running','queued')").fetchone()[0] >= 20:
                raise HTTPException(429, 'The validation queue is full.')
            c.execute('''INSERT INTO submissions(id,team_id,name,source,sha256,created_at,status,
                         error,active,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                      (sid, user['team_id'], name.strip(), source, checksum, time.time(),
                       'validating', None, 0, spec.game_id, spec.rules_version))
            c.execute('INSERT INTO model_submissions VALUES(?,?,?)', (sid, checksum, len(raw)))
            c.execute('INSERT INTO jobs(id,kind,status,team_id,owner_id,created_at,payload) VALUES(?,?,?,?,?,?,?)',
                      (jid, 'model_validation', 'queued', user['team_id'], user['id'], time.time(),
                       json.dumps({'submission_id': sid, 'game_id': spec.game_id,
                                   'rules_version': spec.rules_version})))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {'submission_id': sid, 'job_id': jid, 'sha256': checksum, 'status': 'validating'}
