#!/usr/bin/env python3
"""Playtest: one agent per game, through the real platform.

Registers 6 users/teams, verifies email via the outbox, downloads each game's
starter, submits it, runs a REAL Docker-sandbox practice match, polls the job,
opens the replay, and prints a usability verdict per game.

Run: python3 dev/playtest.py [--base http://127.0.0.1:8001]
"""
import json
import pathlib
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8001"
OUTBOX = pathlib.Path(__file__).resolve().parent.parent / "backend" / "data" / "outbox"
GAMES = ["poker", "bluff", "uno", "hearts", "rummy", "hexchange"]
TIMEOUT = 240


def call(method, path, body=None, cookie=None, raw=None):
    url = BASE + path
    data = None
    headers = {}
    if raw is not None:
        data = raw
        headers["Content-Type"] = "application/zip"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            set_cookie = r.headers.get("Set-Cookie", "")
            token = set_cookie.split(";")[0] if "arena_session=" in set_cookie else cookie
            return r.status, json.loads(r.read() or b"{}"), token
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), cookie
        except Exception:
            return e.code, {}, cookie


def verify_email(email):
    """Consume the newest verify token for this email from the server's outbox."""
    token = None
    deadline = time.time() + 10
    while time.time() < deadline and token is None:
        for f in sorted(OUTBOX.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True):
            if email.replace("@", "_at_") in f.name:
                for line in f.read_text().splitlines():
                    if "/verify?token=" in line:
                        token = line.split("token=")[1].strip()
                        break
        if token is None:
            time.sleep(0.5)
    if token:
        call("POST", "/api/auth/verify", {"token": token})


def poll_job(job_id, cookie):
    t0 = time.time()
    while time.time() - t0 < TIMEOUT:
        status, body, _ = call("GET", f"/api/jobs/{job_id}", cookie=cookie)
        j = body
        if j.get("status") in ("completed", "failed"):
            return j
        time.sleep(1.5)
    return {"status": "timeout", "error": f"{TIMEOUT}s without completion"}


def main():
    rows = []
    print(f"PLAYTEST — six agents through the real platform ({BASE})\n" + "=" * 72)
    for game in GAMES:
        tag = {"poker": "pkr", "bluff": "blf", "uno": "uno", "hearts": "hrt",
               "rummy": "rm6", "hexchange": "hxc"}[game]
        email = f"playtest-{tag}@test.local"
        steps = []
        ok = True
        # 1. register (429 = rate-limited IP: existing users log in) + verify + team
        status, body, cookie = call("POST", "/api/auth/register", {
            "name": f"Playtest {tag}", "email": email, "password": "playtest123",
            "college": "Playtest College"})
        if status in (409, 429):
            status, body, cookie = call("POST", "/api/auth/login", {
                "email": email, "password": "playtest123"})
        steps.append(f"register {status}")
        verify_email(email)
        status, _, cookie = call("POST", "/api/team", {"name": f"Playtest {tag}"}, cookie=cookie)
        if status == 409:
            status, body, _ = call("GET", "/api/me", cookie=cookie)
        steps.append(f"team {status}")
        # 3. reuse an accepted same-game submission if one exists, else submit
        status, subs, cookie = call("GET", "/api/submissions", cookie=cookie)
        sid = next((s["id"] for s in subs.get("submissions", [])
                    if s.get("status") == "accepted" and s.get("game") == game), None)
        if sid:
            steps.append("reuse accepted")
        else:
            status, starter, _ = call("GET", f"/api/starter?game={game}")
            steps.append(f"starter {status}")
            ok &= status == 200
            status, sub, cookie = call("POST", "/api/submissions", {
                "name": f"{game} agent", "source": starter.get("source", ""), "game": game},
                cookie=cookie)
            steps.append(f"submit {status} {str(sub.get('detail', ''))[:40]}")
            ok &= status == 201
            sid = sub.get("id")
        # 4. practice with the submitted agent (real sandbox)
        body_practice = {"game": game, "submission_id": sid}
        status, pr, _ = call("POST", "/api/practice", body_practice, cookie=cookie)
        steps.append(f"practice {status}")
        if status != 202:
            ok = False
            rows.append((game, steps, "BLOCKED: " + str(pr.get("detail", ""))[:80]))
            print(f"{game:10s} {' — '.join(steps)}  ⛔ {str(pr.get('detail',''))[:80]}")
            continue
        job = poll_job(pr["job_id"], cookie)
        result = job.get("result") or {}
        faults = sum(s.get("faults", 0) for s in result.get("scores", []))
        steps.append(f"job {job['status']}")
        ok &= job["status"] == "completed"
        # 5. replay readable + no leaked log
        replay_ok = False
        if result.get("replay_id"):
            status, rep, _ = call("GET", f"/api/replays/{result['replay_id']}", cookie=cookie)
            frames = rep.get("frames")
            has_frames = (isinstance(frames, list) and len(frames) > 0) or (
                isinstance(frames, dict) and len(frames.get("frames", [])) > 0)
            # Poker's summary has always carried its (public) hand log; every
            # other game must keep the privileged audit log out.
            leak = "log" in rep.get("summary", {}) and game != "poker"
            replay_ok = status == 200 and has_frames and not leak
            steps.append(f"replay {'ok' if replay_ok else 'LEAK/BROKEN'}")
            ok &= replay_ok
        err = next((s.get("error") for s in result.get("scores", []) if s.get("error")), None)
        verdict = "✅ PLAYABLE" if ok and job["status"] == "completed" else "❌ BROKEN"
        if err:
            verdict += f" · bot error: {err[:60]}"
            ok = False
        rows.append((game, steps, verdict))
        print(f"{game:10s} {' — '.join(steps)}  {verdict}")
        print(f"{'':10s} scores: " + ", ".join(
            f"{s['name']} {s['points']}" for s in result.get("scores", [])[:4]) +
            f" · faults {faults} · {result.get('matches', result.get('hands'))} match(es)")
    print("=" * 72)
    playable = sum(1 for _, _, v in rows if v.startswith("✅"))
    print(f"VERDICT: {playable}/{len(GAMES)} games playable end-to-end by a submitted agent")


if __name__ == "__main__":
    main()
