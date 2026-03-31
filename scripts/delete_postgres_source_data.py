#!/usr/bin/env python3
"""Delete PostgreSQL packet data for a selected MQTT source and time range.

Examples:
    python3 scripts/delete_postgres_source_data.py --source pl --to 2026-03-01
    python3 scripts/delete_postgres_source_data.py --source pl --from 2026-03-01
    python3 scripts/delete_postgres_source_data.py --source pl --from 2026-03-01 --to 2026-03-15
    python3 scripts/delete_postgres_source_data.py --source pl --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class Bound:
    value: float
    operator: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete packet_history rows for one MQTT source from PostgreSQL, "
            "optionally limited by --from / --to timestamps."
        ),
        epilog=(
            "Examples:\n"
            "  python3 scripts/delete_postgres_source_data.py --source pl --dry-run\n"
            "  python3 scripts/delete_postgres_source_data.py --source pl --to 2026-03-01\n"
            "  python3 scripts/delete_postgres_source_data.py --source pl --from 2026-03-01\n"
            "  python3 scripts/delete_postgres_source_data.py --source pl --from 2026-03-01 --to 2026-03-15\n"
            "\n"
            "Date handling:\n"
            "  --from 2026-03-01           means from 2026-03-01 00:00:00 inclusive\n"
            "  --to   2026-03-15           means through the end of 2026-03-15\n"
            "  --from 2026-03-01T12:00:00  means from that exact timestamp\n"
            "  --to   2026-03-15T18:30:00  means through that exact timestamp\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--source",
        required=True,
        help="MQTT source name to delete, e.g. cz, pl, hu, official",
    )
    parser.add_argument(
        "--from",
        dest="from_ts",
        help="Inclusive lower bound in ISO format, e.g. 2026-03-01 or 2026-03-01T12:00:00",
    )
    parser.add_argument(
        "--to",
        dest="to_ts",
        help="Inclusive upper bound in ISO format, e.g. 2026-03-15 or 2026-03-15T18:30:00",
    )
    parser.add_argument(
        "--postgres-dsn",
        help="Explicit PostgreSQL DSN. If omitted, uses config/env resolution from Malla.",
    )
    parser.add_argument(
        "--config-file",
        help="Optional config.yaml path for resolving PostgreSQL DSN.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show how many rows would be deleted.",
    )
    return parser.parse_args()


def resolve_postgres_dsn(explicit_dsn: str | None, config_file: str | None) -> str:
    if explicit_dsn:
        return explicit_dsn
    env_dsn = os.getenv("MALLA_POSTGRES_DSN")
    if env_dsn:
        return env_dsn

    config_path = Path(config_file) if config_file else DEFAULT_CONFIG_FILE
    if config_path.is_file():
        data = yaml.safe_load(config_path.read_text()) or {}
        dsn = data.get("postgres_dsn")
        if dsn:
            return str(dsn)

    raise RuntimeError(
        "No PostgreSQL DSN available. Pass --postgres-dsn or configure postgres_dsn / MALLA_POSTGRES_DSN."
    )


def parse_bound(raw_value: str, *, is_upper: bool) -> Bound:
    """Parse ISO date/datetime to UNIX timestamp bound.

    Rules:
    - date-only `YYYY-MM-DD`
      - --from => inclusive start of day
      - --to   => exclusive start of following day
    - datetime
      - --from => inclusive >= timestamp
      - --to   => inclusive <= timestamp
    """
    raw_value = raw_value.strip()
    if not raw_value:
        raise ValueError("Empty bound value")

    try:
        parsed_dt = datetime.fromisoformat(raw_value)
        has_time = "T" in raw_value or " " in raw_value
    except ValueError:
        parsed_date = date.fromisoformat(raw_value)
        has_time = False
        parsed_dt = datetime.combine(parsed_date, time.min)

    if not has_time and is_upper:
        next_day = parsed_dt + timedelta(days=1)
        return Bound(value=next_day.timestamp(), operator="<")

    return Bound(
        value=parsed_dt.timestamp(),
        operator="<=" if is_upper else ">=",
    )


def build_where_clause(source: str, from_ts: str | None, to_ts: str | None) -> tuple[str, list[Any]]:
    conditions = ["mqtt_source = %s"]
    params: list[Any] = [source]

    if from_ts:
        bound = parse_bound(from_ts, is_upper=False)
        conditions.append(f"timestamp {bound.operator} %s")
        params.append(bound.value)

    if to_ts:
        bound = parse_bound(to_ts, is_upper=True)
        conditions.append(f"timestamp {bound.operator} %s")
        params.append(bound.value)

    return " AND ".join(conditions), params


def count_matching_rows(conn: Any, where_clause: str, params: list[Any]) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM packet_history WHERE {where_clause}", params)
        return int(cur.fetchone()[0])


def delete_matching_rows(conn: Any, where_clause: str, params: list[Any]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM packet_history WHERE {where_clause}",
            params,
        )
        return int(cur.rowcount)


def delete_orphaned_nodes(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM node_info ni
            WHERE NOT EXISTS (
                SELECT 1 FROM packet_history ph
                WHERE ph.from_node_id = ni.node_id OR ph.to_node_id = ni.node_id
            )
            """
        )
        return int(cur.rowcount)


def main() -> None:
    args = parse_args()
    import psycopg

    dsn = resolve_postgres_dsn(args.postgres_dsn, args.config_file)
    where_clause, params = build_where_clause(args.source, args.from_ts, args.to_ts)

    with psycopg.connect(dsn) as conn:
        conn.autocommit = False

        packets_to_delete = count_matching_rows(conn, where_clause, params)

        print(f"Source: {args.source}")
        print(f"Where:  {where_clause}")
        print(f"Rows matching packet_history delete: {packets_to_delete}")

        if args.dry_run:
            print("Dry run only, no data deleted.")
            return

        deleted_packets = delete_matching_rows(conn, where_clause, params)
        deleted_nodes = delete_orphaned_nodes(conn)
        conn.commit()

        print(f"Deleted packet_history rows: {deleted_packets}")
        print(f"Deleted orphaned node_info rows: {deleted_nodes}")


if __name__ == "__main__":
    main()
