#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SERVICE_NAME="${SERVICE_NAME:-malla-web}"
TRUNCATE_FLAG="${TRUNCATE_FLAG:---truncate}"

usage() {
    cat <<'EOF'
Usage: ./scripts/sync_mobile_bts.sh

What it does:
  - ensures the web container is running
  - runs the BTS import inside the container
  - refreshes rows in mobile_bts_sites from supported public BTS sources

Optional environment variables:
  INSTALL_DIR    Repository path with docker compose files
  SERVICE_NAME   Compose service to execute in (default: malla-web)
  TRUNCATE_FLAG  Import mode flag, default: --truncate
EOF
}

log() {
    printf '[sync-mobile-bts] %s\n' "$*"
}

fail() {
    printf '[sync-mobile-bts] ERROR: %s\n' "$*" >&2
    exit 1
}

require_repo() {
    [ -d "$INSTALL_DIR" ] || fail "Install directory not found: $INSTALL_DIR"
    [ -f "$INSTALL_DIR/docker-compose.yml" ] || fail "docker-compose.yml not found in $INSTALL_DIR"
}

ensure_service_running() {
    cd "$INSTALL_DIR"
    if ! docker compose \
        --env-file .env \
        -f docker-compose.yml \
        -f docker-compose.prod.yml \
        -f docker-compose.remote-build.yml \
        ps --status running "$SERVICE_NAME" | grep -q "$SERVICE_NAME"
    then
        fail "Compose service '$SERVICE_NAME' is not running"
    fi
}

run_import() {
    cd "$INSTALL_DIR"
    log "Refreshing mobile BTS data in mobile_bts_sites"
    docker compose \
        --env-file .env \
        -f docker-compose.yml \
        -f docker-compose.prod.yml \
        -f docker-compose.remote-build.yml \
        exec -T "$SERVICE_NAME" \
        /app/.venv/bin/python /app/scripts/import_mobile_bts.py "$TRUNCATE_FLAG"
}

main() {
    case "${1:-}" in
        -h|--help)
            usage
            exit 0
            ;;
    esac

    require_repo
    ensure_service_running
    run_import
    log "Mobile BTS sync completed"
}

main "$@"
