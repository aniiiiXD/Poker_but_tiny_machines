"""Local operator commands. No default admin account or exposed admin token."""

from __future__ import annotations

import argparse
import json
import time

from . import db, worker
from .sandbox import MODEL_IMAGE, image_id


def main():
    parser = argparse.ArgumentParser(description="Stack Theory local operator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("events", help="List events and their round status")
    admin = sub.add_parser("make-admin", help="Promote an existing registered account")
    admin.add_argument("email")
    create = sub.add_parser("create-event", help="Create a locally scheduled event")
    create.add_argument("title")
    create.add_argument("--tables", type=int, default=8)
    create.add_argument("--hands", type=int, default=50)
    create.add_argument("--rounds", type=int, default=6)
    create.add_argument("--build-minutes", type=int, default=60)
    create.add_argument("--interval", type=int, default=1200)
    create.add_argument("--starts-in", type=int, default=60, help="Minutes until build starts")
    create.add_argument("--sponsor", default=None)
    create.add_argument("--track", choices=("classic", "model"), default="classic")
    create.add_argument("--game", default="poker", help="registered game ID (e.g. poker, bluff)")
    run = sub.add_parser("run-round", help="Freeze submissions and enqueue the next round now")
    run.add_argument("event_id")
    start = sub.add_parser("start-build", help="Open an event build phase now")
    start.add_argument("event_id")
    sub.add_parser("inquiries", help="Read locally stored sponsor inquiries")
    args = parser.parse_args()
    if not (db.DATA / "arena.sqlite").exists():
        db.initialize()
    # A running server owns its active worker leases.
    if args.command == "make-admin":
        with db.connect(True) as c:
            result = c.execute("UPDATE users SET role='admin' WHERE email=?", (args.email.strip().lower(),))
            if not result.rowcount:
                parser.error("Register this account in the website first.")
        print("Administrator access granted to the registered account.")
    elif args.command == "events":
        with db.connect() as c:
            for event in c.execute("SELECT id,title,status FROM events ORDER BY build_starts_at").fetchall():
                print(dict(event))
                for row in c.execute(
                    "SELECT number,status,entries_count FROM rounds WHERE event_id=? ORDER BY number",
                    (event["id"],),
                ):
                    print("  ", dict(row))
    elif args.command == "create-event":
        if not (
            1 <= args.tables <= 10000
            and 1 <= args.hands <= 200
            and 1 <= args.rounds <= 6
            and 1 <= args.build_minutes <= 1440
            and args.interval >= 10
            and args.starts_in >= 0
        ):
            parser.error(
                "Use 1–10000 tables, 1–200 hands, 1–6 rounds, 1–1440 build minutes, interval≥10s, starts-in≥0."
            )
        event_id = worker.ident()
        starts = time.time() + args.starts_in * 60
        from .games import GameError, get_game

        try:
            spec = get_game(args.game)
        except GameError as exc:
            parser.error(str(exc))
        digest = image_id(MODEL_IMAGE) if args.track == "model" else image_id()
        if not digest:
            parser.error("Build the matching sandbox image before creating an event: make sandbox")
        with db.connect(True) as c:
            c.execute(
                """INSERT INTO events(id,title,description,status,variant,build_starts_at,
                   build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,
                   decision_ms,sponsor_name,exhibition,sandbox_digest,game_id,rules_version)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    args.title[:100],
                    "An online Python pokerbot tournament. Build, test, compete, and replay your decisions.",
                    "registration",
                    spec.variant_label,
                    starts,
                    starts + args.build_minutes * 60,
                    args.interval,
                    args.rounds,
                    args.tables,
                    args.hands,
                    50.0 if args.track == "model" else 1.0,
                    args.sponsor,
                    0,
                    digest,
                    spec.game_id,
                    spec.rules_version,
                ),
            )
            c.execute("INSERT INTO event_tracks VALUES(?,?)", (event_id, args.track))
        print(event_id)
    elif args.command == "run-round":
        try:
            print("Queued job:", worker.enqueue_round(args.event_id, manual=True))
        except ValueError as error:
            parser.error(str(error))
    elif args.command == "start-build":
        with db.connect(True) as c:
            event = c.execute("SELECT * FROM events WHERE id=?", (args.event_id,)).fetchone()
            if not event or event["status"] != "registration" or event["exhibition"]:
                parser.error("Select an upcoming student event.")
            now = time.time()
            c.execute(
                "UPDATE events SET status='building',build_starts_at=?,build_ends_at=? WHERE id=?",
                (now, now + event["build_ends_at"] - event["build_starts_at"], args.event_id),
            )
        print("Build phase started.")
    elif args.command == "inquiries":
        with db.connect() as c:
            print(
                json.dumps(
                    [dict(r) for r in c.execute("SELECT * FROM sponsor_inquiries ORDER BY created_at DESC")],
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
