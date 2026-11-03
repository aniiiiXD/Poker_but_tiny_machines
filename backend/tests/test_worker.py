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
        c.execute('INSERT INTO events(id,title,description,status,variant,build_starts_at,build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('event', 'Test', 'Test event', 'building', 'NLHE', now-100, now-1, 10, 2, 2, 1, 1.0, None, 0, None, 'poker', 1))
        for i in range(2):
            team = f't{i}'
            c.execute('INSERT INTO teams VALUES(?,?,?,?)', (team, f'Team {i}', f'CODE{i}', now))
            c.execute('INSERT INTO users(id,name,email,password,college,role,team_id,created_at,email_verified) VALUES(?,?,?,?,?,?,?,?,1)', (f'u{i}', f'User {i}', f'u{i}@test.edu', 'hash', 'College', 'student', team, now))
            c.execute('INSERT INTO entries VALUES(?,?,?)', ('event', team, now))
            c.execute('INSERT INTO submissions(id,team_id,name,source,sha256,created_at,status,error,active,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,"poker",1)', (f's{i}', team, f'Bot {i}', 'source', 'sha', now, 'accepted', None, 1))
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
        c.execute('INSERT INTO submissions(id,team_id,name,source,sha256,created_at,status,error,active,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,"poker",1)', ('new', 't0', 'New bot', 'new source', 'sha2', time.time(), 'accepted', None, 1))
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


def test_tournament_replay_is_published_only_when_round_finishes(tournament, monkeypatch):
    calls = []
    def table(bots, seed, max_hands, capture):
        with db.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM replays WHERE source='tournament'").fetchone()[0] == 0
        calls.append(1)
        return {'points': [3] * 8, 'chips': [2000] * 8, 'faults': [0] * 8, 'errors': [None] * 8,
                'log': [], 'frames': [{'cards': ['As', 'Ks']}] if capture else [], 'hands': 1}
    monkeypatch.setattr(worker, 'play_table', table)
    job_id = worker.enqueue_round('event', manual=True)
    result = worker.score_round(job(job_id))
    assert len(calls) == 2
    assert len(result['replay_ids']) == 1
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM replays WHERE source='tournament'").fetchone()[0] == 1
        assert c.execute("SELECT status FROM rounds WHERE id=?", (result['round_id'],)).fetchone()[0] == 'completed'


def test_failed_round_does_not_publish_early_replay(tournament, monkeypatch):
    calls = []
    def table(bots, seed, max_hands, capture):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('worker failure')
        return {'points': [3] * 8, 'chips': [2000] * 8, 'faults': [0] * 8, 'errors': [None] * 8,
                'log': [], 'frames': [{'cards': ['As', 'Ks']}], 'hands': 1}
    monkeypatch.setattr(worker, 'play_table', table)
    job_id = worker.enqueue_round('event', manual=True)
    with pytest.raises(RuntimeError, match='worker failure'):
        worker.score_round(job(job_id))
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM replays WHERE source='tournament'").fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM round_scores').fetchone()[0] == 0


def test_round_scores_and_claimed_job_commit_atomically(tournament):
    job_id = worker.enqueue_round('event', manual=True)
    claimed = worker.claim_job()
    result = worker.score_round(claimed)
    with db.connect() as c:
        persisted_job = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        round_row = c.execute('SELECT status FROM rounds WHERE id=?', (result['round_id'],)).fetchone()
    assert persisted_job['status'] == 'completed'
    assert json.loads(persisted_job['result']) == result
    assert round_row['status'] == 'completed'
    worker.finish_job(job_id, 'round', error='late crash', lease_owner=claimed['lease_owner'])
    with db.connect() as c:
        assert c.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'completed'
        assert c.execute('SELECT status FROM rounds WHERE id=?', (result['round_id'],)).fetchone()[0] == 'completed'


def test_hand_logs_record_seating_and_each_retry_attempt(tournament, monkeypatch):
    count = []
    def fail_second(bots, seed, max_hands, capture):
        count.append(1)
        if len(count) == 2:
            raise RuntimeError('infrastructure interruption')
        return {'points': [3] * 8, 'chips': [2000] * 8, 'faults': [0] * 8, 'errors': [None] * 8,
                'log': [], 'frames': [], 'hands': 1}
    monkeypatch.setattr(worker, 'play_table', fail_second)
    first_job = worker.enqueue_round('event', manual=True)
    first = job(first_job)
    round_id = json.loads(first['payload'])['round_id']
    with pytest.raises(RuntimeError):
        worker.score_round(first)
    with db.connect(True) as c:
        c.execute("UPDATE rounds SET status='failed' WHERE id=?", (round_id,))
    second_job = worker.enqueue_round('event', manual=True)
    monkeypatch.setattr(worker, 'play_table', lambda bots, seed, max_hands, capture: {
        'points': [3] * 8, 'chips': [2000] * 8, 'faults': [0] * 8, 'errors': [None] * 8,
        'log': [], 'frames': [], 'hands': 1})
    worker.score_round(job(second_job))
    with db.connect() as c:
        rows = c.execute('''SELECT m.job_id,m.seating FROM hand_logs l JOIN hand_log_metadata m
                            ON m.hand_log_id=l.id WHERE l.round_id=?''', (round_id,)).fetchall()
    assert {row['job_id'] for row in rows} == {first_job, second_job}
    for row in rows:
        seats = json.loads(row['seating'])
        assert len(seats) == 8
        assert {seat['seat'] for seat in seats} == set(range(8))
        assert {seat['submission_id'] for seat in seats} == {'s0', 's1'}
        assert sum(seat['scoring'] for seat in seats) == 2


def test_scheduled_event_transitions_and_spaced_rounds(tournament, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(worker.time, 'time', lambda: clock[0])
    with db.connect(True) as c:
        c.execute("UPDATE events SET status='completed' WHERE id='event'")
        c.execute('INSERT INTO events(id,title,description,status,variant,build_starts_at,build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  ('future', 'Future event', 'Scheduled event', 'registration', 'NLHE', clock[0] + 100,
                   clock[0] + 200, 3600, 2, 1, 1, 1.0, None, 0, None, 'poker', 1))
        c.execute('INSERT INTO entries VALUES(?,?,?)', ('future', 't0', clock[0]))
        c.execute('INSERT INTO entries VALUES(?,?,?)', ('future', 't1', clock[0]))
    worker.coordinate_events_once()
    with db.connect() as c:
        assert c.execute("SELECT status FROM events WHERE id='future'").fetchone()[0] == 'registration'
    clock[0] += 100
    worker.coordinate_events_once()
    with db.connect() as c:
        assert c.execute("SELECT status FROM events WHERE id='future'").fetchone()[0] == 'building'
        assert c.execute("SELECT COUNT(*) FROM rounds WHERE event_id='future'").fetchone()[0] == 0
    clock[0] += 100
    worker.coordinate_events_once()
    worker.coordinate_events_once()
    with db.connect(True) as c:
        rounds = c.execute("SELECT * FROM rounds WHERE event_id='future'").fetchall()
        assert len(rounds) == 1 and rounds[0]['number'] == 1 and rounds[0]['status'] == 'queued'
        c.execute("UPDATE rounds SET status='completed' WHERE id=?", (rounds[0]['id'],))
    clock[0] += 3599
    worker.coordinate_events_once()
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM rounds WHERE event_id='future'").fetchone()[0] == 1
    clock[0] += 1
    worker.coordinate_events_once()
    worker.coordinate_events_once()
    with db.connect() as c:
        rounds = c.execute("SELECT * FROM rounds WHERE event_id='future' ORDER BY number").fetchall()
    assert [(row['number'], row['status']) for row in rounds] == [(1, 'completed'), (2, 'queued')]


def test_scheduler_does_not_attempt_empty_expired_events(tournament, monkeypatch):
    with db.connect(True) as c:
        c.execute("DELETE FROM entries WHERE event_id='event'")
    called = []
    monkeypatch.setattr(worker, 'enqueue_round', lambda event_id: called.append(event_id))
    worker.coordinate_events_once()
    assert 'event' not in called
    with db.connect() as c:
        assert c.execute("SELECT status FROM events WHERE id='event'").fetchone()[0] == 'building'
