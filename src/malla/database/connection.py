"""
Database connection management for Meshtastic Mesh Health Web UI.
"""

import logging
import os
import sqlite3

# Prefer configuration loader over environment variables
from malla.config import get_config

logger = logging.getLogger(__name__)


def get_db_connection() -> sqlite3.Connection:
    """
    Get a connection to the SQLite database with proper concurrency configuration.

    Returns:
        sqlite3.Connection: Database connection with row factory set and WAL mode enabled
    """
    # Resolve DB path:
    # 1. Explicit override via `MALLA_DATABASE_FILE` env-var (handy for scripts)
    # 2. Value from YAML configuration
    # 3. Fallback to hard-coded default

    db_path: str = (
        os.getenv("MALLA_DATABASE_FILE")
        or get_config().database_file
        or "meshtastic_history.db"
    )

    try:
        conn = sqlite3.connect(
            db_path, timeout=30.0
        )  # 30 second timeout for busy database
        conn.row_factory = sqlite3.Row  # Enable column access by name

        # Configure SQLite for better concurrency
        cursor = conn.cursor()

        # Enable WAL mode for better concurrent read/write performance
        cursor.execute("PRAGMA journal_mode=WAL")

        # Set synchronous to NORMAL for better performance while maintaining safety
        cursor.execute("PRAGMA synchronous=NORMAL")

        # Set busy timeout to handle concurrent access
        cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds

        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys=ON")

        # Optimize for read performance
        cursor.execute("PRAGMA cache_size=10000")  # 10MB cache
        cursor.execute("PRAGMA temp_store=MEMORY")

        # ------------------------------------------------------------------
        # Lightweight schema migrations – run once per connection.
        # ------------------------------------------------------------------
        try:
            _ensure_schema_migrations(cursor, db_path)
        except Exception as e:
            logger.warning(f"Schema migration check failed: {e}")

        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


def init_database() -> None:
    """
    Initialize the database connection and verify it's accessible.
    This function is called during application startup.
    """
    # Resolve DB path:
    # 1. Explicit override via `MALLA_DATABASE_FILE` env-var (handy for scripts)
    # 2. Value from YAML configuration
    # 3. Fallback to hard-coded default

    db_path: str = (
        os.getenv("MALLA_DATABASE_FILE")
        or get_config().database_file
        or "meshtastic_history.db"
    )

    logger.info(f"Initializing database connection to: {db_path}")

    try:
        # Test the connection
        conn = get_db_connection()

        # Test a simple query to verify the database is accessible
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]

        # Check and log the journal mode
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        conn.close()

        logger.info(
            f"Database connection successful - found {table_count} tables, journal_mode: {journal_mode}"
        )

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        # Don't raise the exception - let the app start anyway
        # The database might not exist yet or be created by another process


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


_SCHEMA_MIGRATIONS_DONE: set[tuple[str, str]] = set()


def _ensure_schema_migrations(cursor: sqlite3.Cursor, db_path: str) -> None:
    """Run any idempotent schema updates that the application depends on.

    Currently this checks that ``node_info`` has the metadata columns used by
    the UI (``primary_channel``, ``lora_modem_preset``,
    ``lora_modem_preset_updated_at``) so queries do not fail when the database
    was created with an older version of the schema.

    The function is **safe** to run repeatedly – it will only attempt each
    migration once per Python process and each individual migration is
    guarded with a try/except that ignores the *duplicate column* error.
    """

    global _SCHEMA_MIGRATIONS_DONE  # pylint: disable=global-statement
    migration_key = (db_path, "node_info_metadata")

    # Quickly short-circuit if we've already handled migrations in this process
    if migration_key in _SCHEMA_MIGRATIONS_DONE:
        return

    try:
        # Check whether the column already exists
        cursor.execute("PRAGMA table_info(node_info)")
        columns = [row[1] for row in cursor.fetchall()]

        if "primary_channel" not in columns:
            cursor.execute("ALTER TABLE node_info ADD COLUMN primary_channel TEXT")
        if "lora_modem_preset" not in columns:
            cursor.execute("ALTER TABLE node_info ADD COLUMN lora_modem_preset TEXT")
        if "lora_modem_preset_updated_at" not in columns:
            cursor.execute(
                "ALTER TABLE node_info ADD COLUMN lora_modem_preset_updated_at REAL"
            )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_node_primary_channel ON node_info(primary_channel)"
        )
        logging.info("Ensured node_info metadata columns exist via auto-migration")

        _SCHEMA_MIGRATIONS_DONE.add(migration_key)
    except sqlite3.OperationalError as exc:
        # Ignore errors about duplicate columns in race situations – another
        # process may have altered the table first.
        if "duplicate column name" in str(exc).lower():
            _SCHEMA_MIGRATIONS_DONE.add(migration_key)
        else:
            raise
