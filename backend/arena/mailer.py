"""Outgoing email. SMTP when configured, a local outbox when not.

Production sets ARENA_SMTP_* and mail leaves the machine. The local pilot
runs without credentials: messages land in DATA/outbox/*.txt with the full
link, which the operator reads and passes on. No tokens are ever returned
through the API.
"""
from __future__ import annotations

import logging
import os
import smtplib
import time
from email.message import EmailMessage

from . import db

log = logging.getLogger(__name__)

VERIFY_TTL = 24 * 3600
RESET_TTL = 3600


def _smtp_config():
    host = os.environ.get("ARENA_SMTP_HOST", "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("ARENA_SMTP_PORT", "587")),
        "user": os.environ.get("ARENA_SMTP_USER", ""),
        "pass": os.environ.get("ARENA_SMTP_PASS", ""),
        "from": os.environ.get("ARENA_MAIL_FROM", "arena@localhost"),
    }


def public_url() -> str:
    return os.environ.get("ARENA_PUBLIC_URL", "http://127.0.0.1:8001").rstrip("/")


def send_mail(to: str, subject: str, body: str) -> str:
    """Deliver an email. Returns the transport used: 'smtp' or 'outbox'."""
    config = _smtp_config()
    if config is None:
        outbox = db.DATA / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = outbox / f"{stamp}-{to.replace('@', '_at_')}.txt"
        path.write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
        log.info("outbox mail to %s: %s", to, subject)
        return "outbox"
    message = EmailMessage()
    message["From"] = config["from"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(config["host"], config["port"], timeout=15) as smtp:
        if config["port"] == 587:
            smtp.starttls()
        if config["user"]:
            smtp.login(config["user"], config["pass"])
        smtp.send_message(message)
    return "smtp"


def verification_email(to: str, token: str) -> str:
    link = f"{public_url()}/verify?token={token}"
    body = (
        "Welcome to Stack Theory.\n\n"
        f"Verify your email to submit bots:\n{link}\n\n"
        "The link expires in 24 hours. If you did not sign up, ignore this message."
    )
    return send_mail(to, "Stack Theory · verify your email", body)


def reset_email(to: str, token: str) -> str:
    link = f"{public_url()}/reset?token={token}"
    body = (
        "A password reset was requested for your Stack Theory account.\n\n"
        f"Set a new password:\n{link}\n\n"
        "The link expires in 1 hour. If this was not you, ignore this message."
    )
    return send_mail(to, "Stack Theory · password reset", body)
