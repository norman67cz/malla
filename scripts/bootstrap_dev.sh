#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJECT_ROOT/.uv-cache}"

missing=0

check_cmd() {
    local cmd="$1"
    local label="$2"
    if command -v "$cmd" >/dev/null 2>&1; then
        printf '[ok] %s\n' "$label"
    else
        printf '[missing] %s\n' "$label"
        missing=1
    fi
}

check_python_313() {
    if command -v python3.13 >/dev/null 2>&1; then
        printf '[ok] python3.13\n'
    elif command -v uv >/dev/null 2>&1 && UV_CACHE_DIR="$UV_CACHE_DIR" uv python find 3.13 >/dev/null 2>&1; then
        printf '[ok] python3.13 (managed by uv)\n'
    else
        printf '[missing] python3.13\n'
        missing=1
    fi
}

check_optional_cmd() {
    local cmd="$1"
    local label="$2"
    if command -v "$cmd" >/dev/null 2>&1; then
        printf '[ok] %s\n' "$label"
    else
        printf '[optional] %s\n' "$label"
    fi
}

check_sync_tool() {
    if command -v rsync >/dev/null 2>&1; then
        printf '[ok] rsync\n'
    elif command -v scp >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then
        printf '[ok] scp + tar fallback\n'
    else
        printf '[missing] rsync or scp + tar\n'
        missing=1
    fi
}

check_optional_docker_compose() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        printf '[ok] docker compose\n'
    else
        printf '[optional] docker compose\n'
    fi
}

printf 'Project root: %s\n' "$PROJECT_ROOT"
printf 'Remote Docker host: %s\n' "${DEPLOY_HOST:-10.5.0.71}"

check_cmd git "git"
check_cmd ssh "ssh"
check_sync_tool
check_cmd make "make"
check_cmd uv "uv"
check_python_313
check_optional_cmd tar "tar"
check_optional_docker_compose

printf '\nExpected local workflow:\n'
printf '  1. cp env.example .env\n'
printf '  2. Edit .env with MQTT and secret values\n'
printf '  3. uv sync --dev\n'
printf '  4. uv run pytest\n'
printf '  5. ./scripts/deploy_remote.sh\n'

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    printf '\n[info] Local .env is missing. Create it from env.example before running locally.\n'
fi

if [[ "$missing" -ne 0 ]]; then
    printf '\nEnvironment is not ready yet.\n'
    exit 1
fi

printf '\nEnvironment checks passed.\n'
