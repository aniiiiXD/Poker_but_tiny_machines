"""End-to-end round execution with real Docker and the real poker engine."""
import json
import time
from pathlib import Path

import pytest
from arena import db, worker
from arena.app import leaderboard
from arena.sandbox import sandbox_status


def test_real_round_freezes_sources_and_produces_scored_replay(tmp_path, monkeypatch):
    if not sandbox_status()['image']:
        pytest.skip('Build the local Docker sandbox image to run live round integration')
    monkeypatch.setattr(db, 'DATA', tmp_path)
    db.initialize()
    worker._stop.clear()
    source = (Path(__file__).resolve().parents[1] / 'starter-kit' / 'agent.py').read_text()
    now = time.time()
    with db.connect(True) as c:
        from arena.sandbox import image_id
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('real-round', 'Real round test', 'Isolated test', 'building', 'NLHE', now - 100, now - 1, 10, 1, 1, 4, 1.0, None, 0, image_id()))
        for i in range(2):
            c.execute('INSERT INTO teams VALUES(?,?,?,?)', (f'team{i}', f'Test bot {i}', f'CODE{i}', now))
            c.execute('INSERT INTO users(id,name,email,password,college,role,team_id,created_at,email_verified) VALUES(?,?,?,?,?,?,?,?,1)', (f'user{i}', 'Test user', f'{i}@test.invalid', 'unused', 'Test college', 'student', f'team{i}', now))
            c.execute('INSERT INTO entries VALUES(?,?,?)', ('real-round', f'team{i}', now))
            c.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)', (f'bot{i}', f'team{i}', 'Test bot', source, 'testhash', now, 'accepted', None, 1))
            (db.DATA / 'bots' / f'bot{i}.py').write_text(source)
    job_id = worker.enqueue_round('real-round', manual=True)
    with db.connect() as c:
        job = dict(c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
    result = worker.score_round(job)
    assert result['teams_scored'] == 2
    assert len(result['replay_ids']) == 1
    board = leaderboard('real-round')
    assert len(board) == 2
    assert all(0 <= row['total_score'] <= 8 for row in board)
    with db.connect() as c:
        assert c.execute("SELECT status FROM events WHERE id='real-round'").fetchone()[0] == 'completed'
        scores = c.execute('SELECT submission_id FROM round_scores WHERE round_id=?', (result['round_id'],)).fetchall()
        assert {r[0] for r in scores} == {'bot0', 'bot1'}
        replay = c.execute('SELECT * FROM replays WHERE id=?', (result['replay_ids'][0],)).fetchone()
    frames = json.loads(replay['frames'])
    assert len(frames) > 4
    assert len(frames[0]['seats']) == 8
    assert sum(json.loads(replay['summary'])['chips']) == 16000
