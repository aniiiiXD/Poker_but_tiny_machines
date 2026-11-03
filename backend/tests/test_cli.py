import os
import sqlite3
import subprocess
import sys

import pytest

from arena.sandbox import MODEL_IMAGE, image_id


def test_create_model_event_pins_image_and_lists_all_events(tmp_path):
    if not image_id(MODEL_IMAGE):
        pytest.skip('Model sandbox image unavailable')
    env = os.environ.copy()
    env['ARENA_DATA_DIR'] = str(tmp_path)
    args = [sys.executable, '-m', 'arena.cli']
    created = subprocess.run(args + ['create-event', 'Model test', '--track', 'model', '--tables', '1',
                                      '--hands', '1', '--rounds', '1', '--starts-in', '0'],
                             env=env, text=True, capture_output=True, check=True)
    event_id = created.stdout.strip()
    with sqlite3.connect(tmp_path / 'arena.sqlite') as c:
        assert c.execute('SELECT track FROM event_tracks WHERE event_id=?', (event_id,)).fetchone() == ('model',)
        digest, milliseconds = c.execute('SELECT sandbox_digest,decision_ms FROM events WHERE id=?', (event_id,)).fetchone()
        assert digest == image_id(MODEL_IMAGE)
        assert milliseconds == 50.0
    listed = subprocess.run(args + ['events'], env=env, text=True, capture_output=True, check=True)
    assert 'Model test' in listed.stdout and 'Stack Theory Open' in listed.stdout
