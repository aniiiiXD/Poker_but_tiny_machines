#!/bin/sh
# deploy.sh — ship the current commit to the pilot box and verify it.
# Usage: ./deploy/deploy.sh [host]   (host = user@ip, default from $ARENA_DEPLOY_HOST)
# Run FROM THE REPO ROOT after pushing. The box must have completed the
# one-time provisioning in deploy/HOSTING.md.
set -eu
HOST="${1:-${ARENA_DEPLOY_HOST:?set ARENA_DEPLOY_HOST=user@host or pass it}}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
SHA="$(git rev-parse --short HEAD)"

echo "▶ deploying $BRANCH@$SHA to $HOST"
ssh "$HOST" "set -e
  cd /srv/arena
  git fetch origin
  git checkout $SHA
  cd backend && uv sync --python 3.12
  cd .. && docker build -q -t campus-arena-bot:local backend/sandbox
  docker build -q -t campus-arena-model:local backend/sandbox -f backend/sandbox/Dockerfile.model
  sudo systemctl restart arena-api arena-worker@1 arena-worker@2
  sleep 4"
echo "▶ health check"
code=$(curl -s -o /dev/null -w '%{http_code}' "https://$(ssh "$HOST" "hostname -f")/api/health" || true)
ssh "$HOST" "curl -s -m 5 http://127.0.0.1:8001/api/health"
echo
echo "✅ deployed $SHA — verify the site, then brag responsibly."
