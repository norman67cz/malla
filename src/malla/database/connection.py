"""
Database connection management for Meshtastic Mesh Health Web UI.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any

from malla.config import get_config

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional until PostgreSQL is enabled
    psycopg = None
    dict_row = None


class RowCompat:
    """Row object that supports both index and key access like sqlite3.Row."""

    def __init__(self, data: dict[str, Any], columns: list[str]):
        self._data = data
        self._columns = columns

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._data[self._columns[key]]
        return self._data[key]

    def keys(self) -> list[str]:
        return list(self._columns)

    def items(self):
        for column in self._columns:
            yield column, self._data[column]

    def values(self):
        for column in self._columns:
            yield self._data[column]

    def __iter__(self):
        for column in self._columns:
            yield self._data[column]

    def __len__(self) -> int:
        return len(self._columns)


class PostgresCursorWrapper:
    """Cursor adapter to keep the existing sqlite-style API working."""

    def __init__(self, cursor):
        self._cursor = cursor
        self._columns: list[str] = []

    def execute(self, query: str, params: Any = None):
        adapted_query = _adapt_sql_for_postgres(query)
        self._cursor.execute(adapted_query, params)
        self._refresh_columns()
        return self

    def executemany(self, query: str, params_seq: Any):
        adapted_query = _adapt_sql_for_postgres(query)
        self._cursor.executemany(adapted_query, params_seq)
        self._refresh_columns()
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return RowCompat(row, self._columns)

    def fetchall(self):
        return [RowCompat(row, self._columns) for row in self._cursor.fetchall()]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def _refresh_columns(self) -> None:
        self._columns = [desc.name for desc in self._cursor.description or []]


class PostgresConnectionWrapper:
    """Connection adapter that exposes sqlite-like cursors."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return PostgresCursorWrapper(self._conn.cursor(row_factory=dict_row))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def get_db_connection():
    """
    Get a database connection for the configured backend.

    Returns a sqlite3 connection for the current default backend and a wrapper
    with sqlite-like row semantics for PostgreSQL.
    """

    cfg = get_config()
    backend = (os.getenv("MALLA_DATABASE_BACKEND") or cfg.database_backend).lower()

    if backend == "postgres":
        return _get_postgres_connection(cfg.postgres_dsn)

    return _get_sqlite_connection(
        os.getenv("MALLA_DATABASE_FILE") or cfg.database_file or "meshtastic_history.db"
    )


def _get_sqlite_connection(db_path: str) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row

        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA cache_size=10000")
        cursor.execute("PRAGMA temp_store=MEMORY")

        try:
            _ensure_sqlite_schema_migrations(cursor, db_path)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Schema migration check failed: {e}")

        return conn
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to connect to SQLite database: {e}")
        raise


def _get_postgres_connection(dsn: str | None):
    if not dsn:
        raise RuntimeError(
            "PostgreSQL backend selected but no postgres_dsn / MALLA_POSTGRES_DSN configured"
        )
    if psycopg is None:
        raise RuntimeError(
            "PostgreSQL backend selected but psycopg is not installed in this environment"
        )

    try:
        conn = psycopg.connect(dsn)
        conn.autocommit = False
        wrapper = PostgresConnectionWrapper(conn)

        try:
            _ensure_postgres_schema_migrations(wrapper.cursor())
        except Exception as e:  # noqa: BLE001
            wrapper.rollback()
            logger.warning(f"Schema migration check failed: {e}")

        return wrapper
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to connect to PostgreSQL database: {e}")
        raise


def init_database() -> None:
    """Initialize the configured database connection and verify it's accessible."""

    cfg = get_config()
    backend = (os.getenv("MALLA_DATABASE_BACKEND") or cfg.database_backend).lower()
    target = (
        os.getenv("MALLA_POSTGRES_DSN") or cfg.postgres_dsn
        if backend == "postgres"
        else os.getenv("MALLA_DATABASE_FILE") or cfg.database_file
    )

    logger.info(f"Initializing database connection to: {target} ({backend})")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if backend == "postgres":
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
            )
            table_count = cursor.fetchone()[0]
            journal_mode = "postgres"
        else:
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]

        conn.close()

        logger.info(
            f"Database connection successful - found {table_count} tables, mode: {journal_mode}"
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Database initialization failed: {e}")


_SCHEMA_MIGRATIONS_DONE: set[tuple[str, str]] = set()


def _ensure_sqlite_schema_migrations(cursor: sqlite3.Cursor, db_path: str) -> None:
    migration_key = (db_path, "node_info_metadata")
    if migration_key in _SCHEMA_MIGRATIONS_DONE:
        return

    try:
        cursor.execute("PRAGMA table_info(node_info)")
        columns = [row[1] for row in cursor.fetchall()]

        if "primary_channel" not in columns:
            cursor.execute("ALTER TABLE node_info ADD COLUMN primary_channel TEXT")
        if "firmware_version" not in columns:
            cursor.execute("ALTER TABLE node_info ADD COLUMN firmware_version TEXT")
        if "firmware_version_source" not in columns:
            cursor.execute(
                "ALTER TABLE node_info ADD COLUMN firmware_version_source TEXT"
            )
        if "firmware_version_updated_at" not in columns:
            cursor.execute(
                "ALTER TABLE node_info ADD COLUMN firmware_version_updated_at REAL"
            )
        if "lora_modem_preset" not in columns:
            cursor.execute("ALTER TABLE node_info ADD COLUMN lora_modem_preset TEXT")
        if "lora_modem_preset_updated_at" not in columns:
            cursor.execute(
                "ALTER TABLE node_info ADD COLUMN lora_modem_preset_updated_at REAL"
            )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_node_primary_channel ON node_info(primary_channel)"
        )
        _SCHEMA_MIGRATIONS_DONE.add(migration_key)
    except sqlite3.OperationalError as exc:
        if "duplicate column name" in str(exc).lower():
            _SCHEMA_MIGRATIONS_DONE.add(migration_key)
        else:
            raise


def _ensure_postgres_schema_migrations(cursor) -> None:
    migration_key = ("postgres", "schema_compat")
    if migration_key in _SCHEMA_MIGRATIONS_DONE:
        return

    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ('node_info', 'packet_history')
        """
    )
    existing_tables = {row["table_name"] for row in cursor.fetchall()}

    # Fresh PostgreSQL installs start with an empty schema. The actual table
    # bootstrap is owned by mqtt_capture.init_database(); skip compatibility
    # migrations until the core tables exist.
    if "node_info" not in existing_tables or "packet_history" not in existing_tables:
        cursor.connection.commit()
        return

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'node_info'
        """
    )
    columns = [row["column_name"] for row in cursor.fetchall()]

    if "primary_channel" not in columns:
        cursor.execute("ALTER TABLE node_info ADD COLUMN primary_channel TEXT")
    if "firmware_version" not in columns:
        cursor.execute("ALTER TABLE node_info ADD COLUMN firmware_version TEXT")
    if "firmware_version_source" not in columns:
        cursor.execute("ALTER TABLE node_info ADD COLUMN firmware_version_source TEXT")
    if "firmware_version_updated_at" not in columns:
        cursor.execute(
            "ALTER TABLE node_info ADD COLUMN firmware_version_updated_at DOUBLE PRECISION"
        )
    if "lora_modem_preset" not in columns:
        cursor.execute("ALTER TABLE node_info ADD COLUMN lora_modem_preset TEXT")
    if "lora_modem_preset_updated_at" not in columns:
        cursor.execute("ALTER TABLE node_info ADD COLUMN lora_modem_preset_updated_at DOUBLE PRECISION")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_primary_channel ON node_info(primary_channel)"
    )

    # Older SQLite -> PostgreSQL migrations created packet_history.id as BIGINT
    # without an attached sequence/default. Ensure inserts continue to work.
    cursor.execute(
        """
        SELECT column_default, is_identity
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'packet_history'
          AND column_name = 'id'
        """
    )
    id_default_row = cursor.fetchone()
    id_default = id_default_row["column_default"] if id_default_row else None
    is_identity = (
        str(id_default_row["is_identity"]).upper() == "YES" if id_default_row else False
    )
    if not is_identity and (not id_default or "nextval(" not in str(id_default)):
        cursor.execute(
            "CREATE SEQUENCE IF NOT EXISTS packet_history_id_seq OWNED BY packet_history.id"
        )
        cursor.execute(
            """
            SELECT setval(
                'packet_history_id_seq',
                GREATEST(COALESCE((SELECT MAX(id) FROM packet_history), 0), 1),
                true
            )
            """
        )
        cursor.execute(
            """
            ALTER TABLE packet_history
            ALTER COLUMN id SET DEFAULT nextval('packet_history_id_seq')
            """
        )

    cursor.connection.commit()
    _SCHEMA_MIGRATIONS_DONE.add(migration_key)


def _adapt_sql_for_postgres(query: str) -> str:
    """Translate a small subset of SQLite syntax used by the web layer."""

    adapted = query

    # Parameter style
    adapted = adapted.replace("?", "%s")

    # SQLite metadata access
    adapted = adapted.replace(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'",
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'",
    )
    adapted = adapted.replace(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='node_info'",
        "SELECT table_name AS name FROM information_schema.tables WHERE table_schema = 'public' AND table_name='node_info'",
    )

    # Common aggregation/text functions
    adapted = adapted.replace(
        "GROUP_CONCAT(DISTINCT gateway_id) AS gateways",
        "STRING_AGG(DISTINCT gateway_id::text, ',') AS gateways",
    )

    # SQLite commonly stores booleans as 0/1. PostgreSQL uses a real boolean
    # type, so normalize the most common read-path predicates.
    adapted = adapted.replace(
        "processed_successfully = 1",
        "processed_successfully IS TRUE",
    )
    adapted = adapted.replace(
        "processed_successfully=1",
        "processed_successfully IS TRUE",
    )

    adapted = re.sub(
        r"printf\('!%08x',\s*([^)]+)\)",
        r"('!' || LPAD(LOWER(TO_HEX(\1)), 8, '0'))",
        adapted,
    )

    # Common SQLite time helpers used in read queries
    adapted = adapted.replace(
        "strftime('%s', 'now')",
        "EXTRACT(EPOCH FROM NOW())",
    )
    adapted = adapted.replace(
        "strftime('%H', datetime(timestamp, 'unixepoch'))",
        "TO_CHAR(TO_TIMESTAMP(timestamp) AT TIME ZONE 'UTC', 'HH24')",
    )

    adapted = re.sub(
        r"datetime\(([^,]+), 'unixepoch'\)",
        r"TO_CHAR(TO_TIMESTAMP(\1) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')",
        adapted,
    )
    adapted = adapted.replace(
        "datetime(COALESCE(stats.last_packet_time, ni.last_updated), 'unixepoch')",
        "TO_CHAR(TO_TIMESTAMP(COALESCE(stats.last_packet_time, ni.last_updated)) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')",
    )
    adapted = adapted.replace(
        "datetime(COALESCE(stats.last_packet, ni.last_updated), 'unixepoch')",
        "TO_CHAR(TO_TIMESTAMP(COALESCE(stats.last_packet, ni.last_updated)) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')",
    )

    return adapted
