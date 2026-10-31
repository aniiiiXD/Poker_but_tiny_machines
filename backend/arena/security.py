from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from fastapi import HTTPException, Request
from .db import connect

COOKIE = "arena_session"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    salt, expected = stored.split(":")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(c, user_id: str):
    token = secrets.token_urlsafe(40)
    c.execute("INSERT INTO sessions VALUES(?,?,?)", (digest_token(token), user_id, time.time() + 86400 * 7))
    return token


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 256:
        return None
    with connect() as c:
        row = c.execute(
            "SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires_at>?",
            (digest_token(token), time.time()),
        ).fetchone()
        if row:
            user = dict(row)
            del user["password"]
            user["email_verified"] = bool(user["email_verified"])
            return user
    return None


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Log in to continue.")
    return user


def require_team(request: Request):
    user = require_user(request)
    if not user["team_id"]:
        raise HTTPException(
            409, "Create or join a team first. Solo competitors can create a one-person team."
        )
    return user


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Only the event operator can do that.")
    return user


def rate_limit(key: str, maximum: int, seconds: int):
    now = time.time()
    with connect(True) as c:
        row = c.execute("SELECT * FROM rate_limits WHERE key=?", (key,)).fetchone()
        if row and row["reset_at"] > now:
            if row["count"] >= maximum:
                raise HTTPException(429, "Too many requests. Please wait before trying again.")
            c.execute("UPDATE rate_limits SET count=count+1 WHERE key=?", (key,))
        else:
            c.execute("INSERT OR REPLACE INTO rate_limits VALUES(?,?,?)", (key, 1, now + seconds))
