#!/usr/bin/env bash
set -euo pipefail

BACKEND="${1:-}"
INSTALL_DIR="${INSTALL_DIR:-/opt/malla}"
REPO_URL="${REPO_URL:-https://github.com/norman67cz/malla.git}"
RUN_AS_USER="${RUN_AS_USER:-${SUDO_USER:-$(id -un)}}"

DEFAULT_MALLA_NAME="${DEFAULT_MALLA_NAME:-Malla}"
DEFAULT_SECRET_KEY="${DEFAULT_SECRET_KEY:-8a5b2d1d4b2f4a4ea8748e7c0f5f5c9581d1e2cb0ef1d4e4b7c8b823a0d1a5f2}"
DEFAULT_WEB_PORT="${DEFAULT_WEB_PORT:-5008}"
DEFAULT_WEB_COMMAND="${DEFAULT_WEB_COMMAND:-/app/.venv/bin/malla-web-gunicorn}"
DEFAULT_MQTT_BROKER="${DEFAULT_MQTT_BROKER:-mqtt.aperturelab.cz}"
DEFAULT_MQTT_PORT="${DEFAULT_MQTT_PORT:-1883}"
DEFAULT_MQTT_USERNAME="${DEFAULT_MQTT_USERNAME:-meshuser}"
DEFAULT_MQTT_PASSWORD="${DEFAULT_MQTT_PASSWORD:-meshpass}"
DEFAULT_MQTT_TOPIC_PREFIX="${DEFAULT_MQTT_TOPIC_PREFIX:-msh}"
DEFAULT_MQTT_TOPIC_SUFFIX="${DEFAULT_MQTT_TOPIC_SUFFIX:-/+/+/+/#}"
DEFAULT_CHANNEL_KEYS="${DEFAULT_CHANNEL_KEYS:-1PG7OiApB1nwvP+rz05pAQ==,mL4n/BUz3SPL/pwGVeHi50kSZ/FgkiLyumjYZxTY7Vs=}"
DEFAULT_DB_NAME="${DEFAULT_DB_NAME:-malla}"
DEFAULT_DB_USER="${DEFAULT_DB_USER:-malla}"
DEFAULT_DB_PASSWORD="${DEFAULT_DB_PASSWORD:-+SbU1LKHzUssEqgsarDXzPsQLvqIHMmm}"
DEFAULT_POSTGRES_DSN="${DEFAULT_POSTGRES_DSN:-postgresql://${DEFAULT_DB_USER}:${DEFAULT_DB_PASSWORD}@/${DEFAULT_DB_NAME}?host=/var/run/postgresql}"

usage() {
    cat <<'EOF'
Usage: sudo ./scripts/install_malla_instance.sh <sqlite|lite|postgres>

What it does:
  - installs missing system packages for deployment
  - clones or updates the Malla repository
  - creates .env using defaults mirrored from 10.5.0.71
  - lets you edit .env before startup
  - starts the application with Docker Compose

Optional environment variables:
  INSTALL_DIR   Target path for the repository (default: /opt/malla)
  REPO_URL      Repository URL to clone (default: upstream GitHub repo)
  RUN_AS_USER   Owner of the install directory
EOF
}

log() {
    printf '[install-malla] %s\n' "$*"
}

fail() {
    printf '[install-malla] ERROR: %s\n' "$*" >&2
    exit 1
}

run_as_target_user() {
    sudo -u "$RUN_AS_USER" "$@"
}

write_build_commit_file() {
    local commit_file="$INSTALL_DIR/BUILD_COMMIT"
    local build_commit

    build_commit="$(run_as_target_user git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || true)"
    [ -n "$build_commit" ] || build_commit="unknown"

    log "Writing build commit metadata to $commit_file"
    printf '%s\n' "$build_commit" >"$commit_file"
    chown "$RUN_AS_USER":"$RUN_AS_USER" "$commit_file"
}

require_root() {
    [ "$(id -u)" -eq 0 ] || fail "Run this script as root or via sudo"
}

package_available() {
    apt-cache show "$1" >/dev/null 2>&1
}

install_if_available() {
    local pkg
    for pkg in "$@"; do
        if package_available "$pkg"; then
            apt-get install -y "$pkg"
            return 0
        fi
    done

    return 1
}

normalize_backend() {
    case "$BACKEND" in
        sqlite|lite)
            BACKEND="sqlite"
            ;;
        postgres)
            ;;
        *)
            usage
            fail "Backend must be one of: sqlite, lite, postgres"
            ;;
    esac
}

install_base_packages() {
    export DEBIAN_FRONTEND=noninteractive
    log "Installing base packages"
    apt-get update
    apt-get install -y \
        ca-certificates \
        curl \
        git \
        rsync \
        docker.io

    install_if_available docker-compose-v2 docker-compose-plugin docker-compose || \
        fail "Unable to find a Docker Compose package"
    install_if_available docker-buildx docker-buildx-plugin || \
        log "Docker Buildx package not available, continuing without explicit install"

    systemctl enable --now docker

    if id "$RUN_AS_USER" >/dev/null 2>&1; then
        usermod -aG docker "$RUN_AS_USER" || true
    fi
}

install_postgres_packages() {
    export DEBIAN_FRONTEND=noninteractive
    log "Installing PostgreSQL packages"
    apt-get update
    apt-get install -y \
        postgresql \
        postgresql-contrib \
        postgresql-client \
        libpq-dev

    systemctl enable --now postgresql
}

ensure_repo() {
    local parent_dir
    parent_dir="$(dirname "$INSTALL_DIR")"

    mkdir -p "$parent_dir"
    chown -R "$RUN_AS_USER":"$RUN_AS_USER" "$parent_dir"

    if [ -d "$INSTALL_DIR/.git" ]; then
        log "Updating existing repository in $INSTALL_DIR"
        run_as_target_user git -C "$INSTALL_DIR" pull --ff-only
    elif [ -d "$INSTALL_DIR" ] && [ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
        log "Using existing source tree in $INSTALL_DIR"
    else
        log "Cloning repository into $INSTALL_DIR"
        run_as_target_user git clone "$REPO_URL" "$INSTALL_DIR"
    fi
}

write_env_file() {
    local env_file="$INSTALL_DIR/.env"
    local db_backend="$BACKEND"
    local postgres_dsn=""

    if [ "$db_backend" = "postgres" ]; then
        postgres_dsn="$DEFAULT_POSTGRES_DSN"
    fi

    log "Writing $env_file"
    cat >"$env_file" <<EOF
MALLA_NAME=$DEFAULT_MALLA_NAME
MALLA_SECRET_KEY=$DEFAULT_SECRET_KEY
MALLA_DEBUG=false
MALLA_WEB_PORT=$DEFAULT_WEB_PORT
MALLA_WEB_COMMAND=$DEFAULT_WEB_COMMAND
MALLA_MQTT_BROKER_ADDRESS=$DEFAULT_MQTT_BROKER
MALLA_MQTT_PORT=$DEFAULT_MQTT_PORT
MALLA_MQTT_USERNAME=$DEFAULT_MQTT_USERNAME
MALLA_MQTT_PASSWORD=$DEFAULT_MQTT_PASSWORD
MALLA_MQTT_TOPIC_PREFIX=$DEFAULT_MQTT_TOPIC_PREFIX
MALLA_MQTT_TOPIC_SUFFIX=$DEFAULT_MQTT_TOPIC_SUFFIX
MALLA_DEFAULT_CHANNEL_KEY=$DEFAULT_CHANNEL_KEYS
MALLA_DATABASE_BACKEND=$db_backend
MALLA_POSTGRES_DSN=$postgres_dsn
EOF

    chown "$RUN_AS_USER":"$RUN_AS_USER" "$env_file"
    chmod 600 "$env_file"
}

configure_postgres() {
    local hba_file

    log "Configuring PostgreSQL database and local auth"
    hba_file="$(sudo -u postgres psql -Atqc 'SHOW hba_file')"
    [ -n "$hba_file" ] || fail "Unable to determine pg_hba.conf path"

    if ! grep -Eq '^local[[:space:]]+all[[:space:]]+all[[:space:]]+scram-sha-256([[:space:]]|$)' "$hba_file"; then
        cp "$hba_file" "${hba_file}.bak.$(date +%s)"
        sed -i -E \
            "s/^local([[:space:]]+all[[:space:]]+all[[:space:]]+)peer([[:space:]]|$)/local\1scram-sha-256\2/" \
            "$hba_file"
        systemctl restart postgresql
    fi

    DB_NAME="$DEFAULT_DB_NAME" \
    DB_USER="$DEFAULT_DB_USER" \
    DB_PASSWORD="$DEFAULT_DB_PASSWORD" \
        "$INSTALL_DIR/scripts/create_postgres_db.sh"
}

maybe_edit_env() {
    local env_file="$INSTALL_DIR/.env"
    local answer

    printf '\nGenerated .env at %s\n' "$env_file"
    printf 'Backend: %s\n' "$BACKEND"
    printf 'You can edit MQTT credentials, secret key, and display name before startup.\n'

    if [ -t 0 ] && [ -t 1 ]; then
        if [ -n "${EDITOR:-}" ]; then
            read -r -p "Open .env in \$EDITOR now? [Y/n] " answer
            if [[ ! "$answer" =~ ^[Nn]$ ]]; then
                run_as_target_user "${EDITOR}" "$env_file"
            fi
        else
            printf 'No $EDITOR set. Edit %s manually if needed.\n' "$env_file"
        fi

        read -r -p "Continue with deployment? [Y/n] " answer
        if [[ "$answer" =~ ^[Nn]$ ]]; then
            log "Stopped before docker compose startup"
            exit 0
        fi
    fi
}

start_application() {
    write_build_commit_file
    log "Starting Malla with Docker Compose"
    cd "$INSTALL_DIR"
    docker compose \
        --env-file .env \
        -f docker-compose.yml \
        -f docker-compose.prod.yml \
        -f docker-compose.remote-build.yml \
        up -d --build
}

sync_mobile_bts_data() {
    log "Syncing mobile BTS data from public web sources"
    "$INSTALL_DIR/scripts/sync_mobile_bts.sh"
}

print_summary() {
    cat <<EOF

Install complete.

Repository: $INSTALL_DIR
Backend:    $BACKEND
Web UI:     http://$(hostname -I | awk '{print $1}'):${DEFAULT_WEB_PORT}

Useful commands:
  cd $INSTALL_DIR
  docker compose ps
  docker logs --tail 50 malla-malla-web-1
  docker logs --tail 50 malla-malla-capture-1
EOF
}

main() {
    require_root
    normalize_backend
    install_base_packages
    if [ "$BACKEND" = "postgres" ]; then
        install_postgres_packages
    fi
    ensure_repo
    if [ "$BACKEND" = "postgres" ]; then
        configure_postgres
    fi
    write_env_file
    maybe_edit_env
    start_application
    sync_mobile_bts_data
    print_summary
}

main "$@"
