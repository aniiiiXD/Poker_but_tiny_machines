#!/usr/bin/env python3
"""Run the independent API and Vite applications; Ctrl-C stops both."""
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for tool in ('uv', 'pnpm'):
    if not shutil.which(tool):
        raise SystemExit(f'Install {tool} first; see README.md.')
for port in (8001, 5173):
    with socket.socket() as check:
        if check.connect_ex(('127.0.0.1', port)) == 0:
            raise SystemExit(f'Port {port} is already in use. The app may already be running.')
children = []


def cleanup(*_):
    for child in children:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
    for child in children:
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)
try:
    children.append(subprocess.Popen(['uv','run','uvicorn','arena.app:app','--host','127.0.0.1','--port','8001'], cwd=ROOT/'backend', start_new_session=True))
    children.append(subprocess.Popen(['pnpm','dev'], cwd=ROOT/'frontend', start_new_session=True))
    print('\nStack Theory: http://127.0.0.1:5173\nAPI docs: http://127.0.0.1:8001/docs\n', flush=True)
    while all(child.poll() is None for child in children):
        time.sleep(.5)
finally:
    cleanup()
