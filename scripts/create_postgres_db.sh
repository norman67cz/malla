#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${DB_NAME:-malla}"
DB_USER="${DB_USER:-malla}"
DB_PASSWORD="${DB_PASSWORD:?DB_PASSWORD must be set}"

sudo -u postgres psql <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
    END IF;
END
\$\$;
SQL

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1 || \
    sudo -u postgres createdb --owner="${DB_USER}" "${DB_NAME}"

echo "PostgreSQL database '${DB_NAME}' and user '${DB_USER}' are ready."
