from __future__ import annotations

import ast
import hashlib
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from . import db, mailer, worker
from .sandbox import sandbox_status, image_id
from .security import (
    COOKIE,
    current_user,
    digest_token,
    hash_password,
    new_session,
    rate_limit,
    require_admin,
    require_team,
    require_user,
    verify_password,
)
import secrets

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ORIGINS = set(
    os.environ.get(
        "ARENA_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8001,http://localhost:8001",
    ).split(",")
)
COOLDOWN = int(os.environ.get("ARENA_SUBMISSION_COOLDOWN", "300"))
SECURE_COOKIE = os.environ.get("ARENA_SECURE_COOKIE") == "1"


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


@asynccontextmanager
async def lifespan(app):
    db.initialize()
    # Production runs standalone workers (python -m arena.worker) with
    # ARENA_EMBEDDED_WORKER=0; local development keeps the in-process one.
    embedded = os.environ.get("ARENA_EMBEDDED_WORKER", "1") == "1"
    if os.environ.get("ARENA_TESTING") != "1":
        worker.seed_exhibition()
        if embedded:
            worker.start()
    yield
    if os.environ.get("ARENA_TESTING") != "1" and embedded:
        worker.stop()


app = FastAPI(title="Campus Arena", version="0.1.0", lifespan=lifespan)
from .github_integration import router as github_router
app.include_router(github_router)
from .model_projects import router as model_router
app.include_router(model_router)


@app.middleware("http")
async def boundaries(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "This origin is not allowed."}, status_code=403)
        size, chunks = 0, []
        async for chunk in request.stream():
            size += len(chunk)
            limit = 16_777_216 if request.url.path == '/api/models/submissions' else 130000
            if size > limit:
                return JSONResponse(
                    {"detail": "Request is too large for this submission type."},
                    status_code=413,
                )
            chunks.append(chunk)
        request._body = b"".join(chunks)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


class Registration(BaseModel):
    name: str = Field(min_length=2, max_length=70)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    college: str = Field(min_length=2, max_length=120)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("name", "college")
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Enter at least two characters.")
        return value.strip()


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=50, pattern=r"^\S(?:.*\S)?$")


class TeamJoin(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class Submission(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    source: str = Field(min_length=20, max_length=102400)


class Practice(BaseModel):
    submission_id: str | None = Field(default=None, max_length=64)
    hands: int = Field(default=20, ge=1, le=30)


class SponsorInquiry(BaseModel):
    name: str = Field(min_length=2, max_length=70)
    email: str = Field(max_length=254)
    company: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=10, max_length=4000)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        return Registration.email_format(value)


class Verify(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class Forgot(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        return Registration.email_format(value)


class Reset(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class EventCreate(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    description: str = Field(min_length=10, max_length=1000)
    build_starts_at: float = Field(default_factory=lambda: time.time() + 3600)
    build_minutes: int = Field(default=60, ge=1, le=1440)
    round_interval_seconds: int = Field(default=1200, ge=10, le=86400)
    round_count: int = Field(default=6, ge=1, le=6)
    tables_per_round: int = Field(default=8, ge=1, le=10000)
    max_hands: int = Field(default=50, ge=1, le=200)
    decision_ms: float = Field(default=1, ge=0.1, le=100)
    sponsor_name: str | None = Field(default=None, max_length=100)
    track: str = Field(default='classic', pattern=r'^(classic|model)$')


def client_key(request):
    return request.client.host if request.client else "local"


def team_info(team_id):
    if not team_id:
        return None
    with db.connect() as c:
        row = c.execute("SELECT id,name,join_code FROM teams WHERE id=?", (team_id,)).fetchone()
        if not row:
            return None
        team = dict(row)
        team["members"] = [
            dict(r)
            for r in c.execute("SELECT id,name FROM users WHERE team_id=? ORDER BY created_at", (team_id,))
        ]
        return team


def set_cookie(response, token):
    response.set_cookie(
        COOKIE, token, httponly=True, secure=SECURE_COOKIE, samesite="lax", max_age=604800, path="/"
    )


@app.get("/api/health")
def health():
    status = sandbox_status()
    return {
        "status": "ok",
        "sandbox_available": status.get("available", status.get("sandbox_available", False)),
        "sandbox_image": status.get("image", status.get("sandbox_image", False)),
    }


@app.post("/api/auth/register", status_code=201)
def register(body: Registration, request: Request, response: Response):
    rate_limit("signup:" + client_key(request), 20, 3600)
    user_id = worker.ident()
    encoded = hash_password(body.password)
    try:
        with db.connect(True) as c:
            c.execute(
                "INSERT INTO users VALUES(?,?,?,?,?,?,?,?,0,NULL,NULL,NULL,NULL)",
                (user_id, body.name, body.email, encoded, body.college, "student", None, time.time()),
            )
            token = new_session(c, user_id)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists.") from None
    verify_token = secrets.token_urlsafe(32)
    with db.connect(True) as c:
        c.execute(
            "UPDATE users SET verify_token=?, verify_expires=? WHERE id=?",
            (digest_token(verify_token), time.time() + mailer.VERIFY_TTL, user_id),
        )
    try:
        transport = mailer.verification_email(body.email, verify_token)
    except Exception:
        log = logging.getLogger("arena.mail")
        log.exception("Verification email failed for %s; the user can resend", body.email)
        transport = "failed"
    set_cookie(response, token)
    return {
        "user": {
            "id": user_id,
            "name": body.name,
            "email": body.email,
            "college": body.college,
            "role": "student",
            "team_id": None,
            "email_verified": False,
        },
        "verification": transport,
    }


@app.post("/api/auth/login")
def login(body: Login, request: Request, response: Response):
    rate_limit("login:" + client_key(request), 30, 600)
    with db.connect() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (body.email.strip().lower(),)).fetchone()
    if not row or not verify_password(body.password, row["password"]):
        raise HTTPException(401, "Email or password is incorrect.")
    user = dict(row)
    del user["password"]
    with db.connect(True) as c:
        old = request.cookies.get(COOKIE)
        if old:
            c.execute("DELETE FROM sessions WHERE token=?", (digest_token(old),))
        token = new_session(c, user["id"])
    set_cookie(response, token)
    return {"user": user}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with db.connect(True) as c:
            c.execute("DELETE FROM sessions WHERE token=?", (digest_token(token),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.post("/api/auth/verify")
def verify_email(body: Verify):
    now = time.time()
    with db.connect(True) as c:
        row = c.execute(
            "SELECT id FROM users WHERE verify_token=? AND verify_expires>?",
            (digest_token(body.token), now),
        ).fetchone()
        if not row:
            raise HTTPException(400, "This verification link is invalid or expired.")
        c.execute(
            "UPDATE users SET email_verified=1, verify_token=NULL, verify_expires=NULL WHERE id=?",
            (row["id"],),
        )
    return {"ok": True}


@app.post("/api/auth/verify/resend")
def resend_verification(request: Request):
    user = require_user(request)
    rate_limit("verify-resend:" + user["id"], 3, 3600)
    if user["email_verified"]:
        return {"ok": True, "already_verified": True}
    token = secrets.token_urlsafe(32)
    with db.connect(True) as c:
        c.execute(
            "UPDATE users SET verify_token=?, verify_expires=? WHERE id=?",
            (digest_token(token), time.time() + mailer.VERIFY_TTL, user["id"]),
        )
    try:
        mailer.verification_email(user["email"], token)
    except Exception:
        raise HTTPException(503, "Could not send the email right now. Try again shortly.") from None
    return {"ok": True}


@app.post("/api/auth/forgot")
def forgot_password(body: Forgot, request: Request):
    # Always the same answer: never reveal whether an email is registered.
    rate_limit("forgot:" + client_key(request), 10, 3600)
    with db.connect() as c:
        row = c.execute("SELECT id FROM users WHERE email=?", (body.email,)).fetchone()
    if row:
        token = secrets.token_urlsafe(32)
        with db.connect(True) as c:
            c.execute(
                "UPDATE users SET reset_token=?, reset_expires=? WHERE id=?",
                (digest_token(token), time.time() + mailer.RESET_TTL, row["id"]),
            )
        try:
            mailer.reset_email(body.email, token)
        except Exception:
            logging.getLogger("arena.mail").exception("Reset email failed for %s", body.email)
    return {"ok": True}


@app.post("/api/auth/reset")
def reset_password(body: Reset):
    now = time.time()
    with db.connect(True) as c:
        row = c.execute(
            "SELECT id FROM users WHERE reset_token=? AND reset_expires>?",
            (digest_token(body.token), now),
        ).fetchone()
        if not row:
            raise HTTPException(400, "This reset link is invalid or expired.")
        c.execute(
            "UPDATE users SET password=?, reset_token=NULL, reset_expires=NULL, "
            "email_verified=1, verify_token=NULL, verify_expires=NULL WHERE id=?",
            (hash_password(body.password), row["id"]),
        )
        c.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    user = current_user(request)
    return {"user": user, "team": team_info(user["team_id"]) if user else None}


@app.post("/api/team", status_code=201)
def create_team(body: TeamCreate, request: Request):
    user = require_user(request)
    team_id = worker.ident()
    with db.connect(True) as c:
        current = c.execute("SELECT team_id FROM users WHERE id=?", (user["id"],)).fetchone()
        if current["team_id"]:
            raise HTTPException(409, "You already belong to a team.")
        try:
            c.execute(
                "INSERT INTO teams VALUES(?,?,?,?)",
                (team_id, body.name, secrets.token_hex(5).upper(), time.time()),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That team name is already in use.") from None
        c.execute("UPDATE users SET team_id=? WHERE id=?", (team_id, user["id"]))
    return team_info(team_id)


@app.post("/api/team/join")
def join_team(body: TeamJoin, request: Request):
    user = require_user(request)
    rate_limit("team-join:" + user["id"], 20, 3600)
    with db.connect(True) as c:
        current = c.execute("SELECT team_id FROM users WHERE id=?", (user["id"],)).fetchone()
        if current["team_id"]:
            raise HTTPException(409, "You already belong to a team.")
        team = c.execute("SELECT * FROM teams WHERE join_code=?", (body.code.strip().upper(),)).fetchone()
        if not team:
            raise HTTPException(404, "No team matches that invitation code.")
        members = c.execute("SELECT COUNT(*) FROM users WHERE team_id=?", (team["id"],)).fetchone()[0]
        if members >= 2:
            raise HTTPException(409, "Teams have at most two members.")
        c.execute("UPDATE users SET team_id=? WHERE id=?", (team["id"], user["id"]))
    return team_info(team["id"])


def event_info(row, user=None):
    event = dict(row)
    with db.connect() as c:
        track_row = c.execute('SELECT track FROM event_tracks WHERE event_id=?', (row['id'],)).fetchone()
        event['track'] = track_row['track'] if track_row else 'classic'
        event["entry_count"] = (
            8
            if event["exhibition"]
            else c.execute("SELECT COUNT(*) FROM entries WHERE event_id=?", (event["id"],)).fetchone()[0]
        )
        event["joined"] = bool(
            user
            and user["team_id"]
            and c.execute(
                "SELECT 1 FROM entries WHERE event_id=? AND team_id=?", (event["id"], user["team_id"])
            ).fetchone()
        )
    event["exhibition"] = bool(event["exhibition"])
    event["build_starts_at"] = iso(event["build_starts_at"])
    event["build_ends_at"] = iso(event["build_ends_at"])
    return event


def leaderboard(event_id=None):
    with db.connect() as c:
        rows = c.execute(
            """SELECT rs.*,r.number,r.event_id FROM round_scores rs JOIN rounds r ON r.id=rs.round_id
            WHERE r.status='completed' """
            + ("AND r.event_id=? " if event_id else "")
            + "ORDER BY r.event_id,r.number",
            (event_id,) if event_id else (),
        ).fetchall()
    totals = {}
    for r in rows:
        if r["team_id"] not in totals:
            totals[r["team_id"]] = {
                "team_id": r["team_id"],
                "team_name": r["team_name"],
                "college": r["college"],
                "total_score": 0.0,
                "round_scores": [0.0] * 6,
                "is_baseline": bool(r["is_baseline"]),
                "_events": set(),
                "faults": 0,
            }
        score = totals[r["team_id"]]
        score["total_score"] += r["score"] * r["number"]
        score["round_scores"][r["number"] - 1] += r["score"]
        score["faults"] += r["faults"]
        score["_events"].add(r["event_id"])
    ordered = sorted(totals.values(), key=lambda t: (-t["total_score"], t["team_name"]))
    previous, rank = None, 0
    for index, t in enumerate(ordered):
        if previous is None or abs(t["total_score"] - previous) > 1e-9:
            rank = index + 1
        previous = t["total_score"]
        t["rank"] = rank
        t["total_score"] = round(t["total_score"], 4)
        t["round_scores"] = [round(v, 4) for v in t["round_scores"]]
        t["events_played"] = len(t.pop("_events"))
    return ordered


@app.get("/api/events")
def events(request: Request):
    user = current_user(request)
    with db.connect() as c:
        rows = c.execute("SELECT * FROM events ORDER BY exhibition,build_starts_at").fetchall()
    return {"events": [event_info(row, user) for row in rows]}


@app.get("/api/events/{event_id}")
def event_detail(event_id: str, request: Request):
    with db.connect() as c:
        row = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Event not found.")
        rounds = [
            dict(r) for r in c.execute("SELECT * FROM rounds WHERE event_id=? ORDER BY number", (event_id,))
        ]
        entries = [
            dict(r)
            for r in c.execute(
                "SELECT t.id AS team_id,t.name AS team_name FROM entries e JOIN teams t ON t.id=e.team_id WHERE e.event_id=?",
                (event_id,),
            )
        ]
    for r in rounds:
        r["starts_at"], r["finished_at"] = iso(r["starts_at"]), iso(r["finished_at"])
    event = event_info(row, current_user(request))
    return {
        "event": event,
        "rounds": rounds,
        "leaderboard": leaderboard(event_id),
        "entries": entries,
        "rules": {
            "language": "Python 3.12 / standard library",
            "source_limit_bytes": 102400,
            "project_limit_bytes": 16777216 if event['track'] == 'model' else None,
            "track": event['track'],
            "network_access": False,
            "decision_ms": row["decision_ms"],
            "submission_cooldown_seconds": COOLDOWN,
            "initial_chips": 2000,
            "blinds": "10/20, doubling every 25 hands",
            "payouts": [8, 5, 3, 2, 1, 0, 0, 0],
            "scoring": "Mean points per table; round weights 1 through 6. ICM at hand cap. Non-scoring copies fill empty seats.",
            "tie_policy": "Equal scores share a rank. No cash prizes are configured for the local pilot.",
            "sandbox_digest": row["sandbox_digest"],
        },
    }


@app.post("/api/events/{event_id}/join")
def enter_event(event_id: str, request: Request):
    user = require_team(request)
    with db.connect(True) as c:
        row = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Event not found.")
        if (
            row["exhibition"]
            or row["status"] not in ("registration", "building")
            or time.time() >= row["build_ends_at"]
        ):
            raise HTTPException(409, "Registration for this event is closed.")
        if not c.execute(
            "SELECT 1 FROM entries WHERE event_id=? AND team_id=?", (event_id, user["team_id"])
        ).fetchone():
            if c.execute("SELECT COUNT(*) FROM entries WHERE event_id=?", (event_id,)).fetchone()[0] >= 64:
                raise HTTPException(409, "This event has reached its 64-team capacity.")
            c.execute("INSERT INTO entries VALUES(?,?,?)", (event_id, user["team_id"], time.time()))
    return {"ok": True}


@app.get('/api/events/{event_id}/metrics')
def event_metrics(event_id: str):
    with db.connect() as c:
        if not c.execute('SELECT 1 FROM events WHERE id=?', (event_id,)).fetchone():
            raise HTTPException(404, 'Event not found.')
        rows = c.execute("""SELECT r.number AS round_number,s.team_id,s.team_name,s.score,s.faults,
                            m.tables_played,m.points_std_error FROM round_scores s
                            JOIN rounds r ON r.id=s.round_id
                            JOIN round_metrics m ON m.round_id=s.round_id AND m.team_id=s.team_id
                            WHERE r.event_id=? AND r.status='completed' ORDER BY r.number,s.team_name""",
                         (event_id,)).fetchall()
    return {'metrics': [dict(row) for row in rows],
            'note': 'Standard error is across played tables; correlated seats and opponents can limit its interpretation.'}


@app.get("/api/starter")
def starter():
    return {
        "source": (ROOT / "starter-kit/agent.py").read_text(),
        "interface": "class Agent:\n    def act(self, observation: dict) -> dict: ...",
        "guide": (ROOT / "starter-kit/README.md").read_text(),
    }


@app.get("/api/starter/download")
def starter_download():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in ("agent.py", "simulate.py", "icm.py", "README.md"):
            bundle.write(ROOT / "starter-kit" / name, name)
    data.seek(0)
    return StreamingResponse(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="campus-arena-starter.zip"'},
    )


def submission_info(row):
    value = dict(row)
    value["created_at"] = iso(value["created_at"])
    value["active"] = bool(value["active"])
    return value


@app.get("/api/submissions")
def submissions(request: Request):
    user = require_user(request)
    with db.connect() as c:
        rows = c.execute(
            """SELECT s.*,g.full_name AS github_repository,g.branch AS github_branch,
                      g.commit_sha AS github_commit,
                      CASE WHEN m.submission_id IS NULL THEN 'classic' ELSE 'model' END AS track
               FROM submissions s
               LEFT JOIN github_submissions g ON g.submission_id=s.id
               LEFT JOIN model_submissions m ON m.submission_id=s.id
               WHERE s.team_id=? ORDER BY s.created_at DESC LIMIT 50""", (user["team_id"],)
        ).fetchall()
        latest = c.execute(
            "SELECT created_at FROM submissions WHERE team_id=? ORDER BY created_at DESC LIMIT 1",
            (user["team_id"],),
        ).fetchone()
    cooldown_remaining = (
        max(0, int(COOLDOWN - (time.time() - latest["created_at"]))) if latest else 0
    )
    return {"submissions": [submission_info(r) for r in rows], "cooldown_remaining": cooldown_remaining}


@app.post("/api/submissions", status_code=201)
def submit(body: Submission, request: Request):
    user = require_team(request)
    if not user["email_verified"]:
        raise HTTPException(
            403,
            "Verify your email before submitting bots. Use the link we emailed you, or resend it from the banner.",
        )
    source = body.source.replace("\r\n", "\n")
    if len(source.encode("utf-8")) > 102400:
        raise HTTPException(413, "Python source must be at most 100 KiB.")
    try:
        tree = ast.parse(source)
        cls = next(
            (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent"), None
        )
        if cls is None or not any(
            isinstance(node, ast.FunctionDef) and node.name == "act" for node in cls.body
        ):
            raise ValueError("Include class Agent with an act(self, observation) method.")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise HTTPException(422, f"Invalid bot source: {exc}") from None
    sid, now = worker.ident(), time.time()
    path = db.DATA / "bots" / (sid + ".py")
    with db.connect(True) as c:
        previous = c.execute(
            "SELECT created_at FROM submissions WHERE team_id=? ORDER BY created_at DESC LIMIT 1",
            (user["team_id"],),
        ).fetchone()
        if previous and now - previous["created_at"] < COOLDOWN:
            remaining = max(1, int(COOLDOWN - (now - previous["created_at"])))
            raise HTTPException(
                429,
                f"Wait {remaining} seconds before the next submission. Keep editing your draft meanwhile.",
                headers={"Retry-After": str(remaining)},
            )
        path.write_text(source, encoding="utf-8")
        c.execute("UPDATE submissions SET active=0 WHERE team_id=?", (user["team_id"],))
        c.execute(
            "INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                sid,
                user["team_id"],
                body.name.strip(),
                source,
                hashlib.sha256(source.encode()).hexdigest(),
                now,
                "accepted",
                None,
                1,
            ),
        )
        result = c.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    return submission_info(result)


@app.post("/api/practice", status_code=202)
def practice(body: Practice, request: Request):
    user = current_user(request)
    if body.submission_id:
        user = require_team(request)
        with db.connect() as c:
            found = c.execute(
                "SELECT 1 FROM submissions WHERE id=? AND team_id=? AND status='accepted'", (body.submission_id, user["team_id"])
            ).fetchone()
        if not found:
            raise HTTPException(404, "Submission not found for your team.")
        status = health()
        if not status["sandbox_available"] or not status["sandbox_image"]:
            raise HTTPException(
                503,
                "The bot sandbox is not ready. Start Docker and build the sandbox image, or try the baseline demo.",
            )
    rate_limit("practice:" + (user["id"] if user else client_key(request)), 20, 3600)
    job_id = worker.ident()
    with db.connect(True) as c:
        if c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('running','queued')").fetchone()[0] >= 20:
            raise HTTPException(429, "The practice queue is full. Try again after a table finishes.")
        if (
            user
            and c.execute(
                "SELECT 1 FROM jobs WHERE owner_id=? AND status IN ('running','queued')", (user["id"],)
            ).fetchone()
        ):
            raise HTTPException(409, "Your current practice run is still in progress.")
        payload = {"submission_id": body.submission_id, "hands": body.hands, "seed": secrets.randbits(52)}
        c.execute(
            "INSERT INTO jobs(id,kind,status,team_id,owner_id,created_at,payload) VALUES(?,?,?,?,?,?,?)",
            (
                job_id,
                "practice",
                "queued",
                user["team_id"] if user else None,
                user["id"] if user else None,
                time.time(),
                json.dumps(payload),
            ),
        )
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    with db.connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Run not found.")
    user = current_user(request)
    if row['team_id'] and not row['owner_id'] and (not user or user['team_id'] != row['team_id']):
        raise HTTPException(404, "Run not found.")
    if row["owner_id"] and (
        not user
        or (user["id"] != row["owner_id"] and (not row["team_id"] or user["team_id"] != row["team_id"]))
    ):
        raise HTTPException(404, "Run not found.")
    return {
        "id": row["id"],
        "status": row["status"],
        "progress": row["progress"],
        "error": row["error"],
        "result": db.json_value(row["result"]),
    }


@app.get("/api/replays")
def replays(request: Request):
    user = current_user(request)
    with db.connect() as c:
        rows = c.execute(
            """SELECT id,title,created_at,hand_count,source FROM replays
          WHERE owner_id IS NULL OR owner_id=? OR (team_id IS NOT NULL AND team_id=?) ORDER BY created_at DESC LIMIT 100""",
            (user["id"] if user else "", user["team_id"] if user else ""),
        ).fetchall()
    return {"replays": [{**dict(r), "created_at": iso(r["created_at"])} for r in rows]}


@app.get("/api/replays/{replay_id}")
def replay_detail(replay_id: str, request: Request):
    with db.connect() as c:
        row = c.execute("SELECT * FROM replays WHERE id=?", (replay_id,)).fetchone()
    user = current_user(request)
    if not row or (
        row["owner_id"]
        and (
            not user
            or (row["owner_id"] != user["id"] and (not row["team_id"] or row["team_id"] != user["team_id"]))
        )
    ):
        raise HTTPException(404, "Replay not found.")
    return {
        "id": row["id"],
        "title": row["title"],
        "frames": db.json_value(row["frames"]),
        "summary": db.json_value(row["summary"]),
    }


@app.get("/api/leaderboard")
def global_leaderboard():
    return {"leaderboard": leaderboard()}


@app.get("/api/profile")
def profile(request: Request):
    user = require_user(request)
    with db.connect() as c:
        submitted = c.execute(
            "SELECT COUNT(*) FROM submissions WHERE team_id=?", (user["team_id"],)
        ).fetchone()[0]
        runs = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE owner_id=? AND kind='practice' AND status='completed'",
            (user["id"],),
        ).fetchone()[0]
        events = c.execute("SELECT COUNT(*) FROM entries WHERE team_id=?", (user["team_id"],)).fetchone()[0]
        recent = c.execute(
            "SELECT * FROM submissions WHERE team_id=? ORDER BY created_at DESC LIMIT 5", (user["team_id"],)
        ).fetchall()
    return {
        "user": user,
        "team": team_info(user["team_id"]),
        "stats": {"submissions": submitted, "practice_runs": runs, "events": events},
        "recent_submissions": [submission_info(s) for s in recent],
    }


@app.post("/api/sponsor-inquiries", status_code=201)
def inquiry(body: SponsorInquiry, request: Request):
    rate_limit("sponsor:" + client_key(request), 5, 3600)
    with db.connect(True) as c:
        c.execute(
            "INSERT INTO sponsor_inquiries VALUES(?,?,?,?,?,?)",
            (
                worker.ident(),
                body.name.strip(),
                body.email,
                body.company.strip(),
                body.message.strip(),
                time.time(),
            ),
        )
    return {"ok": True}


@app.post("/api/admin/events", status_code=201)
def create_event(body: EventCreate, request: Request):
    require_admin(request)
    event_id = worker.ident()
    digest = image_id()
    with db.connect(True) as c:
        c.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                body.title,
                body.description,
                "registration",
                "No-limit Texas Hold’em",
                body.build_starts_at,
                body.build_starts_at + body.build_minutes * 60,
                body.round_interval_seconds,
                body.round_count,
                body.tables_per_round,
                body.max_hands,
                50.0 if body.track == 'model' and 'decision_ms' not in body.model_fields_set else body.decision_ms,
                body.sponsor_name,
                0,
                digest,
            ),
        )
        c.execute('INSERT INTO event_tracks VALUES(?,?)', (event_id, body.track))
    return {"id": event_id, "sandbox_digest": digest}


@app.post("/api/admin/events/{event_id}/start")
def start_build(event_id: str, request: Request):
    require_admin(request)
    with db.connect(True) as c:
        event = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not event or event["status"] != "registration" or event["exhibition"]:
            raise HTTPException(409, "Only an upcoming event can start its build phase.")
        duration = event["build_ends_at"] - event["build_starts_at"]
        c.execute(
            "UPDATE events SET status='building',build_starts_at=?,build_ends_at=? WHERE id=?",
            (time.time(), time.time() + duration, event_id),
        )
    return {"ok": True}


@app.post("/api/admin/events/{event_id}/round", status_code=202)
def start_round(event_id: str, request: Request):
    require_admin(request)
    if not health()["sandbox_image"]:
        raise HTTPException(503, "Build the sandbox image before running a scored round.")
    try:
        return {"job_id": worker.enqueue_round(event_id, manual=True)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get("/api/admin/inquiries")
def inquiries(request: Request):
    require_admin(request)
    with db.connect() as c:
        return {
            "inquiries": [
                dict(r) for r in c.execute("SELECT * FROM sponsor_inquiries ORDER BY created_at DESC")
            ]
        }


class Correction(BaseModel):
    round_id: str = Field(max_length=64)
    team_id: str = Field(max_length=64)
    score: float
    reason: str = Field(min_length=4, max_length=1000)


@app.get("/api/admin/hand-logs")
def hand_log_index(request: Request, round_id: str | None = None):
    require_admin(request)
    with db.connect() as c:
        if round_id:
            logs = c.execute(
                "SELECT id,table_index,seed,created_at FROM hand_logs WHERE round_id=? ORDER BY table_index",
                (round_id,),
            ).fetchall()
        else:
            logs = c.execute(
                "SELECT id,table_index,seed,created_at FROM hand_logs ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
    return {"logs": [dict(r) for r in logs]}


@app.get("/api/admin/hand-logs/{log_id}")
def hand_log_detail(log_id: str, request: Request):
    require_admin(request)
    with db.connect() as c:
        row = c.execute("SELECT * FROM hand_logs WHERE id=?", (log_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Hand log not found.")
    detail = dict(row)
    detail["log"] = db.json_value(detail["log"])
    return detail


@app.get("/api/admin/score-events")
def score_event_index(request: Request, round_id: str | None = None):
    require_admin(request)
    with db.connect() as c:
        if round_id:
            rows = c.execute(
                "SELECT * FROM score_events WHERE round_id=? ORDER BY rowid", (round_id,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM score_events ORDER BY rowid").fetchall()
        chain_valid = db.verify_score_chain(c)
    events = []
    for row in rows:
        item = dict(row)
        item["payload"] = db.json_value(item["payload"])
        events.append(item)
    return {"events": events, "chain_valid": chain_valid}


@app.post("/api/admin/scores/correct")
def correct_score(body: Correction, request: Request):
    require_admin(request)
    with db.connect(True) as c:
        row = c.execute(
            "SELECT * FROM round_scores WHERE round_id=? AND team_id=?",
            (body.round_id, body.team_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "No scored result for that round and team.")
        c.execute(
            "UPDATE round_scores SET score=? WHERE round_id=? AND team_id=?",
            (body.score, body.round_id, body.team_id),
        )
        db.append_score_event(
            c, "correction", body.round_id, body.team_id,
            {"old_score": row["score"], "new_score": body.score, "reason": body.reason},
        )
        chain_valid = db.verify_score_chain(c)
    return {"ok": True, "chain_valid": chain_valid}


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found.")
    directory = (ROOT.parent / "frontend" / "dist").resolve()
    candidate = (directory / path).resolve()
    if candidate.is_relative_to(directory) and candidate.is_file():
        return FileResponse(candidate)
    if (directory / "index.html").is_file():
        return FileResponse(directory / "index.html")
    raise HTTPException(
        404, "Build the frontend with pnpm build, or use the Vite development server on port 5173."
    )
