#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-10.5.0.71}"
DEPLOY_USER="${DEPLOY_USER:-}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/malla}"
SSH_TARGET="${DEPLOY_USER:+${DEPLOY_USER}@}${DEPLOY_HOST}"
BUILD_COMMIT="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD)"

if ! command -v ssh >/dev/null 2>&1; then
    echo "ssh is required"
    exit 1
fi

echo "Syncing project to ${SSH_TARGET}:${DEPLOY_PATH}"
ssh "$SSH_TARGET" "mkdir -p '$DEPLOY_PATH'"

if command -v rsync >/dev/null 2>&1; then
    rsync \
        --archive \
        --compress \
        --delete \
        --exclude ".git/" \
        --exclude ".env" \
        --exclude ".venv/" \
        --exclude ".pytest_cache/" \
        --exclude "__pycache__/" \
        --exclude "htmlcov/" \
        --exclude "dist/" \
        --exclude "build/" \
        "$PROJECT_ROOT"/ "$SSH_TARGET:$DEPLOY_PATH/"
elif command -v tar >/dev/null 2>&1; then
    tar \
        --exclude=".git" \
        --exclude=".env" \
        --exclude=".venv" \
        --exclude=".pytest_cache" \
        --exclude="__pycache__" \
        --exclude="htmlcov" \
        --exclude="dist" \
        --exclude="build" \
        -C "$PROJECT_ROOT" \
        -czf - . | ssh "$SSH_TARGET" "tar -xzf - -C '$DEPLOY_PATH'"
else
    echo "Either rsync or tar is required for deployment"
    exit 1
fi

ssh "$SSH_TARGET" "printf '%s\n' '$BUILD_COMMIT' > '$DEPLOY_PATH/BUILD_COMMIT'"

echo "Rebuilding containers on ${SSH_TARGET}"
ssh "$SSH_TARGET" "
    set -euo pipefail
    cd '$DEPLOY_PATH'
    if [ ! -f .env ]; then
        cp env.example .env
        echo 'Created .env from env.example on the remote host.'
        echo 'Fill in MQTT and secret values, then run the deploy again.'
        exit 2
    fi
    docker compose \
        -f docker-compose.yml \
        -f docker-compose.prod.yml \
        -f docker-compose.remote-build.yml \
        up -d --build
"

echo "Remote deploy completed."
