from __future__ import annotations

import json
import hashlib
import logging
import math
import random
import secrets
import threading
import time
import uuid
from . import db
from .baselines import make_baselines
from .engine import play_table
from .sandbox import ContainerBot, ModelContainerBot, SandboxDown, sandbox_status

log = logging.getLogger(__name__)
_stop = threading.Event()
_thread = None
LEASE_SECONDS = 120


def assert_lease(c, job):
    """Fence claimed work before publishing results; direct unit calls lack a lease."""
    owner = job.get('lease_owner')
    if owner and not c.execute("SELECT 1 FROM jobs WHERE id=? AND status='running' AND lease_owner=? AND lease_until>?",
                               (job['id'], owner, time.time())).fetchone():
        raise RuntimeError('Worker lease expired; results were not published.')


def ident():
    return uuid.uuid4().hex


def save_replay(title, result, source, owner_id=None, team_id=None):
    replay_id = ident()
    with db.connect(True) as c:
        c.execute(
            "INSERT INTO replays VALUES(?,?,?,?,?,?,?,?,?)",
            (
                replay_id,
                title,
                time.time(),
                result["hands"],
                source,
                owner_id,
                team_id,
                json.dumps(result["frames"]),
                json.dumps({k: v for k, v in result.items() if k != "frames"}),
            ),
        )
    return replay_id


def enqueue_round(event_id, manual=False):
    """Freeze accepted submission IDs atomically at round creation, never mid-round."""
    with db.connect(True) as c:
        event = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not event or event["exhibition"] or event["status"] == "completed":
            raise ValueError("This event cannot start a scored round.")
        existing = c.execute("SELECT * FROM rounds WHERE event_id=? ORDER BY number", (event_id,)).fetchall()
        if any(r["status"] in ("queued", "running") for r in existing):
            raise ValueError("A round is already queued or running.")
        failed = next((r for r in existing if r["status"] == "failed"), None)
        number = failed["number"] if failed else len(existing) + 1
        if number > event["round_count"]:
            raise ValueError("All rounds have been scored.")
        due = event["build_ends_at"] + (number - 1) * event["round_interval_seconds"]
        if not manual and time.time() < due:
            raise ValueError("The next round is not due yet.")
        track_row = c.execute('SELECT track FROM event_tracks WHERE event_id=?', (event_id,)).fetchone()
        track = track_row['track'] if track_row else 'classic'
        teams = c.execute(
            """SELECT t.id,t.name,s.id AS submission_id,MIN(u.college) AS college
          FROM entries e JOIN teams t ON t.id=e.team_id
          JOIN submissions s ON s.team_id=t.id AND s.active=1 AND s.status='accepted'
          JOIN users u ON u.team_id=t.id
          LEFT JOIN model_submissions m ON m.submission_id=s.id
          WHERE e.event_id=? AND ((?='model' AND m.submission_id IS NOT NULL)
                               OR (?='classic' AND m.submission_id IS NULL))
          GROUP BY t.id,s.id ORDER BY t.id""",
            (event_id, track, track),
        ).fetchall()
        if not teams:
            raise ValueError("No entered teams have an accepted bot yet.")
        round_id = failed["id"] if failed else ident()
        if failed:
            c.execute(
                "UPDATE rounds SET status='queued',starts_at=?,finished_at=NULL,entries_count=? WHERE id=?",
                (time.time(), len(teams), round_id),
            )
            c.execute("DELETE FROM round_scores WHERE round_id=?", (round_id,))
            c.execute("DELETE FROM round_metrics WHERE round_id=?", (round_id,))
        else:
            c.execute(
                "INSERT INTO rounds VALUES(?,?,?,?,?,?,?)",
                (round_id, event_id, number, "queued", time.time(), None, len(teams)),
            )
        payload = {
            "event": dict(event),
            "track": track,
            "teams": [dict(t) for t in teams],
            "round_id": round_id,
            "number": number,
            "seed": secrets.randbits(52),
        }
        job_id = ident()
        c.execute(
            "INSERT INTO jobs(id,kind,status,created_at,payload) VALUES(?,?,?,?,?)",
            (job_id, "round", "queued", time.time(), json.dumps(payload)),
        )
        c.execute("UPDATE events SET status='running' WHERE id=?", (event_id,))
        return job_id


def practice(job):
    payload = db.json_value(job["payload"])
    bots = make_baselines(8)
    sandbox_bot = None
    try:
        if payload.get("submission_id"):
            with db.connect() as c:
                submission = c.execute(
                    "SELECT * FROM submissions WHERE id=?", (payload["submission_id"],)
                ).fetchone()
                model = c.execute('SELECT 1 FROM model_submissions WHERE submission_id=?',
                                  (payload['submission_id'],)).fetchone()
            if not submission:
                raise ValueError("Submission no longer exists.")
            bot_class = ModelContainerBot if model else ContainerBot
            sandbox_bot = bot_class(db.DATA / 'bots' / (submission['id'] + ('.zip' if model else '.py')),
                                    submission['name'], decision_ms=50.0 if model else 1.0)
            bots[0] = sandbox_bot
        try:
            result = play_table(bots, payload["seed"], max_hands=payload["hands"], capture=True)
        except SandboxDown as exc:
            raise RuntimeError(f"Sandbox is not ready: {exc}") from exc
        scores = [
            {
                "name": bot.name,
                "points": round(result["points"][i], 4),
                "chips": result["chips"][i],
                "faults": result["faults"][i],
                "error": result["errors"][i],
            }
            for i, bot in enumerate(bots)
        ]
        replay_id = save_replay(
            "Practice · " + bots[0].name, result, "practice", job["owner_id"], job["team_id"]
        )
        return {"scores": scores, "replay_id": replay_id, "hands": result["hands"]}
    finally:
        if sandbox_bot:
            sandbox_bot.close()


def smoke_bot(bot):
    """Require at least one legal decision, even if a short table ends before its seat acts."""
    observation = {'hand': 1, 'street': 'preflop', 'seat': 0, 'button': 1,
                   'hole_cards': ['As', 'Kd'], 'board': [], 'pot': 30,
                   'stack': 2000, 'to_call': 20, 'min_raise': 40, 'max_raise': 2000,
                   'legal_actions': ['fold', 'call', 'raise'],
                   'players': [{'seat': 0, 'stack': 2000, 'bet': 0, 'folded': False},
                               {'seat': 1, 'stack': 1980, 'bet': 20, 'folded': False}],
                   'history': []}
    bot.reset()
    action = bot.act(observation)
    if action.get('action') not in observation['legal_actions']:
        raise ValueError('Sandbox smoke test returned an illegal action.')
    if action['action'] == 'raise' and (type(action.get('amount')) is not int or
                                        not 40 <= action['amount'] <= 2000):
        raise ValueError('Sandbox smoke test returned an illegal raise.')


def has_newer_submission(c, team_id, queued_at):
    # Finished GitHub jobs create their submission record after validation;
    # compare request times, not completion times, to handle out-of-order jobs.
    newer_job = c.execute("""SELECT 1 FROM jobs WHERE team_id=? AND kind IN
        ('github_validation','model_validation') AND created_at>? LIMIT 1""",
                          (team_id, queued_at)).fetchone()
    newer_manual = c.execute("""SELECT 1 FROM submissions s LEFT JOIN github_submissions g
        ON g.submission_id=s.id WHERE s.team_id=? AND s.created_at>?
        AND g.submission_id IS NULL LIMIT 1""", (team_id, queued_at)).fetchone()
    return bool(newer_job or newer_manual)


def validate_github_submission(job):
    """Fetch a frozen commit and test it without ever importing user code on the host."""
    from .github_integration import fetch_model_project, fetch_source

    payload = db.json_value(job['payload'])
    is_model = payload.get('track') == 'model'
    if is_model:
        raw, source = fetch_model_project(payload)
    else:
        source = fetch_source(payload)
        raw = source.encode('utf-8')
    submission_id = ident()
    path = db.DATA / 'bots' / (submission_id + ('.zip' if is_model else '.py'))
    path.write_bytes(raw)
    bot_class = ModelContainerBot if is_model else ContainerBot
    bot = bot_class(path, payload['full_name'], decision_ms=50.0 if is_model else 1.0)
    try:
        smoke_bot(bot)
        bots = make_baselines(8)
        bots[0] = bot
        result = play_table(bots, seed=1729, max_hands=1, capture=False)
        if result['faults'][0]:
            raise ValueError('Sandbox smoke test failed: ' + str(result['errors'][0] or 'bot fault'))
        with db.connect(True) as c:
            assert_lease(c, job)
            connection = c.execute('SELECT * FROM github_repositories WHERE id=? AND team_id=?',
                                   (payload['connection_id'], payload['team_id'])).fetchone()
            if not connection:
                raise ValueError('Repository was disconnected during validation.')
            newer = has_newer_submission(c, payload['team_id'], job['created_at'])
            active = connection['latest_job_id'] == job['id'] and not newer
            if active:
                c.execute('UPDATE submissions SET active=0 WHERE team_id=?', (payload['team_id'],))
            c.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)',
                      (submission_id, payload['team_id'], payload['full_name'], source,
                       hashlib.sha256(raw).hexdigest(), time.time(), 'accepted', None, int(active)))
            if is_model:
                c.execute('INSERT INTO model_submissions VALUES(?,?,?)',
                          (submission_id, hashlib.sha256(raw).hexdigest(), len(raw)))
            c.execute('INSERT INTO github_submissions VALUES(?,?,?,?,?,?)',
                      (submission_id, payload['repository_id'], payload['full_name'], payload['branch'],
                       payload['commit_sha'], payload['delivery_id']))
        return {'submission_id': submission_id, 'commit_sha': payload['commit_sha'], 'active': active}
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        bot.close()


def validate_model_submission(job):
    payload = db.json_value(job['payload'])
    sid = payload['submission_id']
    with db.connect() as c:
        submission = c.execute('SELECT * FROM submissions WHERE id=? AND status=?', (sid, 'validating')).fetchone()
    if not submission:
        raise ValueError('Model submission is no longer awaiting validation.')
    bot = ModelContainerBot(db.DATA / 'bots' / (sid + '.zip'), submission['name'], decision_ms=50.0)
    try:
        smoke_bot(bot)
        bots = make_baselines(8)
        bots[0] = bot
        result = play_table(bots, seed=1729, max_hands=1, capture=False)
        if result['faults'][0]:
            raise ValueError('Sandbox smoke test failed: ' + str(result['errors'][0] or 'bot fault'))
        with db.connect(True) as c:
            assert_lease(c, job)
            newer = has_newer_submission(c, submission['team_id'], job['created_at'])
            if not newer:
                c.execute('UPDATE submissions SET active=0 WHERE team_id=?', (submission['team_id'],))
            c.execute("UPDATE submissions SET status='accepted',active=? WHERE id=?",
                      (int(not newer), sid))
        return {'submission_id': sid, 'active': not bool(newer)}
    except Exception as exc:
        with db.connect(True) as c:
            if not job.get('lease_owner') or c.execute(
                "SELECT 1 FROM jobs WHERE id=? AND status='running' AND lease_owner=? AND lease_until>?",
                (job['id'], job['lease_owner'], time.time())).fetchone():
                c.execute("UPDATE submissions SET status='rejected',error=?,active=0 WHERE id=?", (str(exc)[:500], sid))
        raise
    finally:
        bot.close()


def score_round(job):
    payload = db.json_value(job["payload"])
    event, teams = payload["event"], payload["teams"]
    # Preflight: a disrupted round is retried, never scored with dead sandboxes.
    status = sandbox_status()
    if not status["available"] or not status["image"]:
        raise RuntimeError(
            f"Sandbox is not ready ({status['error']}). The round was not scored and can be retried."
        )
    totals = {t["id"]: {"points": 0.0, "points_sq": 0.0, "tables": 0, "faults": 0} for t in teams}
    rng = random.Random(payload["seed"])
    replay_ids = []
    table_index = 0
    with db.connect(True) as c:
        assert_lease(c, job)
        c.execute("UPDATE rounds SET status='running' WHERE id=?", (payload["round_id"],))
    for iteration in range(event["tables_per_round"]):
        if _stop.is_set():
            raise RuntimeError("The worker stopped; the operator can retry this round.")
        order = teams[:]
        rng.shuffle(order)
        for offset in range(0, len(order), 8):
            primary = order[offset : offset + 8]
            seats = [(t, True) for t in primary]
            while len(seats) < 8:
                seats.append((rng.choice(teams), False))
            rng.shuffle(seats)
            table_seed = rng.getrandbits(52)
            bot_class = ModelContainerBot if payload.get('track') == 'model' else ContainerBot
            extension = '.zip' if payload.get('track') == 'model' else '.py'
            bots = [
                bot_class(
                    db.DATA / "bots" / (t["submission_id"] + extension),
                    t["name"] if scoring else t["name"] + " (filler)",
                    event["decision_ms"],
                    image=event.get("sandbox_digest"),
                )
                for t, scoring in seats
            ]
            try:
                result = play_table(
                    bots,
                    table_seed,
                    max_hands=event["max_hands"],
                    capture=iteration == 0 and offset == 0,
                )
            finally:
                for bot in bots:
                    bot.close()
            with db.connect(True) as c:
                assert_lease(c, job)
                c.execute(
                    "INSERT INTO hand_logs VALUES(?,?,?,?,?,?)",
                    (ident(), payload["round_id"], table_index, table_seed, time.time(),
                     json.dumps(result["log"])),
                )
            table_index += 1
            for index, (team, scoring) in enumerate(seats):
                if scoring:
                    total = totals[team["id"]]
                    total["points"] += result["points"][index]
                    total["points_sq"] += result["points"][index] ** 2
                    total["tables"] += 1
                    total["faults"] += result["faults"][index]
            if result["frames"]:
                replay_ids.append(
                    save_replay(f"{event['title']} · Round {payload['number']}", result, "tournament")
                )
        with db.connect(True) as c:
            assert_lease(c, job)
            c.execute(
                "UPDATE jobs SET progress=? WHERE id=?",
                (int((iteration + 1) / event["tables_per_round"] * 95), job["id"]),
            )
    with db.connect(True) as c:
        assert_lease(c, job)
        for team in teams:
            total = totals[team["id"]]
            c.execute(
                "INSERT INTO round_scores VALUES(?,?,?,?,?,?,?,?)",
                (
                    payload["round_id"],
                    team["id"],
                    team["name"],
                    team["college"],
                    total["points"] / total["tables"],
                    total["faults"],
                    team["submission_id"],
                    0,
                ),
            )
            n = total['tables']
            sample_variance = max(0.0, (total['points_sq'] - total['points'] ** 2 / n) / (n - 1)) if n > 1 else None
            stderr = math.sqrt(sample_variance / n) if sample_variance is not None else None
            c.execute('INSERT INTO round_metrics VALUES(?,?,?,?)', (payload['round_id'], team['id'], n, stderr))
            db.append_score_event(
                c, "round-score", payload["round_id"], team["id"],
                {
                    "score": total["points"] / total["tables"],
                    "faults": total["faults"],
                    "submission_id": team["submission_id"],
                    "round_number": payload["number"],
                    "event_id": event["id"],
                },
            )
        c.execute(
            "UPDATE rounds SET status='completed',finished_at=? WHERE id=?",
            (time.time(), payload["round_id"]),
        )
        if payload["number"] == event["round_count"]:
            c.execute("UPDATE events SET status='completed' WHERE id=?", (event["id"],))
    return {"round_id": payload["round_id"], "replay_ids": replay_ids, "teams_scored": len(teams)}


def seed_exhibition():
    with db.connect() as c:
        if c.execute("SELECT 1 FROM events WHERE id='baseline-exhibition'").fetchone():
            return
    now = time.time()
    rounds = []
    replay = None
    # Calculate the complete exhibition before publishing any part of it.
    for number in range(1, 7):
        bots = make_baselines(8)
        totals = [0.0] * 8
        faults = [0] * 8
        for iteration in range(2):
            result = play_table(bots, 781000 + number * 100 + iteration, max_hands=12, capture=number == 1 and iteration == 0)
            totals = [a + b / 2 for a, b in zip(totals, result['points'])]
            faults = [a + b for a, b in zip(faults, result['faults'])]
            if result['frames']:
                replay = result
        rounds.append((number, [bot.name for bot in bots], totals, faults))
    with db.connect(True) as c:
        # Another process may have completed the same work while we computed.
        if c.execute("SELECT 1 FROM events WHERE id='baseline-exhibition'").fetchone():
            return
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            'baseline-exhibition', 'The opening table', 'Completed exhibition between eight built-in baseline strategies. These are reference bots, not student competitors.',
            'completed', 'No-limit Texas Hold’em', now - 7200, now - 3600, 1200, 6, 2, 12, 1.0, None, 1, None))
        if replay is not None:
            c.execute('INSERT INTO replays VALUES(?,?,?,?,?,?,?,?,?)', (
                ident(), 'The opening table · Baseline exhibition', now, replay['hands'], 'exhibition', None, None,
                json.dumps(replay['frames']), json.dumps({k: v for k, v in replay.items() if k != 'frames'})))
        for number, names, totals, faults in rounds:
            round_id = 'exhibition-' + str(number)
            c.execute('INSERT INTO rounds VALUES(?,?,?,?,?,?,?)', (round_id, 'baseline-exhibition', number, 'completed', now - 3600 + number * 60, now - 3600 + number * 60 + 1, 8))
            for index, name in enumerate(names):
                c.execute('INSERT INTO round_scores VALUES(?,?,?,?,?,?,?,?)', (round_id, f'baseline-{index}', name, 'Built-in baseline', totals[index], faults[index], None, 1))


def claim_job():
    """Atomically pull the next queued job. Safe across threads and processes."""
    with db.connect(True) as c:  # BEGIN IMMEDIATE: claim is exclusive
        expired = c.execute("SELECT * FROM jobs WHERE status='running' AND lease_until IS NOT NULL AND lease_until<?",
                            (time.time(),)).fetchall()
        for old in expired:
            c.execute("UPDATE jobs SET status='failed',error='Worker lease expired; retry the job.' WHERE id=? AND status='running'",
                      (old['id'],))
            payload = db.json_value(old['payload']) or {}
            if old['kind'] == 'round' and payload.get('round_id'):
                c.execute("UPDATE rounds SET status='failed' WHERE id=? AND status IN ('queued','running')", (payload['round_id'],))
            if old['kind'] == 'model_validation' and payload.get('submission_id'):
                c.execute("UPDATE submissions SET status='rejected',error='Worker lease expired; resubmit.' WHERE id=? AND status='validating'",
                          (payload['submission_id'],))
        row = c.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        owner = ident()
        c.execute("UPDATE jobs SET status='running',progress=5,lease_owner=?,lease_until=? WHERE id=? AND status='queued'",
                  (owner, time.time() + LEASE_SECONDS, row['id']))
        claimed = dict(row)
        claimed['lease_owner'] = owner
        return claimed


def finish_job(job_id, kind, result=None, error=None, lease_owner=None):
    with db.connect(True) as c:
        where = "id=? AND status='running' AND " + ("lease_owner=? AND lease_until>?" if lease_owner else "lease_owner IS NULL")
        fence = (job_id, lease_owner, time.time()) if lease_owner else (job_id,)
        if error is None:
            c.execute("UPDATE jobs SET status='completed',progress=100,result=? WHERE " + where,
                      (json.dumps(result), *fence))
        else:
            changed = c.execute("UPDATE jobs SET status='failed',error=? WHERE " + where,
                                (str(error)[:500], *fence)).rowcount
            if changed and kind == "round":
                try:
                    round_id = db.json_value(
                        c.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()["payload"]
                    )["round_id"]
                    c.execute("UPDATE rounds SET status='failed' WHERE id=?", (round_id,))
                except (TypeError, KeyError, db.sqlite3.Error):
                    log.exception("Could not fail round for job %s", job_id)


def _run_claimed(job):
    finished = threading.Event()
    def heartbeat():
        while not finished.wait(10):
            with db.connect(True) as c:
                changed = c.execute("UPDATE jobs SET lease_until=? WHERE id=? AND status='running' AND lease_owner=? AND lease_until>?",
                                    (time.time() + LEASE_SECONDS, job['id'], job['lease_owner'], time.time())).rowcount
            if not changed:
                return
    thread = threading.Thread(target=heartbeat, name='arena-job-heartbeat', daemon=True)
    thread.start()
    try:
        handlers = {'practice': practice, 'round': score_round, 'github_validation': validate_github_submission,
                    'model_validation': validate_model_submission}
        if job['kind'] not in handlers:
            raise ValueError('Unknown job kind.')
        result = handlers[job['kind']](job)
        finish_job(job['id'], job['kind'], result=result, lease_owner=job['lease_owner'])
    except Exception as exc:
        finish_job(job['id'], job['kind'], error=exc, lease_owner=job['lease_owner'])
        raise
    finally:
        finished.set()
        thread.join(timeout=2)


def execute_loop(index: int):
    """Worker thread: claim and run jobs until stopped."""
    name = f"arena-exec-{index}"
    while not _stop.is_set():
        try:
            job = claim_job()
            if not job:
                _stop.wait(0.4)
                continue
            log.info("%s claimed job %s (%s)", name, job["id"], job["kind"])
            try:
                _run_claimed(job)
            except Exception as exc:
                log.exception("Job %s failed", job["id"])
        except Exception:
            log.exception("%s crashed on the loop itself", name)
            _stop.wait(2)


def coordinator():
    """Scheduling only: event transitions and due-round enqueueing."""
    tick = 0
    while not _stop.is_set():
        try:
            if tick % 20 == 0:
                with db.connect(True) as c:
                    now = time.time()
                    c.execute(
                        "UPDATE events SET status='building' WHERE status='registration' AND build_starts_at<=?",
                        (now,),
                    )
                    due = c.execute(
                        "SELECT id FROM events WHERE status IN ('building','running') AND build_ends_at<=?",
                        (now,),
                    ).fetchall()
                for event in due:
                    with db.connect() as c:
                        failed = c.execute(
                            "SELECT 1 FROM rounds WHERE event_id=? AND status='failed'", (event["id"],)
                        ).fetchone()
                    if not failed:
                        try:
                            enqueue_round(event["id"])
                        except ValueError:
                            pass
            tick += 1
            _stop.wait(0.5)
        except Exception:
            log.exception("Worker coordinator failed")
            _stop.wait(2)


def start(workers: int | None = None):
    global _threads
    if _threads:
        return
    _stop.clear()
    import os

    if workers is None:
        workers = max(1, min(16, int(os.environ.get("ARENA_WORKERS", "1"))))
    _threads = [threading.Thread(target=coordinator, name="arena-coordinator", daemon=True)]
    for index in range(workers):
        _threads.append(threading.Thread(target=execute_loop, args=(index,), name=f"arena-exec-{index}", daemon=True))
    for thread in _threads:
        thread.start()
    log.info("Worker started: %d execution slots", workers)


def stop():
    global _threads
    _stop.set()
    for thread in _threads or []:
        thread.join(timeout=5)
    _threads = []


def main():
    """Standalone worker entry: python -m arena.worker [--workers N] [--once]"""
    import argparse
    import signal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description="Campus Arena job worker")
    parser.add_argument("--workers", type=int, default=None, help="execution slots (default ARENA_WORKERS or 1)")
    parser.add_argument("--once", action="store_true", help="run a single claim+execute cycle and exit")
    args = parser.parse_args()

    db.initialize()
    seed_exhibition()

    if args.once:
        job = claim_job()
        if not job:
            log.info("No queued jobs.")
            return
        log.info("Running job %s (%s)", job["id"], job["kind"])
        try:
            _run_claimed(job)
            log.info("Job %s completed", job["id"])
        except Exception as exc:
            log.exception("Job %s failed", job["id"])
            raise SystemExit(1)
        return

    start(args.workers)
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    log.info("Worker running. Ctrl+C to stop.")
    while not _stop.is_set():
        _stop.wait(1)
    stop()
    log.info("Worker stopped.")


if __name__ == "__main__":
    main()
