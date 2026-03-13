#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-$PROJECT_ROOT}"
ENV_FILE="${ENV_FILE:-$COMPOSE_PROJECT_DIR/.env}"
DRY_RUN=0

SQLITE_DB_PATH="${SQLITE_DB_PATH:-}"
WEB_URL="${WEB_URL:-http://127.0.0.1:5008}"

COMPOSE_FILES=(
    -f docker-compose.yml
    -f docker-compose.prod.yml
    -f docker-compose.remote-build.yml
)

log() {
    printf '[switch-to-sqlite] %s\n' "$*"
}

fail() {
    printf '[switch-to-sqlite] ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: switch_to_sqlite.sh [--dry-run]

Environment variables:
  SQLITE_DB_PATH      Optional explicit SQLite DB path
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
        printf '[switch-to-sqlite] DRY-RUN:'
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

detect_sqlite_db_path() {
    if [ -n "$SQLITE_DB_PATH" ]; then
        [ -f "$SQLITE_DB_PATH" ] || fail "SQLITE_DB_PATH does not exist: $SQLITE_DB_PATH"
        return
    fi

    if [ -f "$ENV_FILE" ]; then
        local env_db_path
        env_db_path="$(grep -E '^MALLA_DATABASE_FILE=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)"
        if [ -n "$env_db_path" ]; then
            SQLITE_DB_PATH="$env_db_path"
            return
        fi
    fi

    SQLITE_DB_PATH="/app/data/meshtastic_history.db"
}

update_env_file() {
    [ -f "$ENV_FILE" ] || fail ".env file not found: $ENV_FILE"

    log "Updating SQLite backend settings in $ENV_FILE"
    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: would set MALLA_DATABASE_BACKEND=sqlite"
        log "DRY-RUN: would set MALLA_DATABASE_FILE=$SQLITE_DB_PATH"
        log "DRY-RUN: would clear MALLA_POSTGRES_DSN"
        return
    fi

    python3 - "$ENV_FILE" "$SQLITE_DB_PATH" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
sqlite_db_path = sys.argv[2]

lines = env_path.read_text().splitlines()
keys = {
    "MALLA_DATABASE_BACKEND": "sqlite",
    "MALLA_DATABASE_FILE": sqlite_db_path,
    "MALLA_POSTGRES_DSN": "",
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

main() {
    parse_args "$@"

    command -v docker >/dev/null 2>&1 || fail "Missing required command: docker"
    command -v python3 >/dev/null 2>&1 || fail "Missing required command: python3"
    command -v curl >/dev/null 2>&1 || fail "Missing required command: curl"

    cd "$COMPOSE_PROJECT_DIR"

    detect_sqlite_db_path
    log "Using SQLite path: $SQLITE_DB_PATH"

    update_env_file
    write_build_commit_file

    log "Rebuilding and restarting application with SQLite backend"
    run_cmd docker compose --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" up -d --build

    log "Verifying application endpoints"
    verify_http "/"
    verify_http "/api/stats"
    verify_http "/api/analytics"

    log "Switch to SQLite completed successfully"
}

main "$@"
