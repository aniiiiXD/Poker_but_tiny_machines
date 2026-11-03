"""Migration safety: populated pre-change databases upgrade cleanly, twice."""
import time

import pytest

from arena import db

# The schema exactly as it existed before the multi-game columns were added
# (submissions/events/replays/github_repositories without game columns).
OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
 password TEXT NOT NULL, college TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'student',
 team_id TEXT, created_at REAL NOT NULL,
 email_verified INTEGER NOT NULL DEFAULT 0, verify_token TEXT, verify_expires REAL,
 reset_token TEXT, reset_expires REAL
);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,join_code TEXT UNIQUE NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY,team_id TEXT NOT NULL,name TEXT NOT NULL,
 source TEXT NOT NULL,sha256 TEXT NOT NULL,created_at REAL NOT NULL,status TEXT NOT NULL,error TEXT,active INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS submissions_team ON submissions(team_id,created_at);
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,
 status TEXT NOT NULL,variant TEXT NOT NULL,build_starts_at REAL NOT NULL,build_ends_at REAL NOT NULL,
 round_interval_seconds INTEGER NOT NULL,round_count INTEGER NOT NULL,tables_per_round INTEGER NOT NULL,
 max_hands INTEGER NOT NULL,decision_ms REAL NOT NULL,sponsor_name TEXT,exhibition INTEGER NOT NULL DEFAULT 0,
 sandbox_digest TEXT);
CREATE TABLE IF NOT EXISTS entries (event_id TEXT NOT NULL,team_id TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(event_id,team_id));
CREATE TABLE IF NOT EXISTS rounds (id TEXT PRIMARY KEY,event_id TEXT NOT NULL,number INTEGER NOT NULL,status TEXT NOT NULL,
 starts_at REAL NOT NULL,finished_at REAL,entries_count INTEGER NOT NULL DEFAULT 0,UNIQUE(event_id,number));
CREATE TABLE IF NOT EXISTS round_scores (round_id TEXT NOT NULL,team_id TEXT NOT NULL,team_name TEXT NOT NULL,college TEXT NOT NULL,
 score REAL NOT NULL,faults INTEGER NOT NULL,submission_id TEXT,is_baseline INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(round_id,team_id));
CREATE TABLE IF NOT EXISTS round_metrics (
 round_id TEXT NOT NULL,team_id TEXT NOT NULL,tables_played INTEGER NOT NULL,
 points_std_error REAL,PRIMARY KEY(round_id,team_id)
);
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,team_id TEXT,owner_id TEXT,
 created_at REAL NOT NULL,progress INTEGER NOT NULL DEFAULT 0,payload TEXT NOT NULL,result TEXT,error TEXT,
 lease_owner TEXT,lease_until REAL);
CREATE TABLE IF NOT EXISTS replays (id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at REAL NOT NULL,hand_count INTEGER NOT NULL,
 source TEXT NOT NULL,owner_id TEXT,team_id TEXT,frames TEXT NOT NULL,summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sponsor_inquiries (id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL,company TEXT NOT NULL,message TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS hand_logs (id TEXT PRIMARY KEY, round_id TEXT NOT NULL, table_index INTEGER NOT NULL,
 seed INTEGER NOT NULL, created_at REAL NOT NULL, log TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hand_log_metadata (
 hand_log_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,seating TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS score_events (id TEXT PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL,
 round_id TEXT, team_id TEXT, payload TEXT NOT NULL, prev_hash TEXT, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY,count INTEGER NOT NULL,reset_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS github_identities (
 github_id INTEGER PRIMARY KEY, user_id TEXT NOT NULL UNIQUE, login TEXT NOT NULL,
 access_token TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS github_repositories (
 id TEXT PRIMARY KEY, team_id TEXT NOT NULL, installation_id INTEGER NOT NULL,
 repository_id INTEGER NOT NULL, full_name TEXT NOT NULL, branch TEXT NOT NULL,
 created_at REAL NOT NULL, latest_job_id TEXT, track TEXT NOT NULL DEFAULT 'classic',
 UNIQUE(team_id,repository_id,branch)
);
CREATE TABLE IF NOT EXISTS model_submissions (
 submission_id TEXT PRIMARY KEY, archive_sha256 TEXT NOT NULL, archive_bytes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS event_tracks (
 event_id TEXT PRIMARY KEY, track TEXT NOT NULL CHECK(track IN ('classic','model'))
);
"""


@pytest.fixture
def old_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    db.DATA.mkdir(parents=True, exist_ok=True)
    import sqlite3

    raw = sqlite3.connect(tmp_path / "arena.sqlite")
    raw.executescript(OLD_SCHEMA)
    now = time.time()
    raw.execute("INSERT INTO teams VALUES(?,?,?,?)", ("t1", "Team One", "CODE11", now))
    raw.execute("""INSERT INTO users(id,name,email,password,college,role,team_id,created_at,email_verified)
                   VALUES(?,?,?,?,?,?,?,?,1)""",
                ("u1", "User One", "u1@test.edu", "hash", "College", "student", "t1", now))
    raw.execute("INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)",
                ("keep-active", "t1", "Old poker bot", "print(1)", "sha", now, "accepted", None, 1))
    raw.execute("INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)",
                ("old-inactive", "t1", "Older poker bot", "print(2)", "sha2", now - 1, "accepted", None, 0))
    raw.execute("""INSERT INTO events(id,title,description,status,variant,build_starts_at,
        build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
        decision_ms,sponsor_name,exhibition,sandbox_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("old-event", "Old event", "Pre-change event", "completed", "No-limit Texas Hold’em",
         now - 100, now - 90, 60, 1, 1, 1, 1.0, None, 0, None))
    raw.execute("INSERT INTO entries VALUES(?,?,?)", ("old-event", "t1", now))
    raw.execute("INSERT INTO rounds VALUES(?,?,?,?,?,?,?)", ("old-r1", "old-event", 1, "completed", now, now, 1))
    raw.execute("""INSERT INTO round_scores(round_id,team_id,team_name,college,score,faults,
        submission_id,is_baseline) VALUES(?,?,?,?,?,?,?,?)""",
        ("old-r1", "t1", "Team One", "College", 3.0, 0, "keep-active", 0))
    raw.execute("INSERT INTO replays VALUES(?,?,?,?,?,?,?,?,?)",
        ("old-replay", "Old replay", now, 1, "tournament", None, None, "[]", "{}"))
    raw.execute("""INSERT INTO github_repositories(id,team_id,installation_id,repository_id,
        full_name,branch,created_at,track) VALUES(?,?,?,?,?,?,?,?)""",
        ("gh1", "t1", 111, 222, "owner/repo", "main", now, "classic"))
    raw.commit()
    raw.close()
    return tmp_path


def columns(tmp_path, table):
    import sqlite3

    raw = sqlite3.connect(tmp_path / "arena.sqlite")
    cols = {row[1]: row for row in raw.execute(f"PRAGMA table_info({table})")}
    raw.close()
    return cols


def test_upgrade_preserves_rows_and_defaults_to_poker(old_database):
    db.initialize()  # first upgrade
    with db.connect() as c:
        submission = c.execute("SELECT * FROM submissions WHERE id='keep-active'").fetchone()
        assert submission["active"] == 1  # the team's active poker bot survives
        assert submission["game_id"] == "poker"
        assert submission["rules_version"] == 1
        inactive = c.execute("SELECT game_id FROM submissions WHERE id='old-inactive'").fetchone()
        assert inactive["game_id"] == "poker"
        event = c.execute("SELECT game_id,rules_version,variant FROM events WHERE id='old-event'").fetchone()
        assert event["game_id"] == "poker" and event["rules_version"] == 1
        assert c.execute("SELECT game_id FROM replays WHERE id='old-replay'").fetchone()[0] == "poker"
        assert c.execute("SELECT game_id FROM github_repositories WHERE id='gh1'").fetchone()[0] == "poker"
        assert c.execute("SELECT score FROM round_scores WHERE team_id='t1'").fetchone()[0] == 3.0
    # A populated database does not grow a second seed event.
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert "game_id" in columns(old_database, "submissions")
    assert "game_id" in columns(old_database, "events")
    assert "game_id" in columns(old_database, "replays")
    assert "game_id" in columns(old_database, "github_repositories")

    db.initialize()  # second run must be an idempotent no-op
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 2
        assert c.execute("SELECT active FROM submissions WHERE id='keep-active'").fetchone()[0] == 1
    assert db.verify_score_chain(db.connect().__enter__()) is True


def test_fresh_initialization_creates_game_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    db.initialize()
    assert "game_id" in columns(tmp_path, "submissions")
    assert "rules_version" in columns(tmp_path, "events")
    with db.connect() as c:
        seed = c.execute("SELECT game_id,variant FROM events WHERE id='campus-open-001'").fetchone()
        assert seed["game_id"] == "poker"


def test_activation_is_scoped_by_team_game_and_track(old_database):
    from arena import worker

    db.initialize()
    with db.connect(True) as c:
        # Three coexisting active bots: poker classic, poker model, bluff classic.
        for sid, game, track in (("pc", "poker", "classic"), ("pm", "poker", "model"),
                                 ("bc", "bluff", "classic")):
            worker.deactivate_active(c, "t1", game, track)
            c.execute("""INSERT INTO submissions(id,team_id,name,source,sha256,created_at,status,
                         error,active,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (sid, "t1", f"Bot {sid}", "s", "sha-" + sid, time.time(), "accepted", None, 1, game, 1))
            if track == "model":
                c.execute("INSERT INTO model_submissions VALUES(?,?,?)", (sid, "sha-" + sid, 10))
        rows = dict(c.execute("SELECT id,active FROM submissions").fetchall())
    assert rows["pc"] == 1 and rows["pm"] == 1 and rows["bc"] == 1

    with db.connect(True) as c:
        # Activating another bluff classic bot drops only the old bluff one.
        worker.deactivate_active(c, "t1", "bluff", "classic")
        c.execute("""UPDATE submissions SET active=1 WHERE id='bc2'""") if False else None
        c.execute("""INSERT INTO submissions(id,team_id,name,source,sha256,created_at,status,
                     error,active,game_id,rules_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  ("bc2", "t1", "Bot bc2", "s", "sha-bc2", time.time(), "accepted", None, 1, "bluff", 1))
        rows = dict(c.execute("SELECT id,active FROM submissions").fetchall())
    assert rows["bc"] == 0
    assert rows["bc2"] == 1
    assert rows["pc"] == 1 and rows["pm"] == 1
