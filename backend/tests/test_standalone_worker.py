"""Standalone worker process and atomic job claims."""
import json
import subprocess
from pathlib import Path
import sys
import time

import pytest

from arena import db, worker


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('ARENA_TESTING', '1')
    monkeypatch.setattr(db, 'DATA', tmp_path)
    db.initialize()
    return tmp_path


def enqueue_practice(seed=1):
    job_id = 'job-' + str(seed)
    with db.connect(True) as c:
        c.execute(
            "INSERT INTO jobs(id,kind,status,created_at,payload) VALUES(?,?,?,?,?)",
            (job_id, 'practice', 'queued', time.time(),
             json.dumps({'submission_id': None, 'hands': 1, 'seed': seed})),
        )
    return job_id


def test_claim_is_atomic_and_marks_running(data_dir):
    enqueue_practice(1)
    enqueue_practice(2)
    first = worker.claim_job()
    second = worker.claim_job()
    assert first['id'] != second['id']
    assert worker.claim_job() is None  # nothing queued remains
    with db.connect() as c:
        states = dict(c.execute("SELECT id,status FROM jobs").fetchall())
    assert states == {'job-1': 'running', 'job-2': 'running'}


def test_finish_fails_the_round_for_round_jobs(data_dir):
    with db.connect(True) as c:
        c.execute("INSERT INTO rounds VALUES(?,?,?,?,?,?,?)", ('r1', 'evt', 1, 'running', time.time(), None, 8))
        c.execute(
            "INSERT INTO jobs(id,kind,status,created_at,payload) VALUES(?,?,?,?,?)",
            ('jobr', 'round', 'running', time.time(), json.dumps({'round_id': 'r1'})),
        )
    worker.finish_job('jobr', 'round', error='sandbox vanished')
    with db.connect() as c:
        assert c.execute("SELECT status FROM jobs WHERE id='jobr'").fetchone()[0] == 'failed'
        assert c.execute("SELECT status FROM rounds WHERE id='r1'").fetchone()[0] == 'failed'


def test_standalone_worker_once_completes_a_baseline_practice(data_dir):
    job_id = enqueue_practice(7)
    backend = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, '-m', 'arena.worker', '--once'],
        capture_output=True, text=True, timeout=120,
        env={
            'ARENA_TESTING': '1', 'ARENA_DATA_DIR': str(data_dir),
            'PATH': '/usr/bin:/bin', 'PYTHONPATH': backend,
        },
        cwd=data_dir.parent,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    with db.connect() as c:
        row = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    assert row['status'] == 'completed'
    payload = db.json_value(row['result'])
    assert payload['hands'] >= 1
    assert len(payload['scores']) == 8


def test_standalone_worker_once_exits_nonzero_on_failure(data_dir):
    job_id = enqueue_practice(9)
    # A poisoned job payload exercises the failure path in the subprocess.
    with db.connect(True) as c:
        c.execute(
            "UPDATE jobs SET payload=? WHERE id=?",
            (json.dumps({'submission_id': 'missing-bot', 'hands': 1, 'seed': 9}), job_id),
        )
    backend = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, '-m', 'arena.worker', '--once'],
        capture_output=True, text=True, timeout=120,
        env={
            'ARENA_TESTING': '1', 'ARENA_DATA_DIR': str(data_dir),
            'PATH': '/usr/bin:/bin', 'PYTHONPATH': backend,
        },
        cwd=data_dir.parent,
    )
    assert result.returncode == 1
    with db.connect() as c:
        row = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    assert row['status'] == 'failed'
    assert row['error']


def test_api_lifespan_starts_and_stops_embedded_worker(data_dir, monkeypatch):
    import threading
    from fastapi.testclient import TestClient
    from arena.app import app

    monkeypatch.delenv('ARENA_TESTING', raising=False)
    monkeypatch.delenv('ARENA_EMBEDDED_WORKER', raising=False)
    monkeypatch.setattr(worker, 'seed_exhibition', lambda: None)
    monkeypatch.setattr(worker, '_stop', threading.Event())
    with TestClient(app) as client:
        assert client.get('/api/models/tracks').status_code == 200
        assert len(worker._threads) >= 2
        assert all(thread.is_alive() for thread in worker._threads)
    assert worker._threads == []
