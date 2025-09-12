#!/usr/bin/env bash
# scripts/pg_backup.sh
#
# Description:
#   Minimal, reliable PostgreSQL backup helper.
#   Reads standard env vars (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE)
#   and writes a compressed dump to:
#       backups/$(date +%F_%H%M)-dump.sql.gz
#
# Usage:
#   PGHOST=... PGPORT=5432 PGUSER=... PGPASSWORD=... PGDATABASE=... \
#     ./scripts/pg_backup.sh
#
# Notes:
#   - Requires `pg_dump` in PATH.
#   - Does NOT echo credentials.
#   - Exits non-zero on failure.
#   - You can override backup directory via BACKUP_DIR env (default: backups).
#
# Example cron (daily at 02:15):
#   15 2 * * * cd /your/app && PGHOST=db.local PGPORT=5432 PGUSER=app \
#     PGPASSWORD='********' PGDATABASE=appdb BACKUP_DIR=/var/backups/app \
#     ./scripts/pg_backup.sh >> /var/log/app/pg_backup.log 2>&1

set -Eeuo pipefail
IFS=$'\n\t'

# ------------- helpers -------------

log() {
  # shellcheck disable=SC2059
  printf "%s %s\n" "$(date +"%Y-%m-%dT%H:%M:%S%z")" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

# ------------- preflight -------------

command -v pg_dump >/dev/null 2>&1 || die "pg_dump not found in PATH"

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
# PGPASSWORD is optional if .pgpass is configured; enforce if not present.
if [[ -z "${PGPASSWORD:-}" ]] && [[ ! -f "$HOME/.pgpass" ]]; then
  die "PGPASSWORD is required (or configure $HOME/.pgpass)"
fi

PGPORT="${PGPORT:-5432}"
BACKUP_DIR="${BACKUP_DIR:-backups}"

mkdir -p "$BACKUP_DIR" || die "Failed to create backup dir: $BACKUP_DIR"

timestamp="$(date +%F_%H%M)"
outfile="${BACKUP_DIR}/${timestamp}-dump.sql.gz"

log "Starting pg_dump (host=$PGHOST port=$PGPORT db=$PGDATABASE user=$PGUSER)"
log "Output: $outfile"

# ------------- dump -------------

# Export PGPASSWORD for pg_dump, but never print it.
if [[ -n "${PGPASSWORD:-}" ]]; then
  export PGPASSWORD
fi

# --no-owner/--no-privileges make restores more portable across envs.
# Use plain SQL piped to gzip to keep script simple and portable.
pg_dump \
  --host="$PGHOST" \
  --port="$PGPORT" \
  --username="$PGUSER" \
  --format=plain \
  --no-owner \
  --no-privileges \
  "$PGDATABASE" \
  | gzip -c > "$outfile"

# ------------- post-check -------------

if [[ ! -s "$outfile" ]]; then
  die "Backup file is missing or empty: $outfile"
fi

log "Backup completed successfully: $outfile"
