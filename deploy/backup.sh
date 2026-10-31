#!/bin/sh
# Online backup of the arena database plus bot sources. Keeps 14 days.
set -eu
DATA_DIR="${ARENA_DATA_DIR:-/srv/arena-data}"
DEST="${1:-$DATA_DIR/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
sqlite3 "$DATA_DIR/arena.sqlite" ".backup '$DEST/arena-$STAMP.sqlite'"
tar -czf "$DEST/bots-$STAMP.tar.gz" -C "$DATA_DIR" bots
find "$DEST" -name 'arena-*.sqlite' -mtime +14 -delete
find "$DEST" -name 'bots-*.tar.gz' -mtime +14 -delete
echo "backup complete: $DEST/arena-$STAMP.sqlite"
