from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DATA = Path(os.environ.get("ARENA_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
SCHEMA = """
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
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created_at);
CREATE TABLE IF NOT EXISTS replays (id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at REAL NOT NULL,hand_count INTEGER NOT NULL,
 source TEXT NOT NULL,owner_id TEXT,team_id TEXT,frames TEXT NOT NULL,summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sponsor_inquiries (id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL,company TEXT NOT NULL,message TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS hand_logs (id TEXT PRIMARY KEY, round_id TEXT NOT NULL, table_index INTEGER NOT NULL,
 seed INTEGER NOT NULL, created_at REAL NOT NULL, log TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS hand_logs_round ON hand_logs(round_id,table_index);
CREATE TABLE IF NOT EXISTS score_events (id TEXT PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL,
 round_id TEXT, team_id TEXT, payload TEXT NOT NULL, prev_hash TEXT, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY,count INTEGER NOT NULL,reset_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS github_identities (
 github_id INTEGER PRIMARY KEY, user_id TEXT NOT NULL UNIQUE, login TEXT NOT NULL,
 access_token TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS github_oauth_states (
 state_hash TEXT PRIMARY KEY, user_id TEXT, expires_at REAL NOT NULL, payload TEXT
);
CREATE TABLE IF NOT EXISTS github_discoveries (
 user_id TEXT PRIMARY KEY, repositories TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS github_repositories (
 id TEXT PRIMARY KEY, team_id TEXT NOT NULL, installation_id INTEGER NOT NULL,
 repository_id INTEGER NOT NULL, full_name TEXT NOT NULL, branch TEXT NOT NULL,
 created_at REAL NOT NULL, latest_job_id TEXT, track TEXT NOT NULL DEFAULT 'classic',
 UNIQUE(team_id,repository_id,branch)
);
CREATE TABLE IF NOT EXISTS github_deliveries (
 delivery_id TEXT PRIMARY KEY, received_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS github_pushes (
 connection_id TEXT NOT NULL, commit_sha TEXT NOT NULL, job_id TEXT NOT NULL,
 PRIMARY KEY(connection_id,commit_sha)
);
CREATE TABLE IF NOT EXISTS github_submissions (
 submission_id TEXT PRIMARY KEY, repository_id INTEGER NOT NULL, full_name TEXT NOT NULL,
 branch TEXT NOT NULL, commit_sha TEXT NOT NULL, delivery_id TEXT NOT NULL,
 UNIQUE(repository_id,branch,commit_sha,submission_id)
);
CREATE TABLE IF NOT EXISTS model_submissions (
 submission_id TEXT PRIMARY KEY, archive_sha256 TEXT NOT NULL, archive_bytes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS event_tracks (
 event_id TEXT PRIMARY KEY, track TEXT NOT NULL CHECK(track IN ('classic','model'))
);
"""


@contextmanager
def connect(write=False):
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / "arena.sqlite", timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    if write:
        c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        if write:
            c.commit()
    except Exception:
        if write:
            c.rollback()
        raise
    finally:
        c.close()


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "bots").mkdir(exist_ok=True)
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        c.commit()
    with connect(True) as c:
        now = time.time()
        # Migrate databases created before a column existed.
        users_cols = {row[1] for row in c.execute("PRAGMA table_info(users)")}
        for col, ddl in (
            ("email_verified", "INTEGER NOT NULL DEFAULT 0"),
            ("verify_token", "TEXT"),
            ("verify_expires", "REAL"),
            ("reset_token", "TEXT"),
            ("reset_expires", "REAL"),
        ):
            if col not in users_cols:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        events_cols = {row[1] for row in c.execute("PRAGMA table_info(events)")}
        if "sandbox_digest" not in events_cols:
            c.execute("ALTER TABLE events ADD COLUMN sandbox_digest TEXT")
        oauth_cols = {row[1] for row in c.execute("PRAGMA table_info(github_oauth_states)")}
        if "payload" not in oauth_cols:
            c.execute("ALTER TABLE github_oauth_states ADD COLUMN payload TEXT")
        github_repo_cols = {row[1] for row in c.execute("PRAGMA table_info(github_repositories)")}
        if "latest_job_id" not in github_repo_cols:
            c.execute("ALTER TABLE github_repositories ADD COLUMN latest_job_id TEXT")
        if "track" not in github_repo_cols:
            c.execute("ALTER TABLE github_repositories ADD COLUMN track TEXT NOT NULL DEFAULT 'classic'")
        jobs_cols = {row[1] for row in c.execute('PRAGMA table_info(jobs)')}
        if 'lease_owner' not in jobs_cols:
            c.execute('ALTER TABLE jobs ADD COLUMN lease_owner TEXT')
        if 'lease_until' not in jobs_cols:
            c.execute('ALTER TABLE jobs ADD COLUMN lease_until REAL')
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute("DELETE FROM rate_limits WHERE reset_at < ?", (now,))
        # Do not reset running jobs here: another API or worker process may own them.
        if not c.execute("SELECT 1 FROM events LIMIT 1").fetchone():
            c.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "campus-open-001",
                    "Campus Open · Founding round",
                    "Our first online student event. Build solo or with a teammate, test your strategy, and compete from anywhere. The local pilot is operated from this workspace.",
                    "registration",
                    "No-limit Texas Hold’em",
                    now + 86400,
                    now + 90000,
                    1200,
                    6,
                    8,
                    50,
                    1.0,
                    None,
                    0,
                    None,
                ),
            )


def json_value(value):
    return json.loads(value) if value else None


def append_score_event(c, kind: str, round_id: str | None, team_id: str | None, payload: dict):
    """Append to the hash-chained scoring log. Corrections append; nothing mutates."""
    prev = c.execute("SELECT hash FROM score_events ORDER BY rowid DESC LIMIT 1").fetchone()
    prev_hash = prev["hash"] if prev else "GENESIS"
    event_id = uuid.uuid4().hex
    ts = time.time()
    body = json.dumps(
        {"id": event_id, "created_at": ts, "kind": kind, "round_id": round_id,
         "team_id": team_id, "payload": payload},
        sort_keys=True,
    )
    event_hash = hashlib.sha256((prev_hash + body).encode()).hexdigest()
    c.execute(
        "INSERT INTO score_events VALUES(?,?,?,?,?,?,?,?)",
        (event_id, ts, kind, round_id, team_id, json.dumps(payload), prev_hash, event_hash),
    )
    return event_hash


def verify_score_chain(c) -> bool:
    """Recompute the whole chain. Any tampering breaks it."""
    prev_hash = "GENESIS"
    for row in c.execute("SELECT * FROM score_events ORDER BY rowid"):
        body = json.dumps(
            {"id": row["id"], "created_at": row["created_at"], "kind": row["kind"],
             "round_id": row["round_id"], "team_id": row["team_id"], "payload": json.loads(row["payload"])},
            sort_keys=True,
        )
        expected = hashlib.sha256((prev_hash + body).encode()).hexdigest()
        if row["prev_hash"] != prev_hash or row["hash"] != expected:
            return False
        prev_hash = row["hash"]
    return True
