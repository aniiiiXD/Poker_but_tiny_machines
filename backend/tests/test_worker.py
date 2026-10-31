import json
import time

import pytest

from arena import db, worker
from arena.app import leaderboard


@pytest.fixture
def tournament(tmp_path, monkeypatch):
    monkeypatch.setenv('ARENA_TESTING', '1')
    monkeypatch.setattr(db, 'DATA', tmp_path)
    db.initialize()
    worker._stop.clear()
    now = time.time()
    with db.connect(True) as c:
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('event', 'Test', 'Test event', 'building', 'NLHE', now-100, now-1, 10, 2, 2, 1, 1.0, None, 0, None))
        for i in range(2):
            team = f't{i}'
            c.execute('INSERT INTO teams VALUES(?,?,?,?)', (team, f'Team {i}', f'CODE{i}', now))
            c.execute('INSERT INTO users(id,name,email,password,college,role,team_id,created_at,email_verified) VALUES(?,?,?,?,?,?,?,?,1)', (f'u{i}', f'User {i}', f'u{i}@test.edu', 'hash', 'College', 'student', team, now))
            c.execute('INSERT INTO entries VALUES(?,?,?)', ('event', team, now))
            c.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)', (f's{i}', team, f'Bot {i}', 'source', 'sha', now, 'accepted', None, 1))
    class FakeContainer:
        def __init__(self, path, name, decision_ms, image=None):
            self.name, self.path, self.image = name, path, image
        def close(self): pass
    def fake_table(bots, seed, max_hands, capture):
        return {'points': [2 if b.name.startswith('Team 0') else 5 for b in bots], 'chips': [2000]*8,
                'faults': [0]*8, 'errors': [None]*8, 'log': [{'hand': 1, 'actions': []}], 'frames': [], 'hands': 1}
    monkeypatch.setattr(worker, 'ContainerBot', FakeContainer)
    monkeypatch.setattr(worker, 'play_table', fake_table)
    monkeypatch.setattr(worker, 'sandbox_status', lambda: {'available': True, 'image': True, 'error': None})
    return tmp_path


def job(job_id):
    with db.connect() as c:
        return dict(c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())


def test_frozen_submission_and_weighted_round_scores(tournament):
    first_id = worker.enqueue_round('event', manual=True)
    first_job = job(first_id)
    frozen = json.loads(first_job['payload'])
    assert {t['submission_id'] for t in frozen['teams']} == {'s0', 's1'}
    with db.connect(True) as c:
        c.execute("UPDATE submissions SET active=0 WHERE id='s0'")
        c.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)', ('new', 't0', 'New bot', 'new source', 'sha2', time.time(), 'accepted', None, 1))
    assert worker.score_round(first_job)['teams_scored'] == 2
    with db.connect() as c:
        rows = c.execute('SELECT team_id,score,submission_id FROM round_scores WHERE round_id=?', (frozen['round_id'],)).fetchall()
    assert {r['team_id']: (r['score'], r['submission_id']) for r in rows} == {'t0': (2, 's0'), 't1': (5, 's1')}
    second_id = worker.enqueue_round('event', manual=True)
    second_job = job(second_id)
    assert {t['submission_id'] for t in json.loads(second_job['payload'])['teams']} == {'new', 's1'}
    worker.score_round(second_job)
    ranks = leaderboard('event')
    assert [(r['team_id'], r['total_score'], r['round_scores'][:2]) for r in ranks] == [('t1', 15, [5, 5]), ('t0', 6, [2, 2])]
    with db.connect() as c:
        assert c.execute("SELECT status FROM events WHERE id='event'").fetchone()['status'] == 'completed'


def test_sandbox_preflight_aborts_round_without_scoring(tournament, monkeypatch):
    monkeypatch.setattr(worker, 'sandbox_status',
                        lambda: {'available': False, 'image': False, 'error': 'Docker is unavailable'})
    job_id = worker.enqueue_round('event', manual=True)
    stored = job(job_id)
    round_id = json.loads(stored['payload'])['round_id']
    with pytest.raises(RuntimeError, match='Sandbox is not ready'):
        worker.score_round(stored)
    with db.connect() as c:
        assert c.execute('SELECT status FROM rounds WHERE id=?', (round_id,)).fetchone()['status'] == 'queued'
        assert c.execute('SELECT COUNT(*) FROM round_scores').fetchone()[0] == 0


def test_practice_reports_first_bot_error(tournament, monkeypatch):
    def faulty_table(bots, seed, max_hands, capture):
        errors = ['Decision exceeded 1 ms wall deadline'] + [None] * 7
        return {'points': [1.0] * 8, 'chips': [2000] * 8, 'faults': [3] + [0] * 7,
                'errors': errors, 'frames': [], 'hands': 2}
    monkeypatch.setattr(worker, 'play_table', faulty_table)
    result = worker.practice({'owner_id': None, 'team_id': None,
                              'payload': json.dumps({'submission_id': None, 'hands': 2, 'seed': 1})})
    assert result['scores'][0]['faults'] == 3
    assert result['scores'][0]['error'] == 'Decision exceeded 1 ms wall deadline'
    assert result['scores'][1]['error'] is None


def test_scored_round_writes_hand_logs_and_score_events(tournament, monkeypatch):
    def logged_table(bots, seed, max_hands, capture):
        return {'points': [2 if b.name.startswith('Team 0') else 5 for b in bots],
                'chips': [2000] * 8, 'faults': [0] * 8, 'errors': [None] * 8,
                'log': [{'hand': 1, 'blinds': [10, 20], 'board': [], 'actions': [], 'busted': []}],
                'frames': [], 'hands': 1}
    monkeypatch.setattr(worker, 'play_table', logged_table)
    job_id = worker.enqueue_round('event', manual=True)
    worker.score_round(job(job_id))
    with db.connect() as c:
        logs = c.execute("SELECT * FROM hand_logs WHERE round_id=?", (json.loads(job(job_id)['payload'])['round_id'],)).fetchall()
        # 2 teams = 1 table per iteration, 2 rounds worth of iterations in one round
        assert len(logs) >= 1
        assert all(row['seed'] is not None for row in logs)
        events = c.execute("SELECT kind FROM score_events WHERE round_id=?", (json.loads(job(job_id)['payload'])['round_id'],)).fetchall()
    assert {row[0] for row in events} == {'round-score'}


def test_score_event_chain_detects_tampering(tournament, monkeypatch):
    monkeypatch.setattr(worker, 'play_table', lambda bots, seed, max_hands, capture: {
        'points': [3] * 8, 'chips': [2000] * 8, 'faults': [0] * 8, 'errors': [None] * 8,
        'log': [], 'frames': [], 'hands': 1})
    job_id = worker.enqueue_round('event', manual=True)
    worker.score_round(job(job_id))
    with db.connect() as c:
        assert db.verify_score_chain(c) is True
        c.execute("UPDATE score_events SET payload=json(payload) WHERE rowid=1")
        # Direct SQL tampering (the exact attack the chain exists to catch)
        c.execute("UPDATE score_events SET payload=replace(payload,'3','9') WHERE rowid=1")
        assert db.verify_score_chain(c) is False
