#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-$PROJECT_ROOT}"
ENV_FILE="${ENV_FILE:-$COMPOSE_PROJECT_DIR/.env}"
DRY_RUN=0

DB_NAME="${DB_NAME:-malla}"
DB_USER="${DB_USER:-malla}"
DB_PASSWORD="${DB_PASSWORD:?DB_PASSWORD must be set}"
POSTGRES_DSN="${POSTGRES_DSN:-postgresql://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/var/run/postgresql}"

SQLITE_DB_PATH="${SQLITE_DB_PATH:-}"
SNAPSHOT_PATH="${SNAPSHOT_PATH:-/tmp/meshtastic_history_migration_snapshot.db}"
CAPTURE_CONTAINER="${CAPTURE_CONTAINER:-malla-malla-capture-1}"
WEB_URL="${WEB_URL:-http://127.0.0.1:5008}"

COMPOSE_FILES=(
    -f docker-compose.yml
    -f docker-compose.prod.yml
    -f docker-compose.remote-build.yml
)

log() {
    printf '[switch-to-postgres] %s\n' "$*"
}

fail() {
    printf '[switch-to-postgres] ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

usage() {
    cat <<'EOF'
Usage: switch_to_postgres.sh [--dry-run]

Environment variables:
  DB_PASSWORD         Required PostgreSQL password for DB_USER
  DB_NAME             PostgreSQL database name (default: malla)
  DB_USER             PostgreSQL user name (default: malla)
  POSTGRES_DSN        PostgreSQL DSN override
  SQLITE_DB_PATH      Source SQLite database path override
  SNAPSHOT_PATH       Snapshot target path
  CAPTURE_CONTAINER   Capture container name
  WEB_URL             Base URL for health checks
  ENV_FILE            Path to .env
  COMPOSE_PROJECT_DIR Compose project root
EOF
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --dry-run)
                DRY_RUN=1
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                fail "Unknown argument: $1"
                ;;
        esac
        shift
    done
}

run_cmd() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '[switch-to-postgres] DRY-RUN:'
        printf ' %q' "$@"
        printf '\n'
        return 0
    fi

    "$@"
}

write_build_commit_file() {
    local commit

    commit="$(git -C "$COMPOSE_PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || true)"
    [ -n "$commit" ] || commit="unknown"

    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: would write BUILD_COMMIT=$commit"
        return
    fi

    printf '%s\n' "$commit" > "$COMPOSE_PROJECT_DIR/BUILD_COMMIT"
}

ensure_pg_hba_local_password_auth() {
    local hba_file

    hba_file="$(sudo -u postgres psql -Atqc 'SHOW hba_file')"
    [ -n "$hba_file" ] || fail "Unable to determine pg_hba.conf path"

    if grep -Eq '^local[[:space:]]+all[[:space:]]+all[[:space:]]+scram-sha-256([[:space:]]|$)' "$hba_file"; then
        log "pg_hba.conf already allows password auth for local connections"
        return
    fi

    log "Updating pg_hba.conf local auth to scram-sha-256"
    run_cmd sudo cp "$hba_file" "${hba_file}.bak.$(date +%s)"
    run_cmd sudo sed -i -E \
        "s/^local([[:space:]]+all[[:space:]]+all[[:space:]]+)peer([[:space:]]|$)/local\1scram-sha-256\2/" \
        "$hba_file"
    run_cmd sudo systemctl restart postgresql
}

detect_sqlite_db_path() {
    if [ -n "$SQLITE_DB_PATH" ]; then
        [ -f "$SQLITE_DB_PATH" ] || fail "SQLITE_DB_PATH does not exist: $SQLITE_DB_PATH"
        return
    fi

    if [ -f "$COMPOSE_PROJECT_DIR/.env" ]; then
        local env_db_path
        env_db_path="$(grep -E '^MALLA_DATABASE_FILE=' "$COMPOSE_PROJECT_DIR/.env" | tail -n1 | cut -d= -f2- || true)"
        if [ -n "$env_db_path" ] && [ -f "$env_db_path" ]; then
            SQLITE_DB_PATH="$env_db_path"
            return
        fi
    fi

    local candidates=(
        "/var/lib/docker/volumes/malla_malla_data/_data/meshtastic_history.db"
        "/var/lib/docker/volumes/${PWD##*/}_malla_data/_data/meshtastic_history.db"
        "$COMPOSE_PROJECT_DIR/data/meshtastic_history.db"
        "$COMPOSE_PROJECT_DIR/meshtastic_history.db"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [ -f "$candidate" ]; then
            SQLITE_DB_PATH="$candidate"
            return
        fi
    done

    fail "Unable to find SQLite database automatically. Set SQLITE_DB_PATH explicitly."
}

create_postgres_db() {
    log "Ensuring PostgreSQL user/database exist"
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '[switch-to-postgres] DRY-RUN: DB_NAME=%q DB_USER=%q DB_PASSWORD=%q %q\n' \
            "$DB_NAME" "$DB_USER" "$DB_PASSWORD" "$PROJECT_ROOT/scripts/create_postgres_db.sh"
        return
    fi
    DB_NAME="$DB_NAME" DB_USER="$DB_USER" DB_PASSWORD="$DB_PASSWORD" \
        "$PROJECT_ROOT/scripts/create_postgres_db.sh"
}

stop_capture_for_snapshot() {
    if docker ps --format '{{.Names}}' | grep -qx "$CAPTURE_CONTAINER"; then
        log "Stopping capture container for a consistent SQLite snapshot"
        run_cmd docker stop "$CAPTURE_CONTAINER" >/dev/null
        return 0
    fi

    log "Capture container $CAPTURE_CONTAINER is not running, snapshot will proceed without stop"
    return 1
}

start_capture_after_snapshot() {
    if docker ps -a --format '{{.Names}}' | grep -qx "$CAPTURE_CONTAINER"; then
        log "Starting capture container after snapshot"
        run_cmd docker start "$CAPTURE_CONTAINER" >/dev/null
    fi
}

update_env_file() {
    [ -f "$ENV_FILE" ] || fail ".env file not found: $ENV_FILE"

    log "Updating PostgreSQL backend settings in $ENV_FILE"
    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: would set MALLA_DATABASE_BACKEND=postgres"
        log "DRY-RUN: would set MALLA_POSTGRES_DSN=$POSTGRES_DSN"
        return
    fi
    python3 - "$ENV_FILE" "$POSTGRES_DSN" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
postgres_dsn = sys.argv[2]

lines = env_path.read_text().splitlines()
keys = {
    "MALLA_DATABASE_BACKEND": "postgres",
    "MALLA_POSTGRES_DSN": postgres_dsn,
}
seen = set()
updated = []

for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        updated.append(line)
        continue
    key, _value = line.split("=", 1)
    if key in keys:
        updated.append(f"{key}={keys[key]}")
        seen.add(key)
    else:
        updated.append(line)

for key, value in keys.items():
    if key not in seen:
        updated.append(f"{key}={value}")

env_path.write_text("\n".join(updated) + "\n")
PY
}

verify_http() {
    local path="$1"
    local status
    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: would verify ${WEB_URL}${path}"
        return
    fi
    status="$(curl -s -o /dev/null -w '%{http_code}' "${WEB_URL}${path}")"
    [ "$status" = "200" ] || fail "HTTP check failed for ${path}: ${status}"
}

verify_postgres_growth() {
    local query="SELECT COUNT(*), COALESCE(MAX(id), 0) FROM packet_history;"
    local first second

    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: would verify PostgreSQL packet counter growth"
        return
    fi

    first="$(PGPASSWORD="$DB_PASSWORD" psql "$POSTGRES_DSN" -Atc "$query")"
    sleep 3
    second="$(PGPASSWORD="$DB_PASSWORD" psql "$POSTGRES_DSN" -Atc "$query")"

    log "PostgreSQL packet counters: ${first} -> ${second}"
}

main() {
    parse_args "$@"
    require_command docker
    require_command uv
    require_command python3
    require_command psql
    require_command curl

    cd "$COMPOSE_PROJECT_DIR"

    detect_sqlite_db_path
    log "Using SQLite database: $SQLITE_DB_PATH"

    ensure_pg_hba_local_password_auth
    create_postgres_db

    local capture_was_running=0
    if stop_capture_for_snapshot; then
        capture_was_running=1
    fi

    log "Creating SQLite snapshot at $SNAPSHOT_PATH"
    run_cmd cp "$SQLITE_DB_PATH" "$SNAPSHOT_PATH"

    if [ "$capture_was_running" -eq 1 ]; then
        start_capture_after_snapshot
    fi

    log "Migrating SQLite snapshot to PostgreSQL"
    run_cmd uv run python "$PROJECT_ROOT/scripts/migrate_sqlite_to_postgres.py" \
        --sqlite-path "$SNAPSHOT_PATH" \
        --postgres-dsn "$POSTGRES_DSN" \
        --truncate

    update_env_file
    write_build_commit_file

    log "Rebuilding and restarting application with PostgreSQL backend"
    run_cmd docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" up -d --build

    log "Verifying application endpoints"
    verify_http "/"
    verify_http "/api/stats"
    verify_http "/api/analytics"

    verify_postgres_growth

    log "Switch to PostgreSQL completed successfully"
}

main "$@"
