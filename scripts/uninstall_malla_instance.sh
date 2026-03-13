#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/malla}"
PURGE_POSTGRES="${PURGE_POSTGRES:-0}"
PURGE_PACKAGES="${PURGE_PACKAGES:-0}"
FORCE=0

usage() {
    cat <<'EOF'
Usage: sudo ./scripts/uninstall_malla_instance.sh [--force]

What it removes:
  - Malla Docker containers
  - local Docker volume malla_data
  - cloned repository at INSTALL_DIR
  - optional PostgreSQL database/user
  - optional system packages

Environment variables:
  INSTALL_DIR      Repository path to remove (default: /opt/malla)
  PURGE_POSTGRES   1 = also drop PostgreSQL DB/user malla
  PURGE_PACKAGES   1 = also remove docker/postgresql/git/rsync packages
EOF
}

log() {
    printf '[uninstall-malla] %s\n' "$*"
}

fail() {
    printf '[uninstall-malla] ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    [ "$(id -u)" -eq 0 ] || fail "Run this script as root or via sudo"
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --force)
                FORCE=1
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

confirm() {
    if [ "$FORCE" -eq 1 ]; then
        return
    fi

    if [ -t 0 ] && [ -t 1 ]; then
        local answer
        read -r -p "This will remove Malla from this host. Continue? [y/N] " answer
        [[ "$answer" =~ ^[Yy]$ ]] || exit 0
        return
    fi

    fail "Refusing to run non-interactively without --force"
}

remove_malla() {
    if [ -d "$INSTALL_DIR" ]; then
        log "Stopping and removing Malla containers"
        (
            cd "$INSTALL_DIR"
            docker compose \
                --env-file .env \
                -f docker-compose.yml \
                -f docker-compose.prod.yml \
                -f docker-compose.remote-build.yml \
                down -v || true
        )

        log "Removing install directory $INSTALL_DIR"
        rm -rf "$INSTALL_DIR"
    else
        log "Install directory not found: $INSTALL_DIR"
    fi

    if docker volume ls --format '{{.Name}}' | grep -qx 'malla_malla_data'; then
        log "Removing Docker volume malla_malla_data"
        docker volume rm -f malla_malla_data || true
    fi
}

purge_postgres() {
    if [ "$PURGE_POSTGRES" != "1" ]; then
        return
    fi

    if command -v psql >/dev/null 2>&1; then
        log "Dropping PostgreSQL database/user malla"
        sudo -u postgres psql <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'malla';
DROP DATABASE IF EXISTS malla;
DROP ROLE IF EXISTS malla;
SQL
    fi
}

purge_packages() {
    if [ "$PURGE_PACKAGES" != "1" ]; then
        return
    fi

    log "Purging deployment-related packages"
    apt-get remove -y --purge \
        docker.io \
        docker-compose-v2 \
        docker-compose-plugin \
        docker-compose \
        docker-buildx \
        docker-buildx-plugin \
        postgresql \
        postgresql-contrib \
        postgresql-client \
        libpq-dev \
        git \
        rsync || true
    apt-get autoremove -y
}

main() {
    require_root
    parse_args "$@"
    confirm
    remove_malla
    purge_postgres
    purge_packages
    log "Uninstall completed"
}

main "$@"
