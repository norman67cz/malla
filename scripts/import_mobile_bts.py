#!/usr/bin/env python3
"""Import Czech public mobile BTS sites for relevant 800/900 MHz bands.

Data source:
- public GPS-enabled search pages on gsmweb.cz

Filtering:
- LTE/NR rows with explicit band 800 or 900
- GSM rows whose BCCH/ARFCN falls into the GSM 900 ranges
"""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.request import Request, urlopen

from malla.config import get_config
from malla.database.connection import get_db_connection

USER_AGENT = "malla-bts-import/1.0 (+https://github.com/norman67cz/malla)"
SOURCE_NAME = "gsmweb.cz"


@dataclass(frozen=True)
class SourceDef:
    operator: str
    radio: str
    districts_url: str
    search_op: str
    seznam_key: str


SOURCES: tuple[SourceDef, ...] = (
    SourceDef(
        "O2",
        "LTE",
        "https://gsmweb.cz/seznamy/okresy.php?seznam=o2lte",
        "o2lte",
        "o2lte",
    ),
    SourceDef(
        "Vodafone",
        "LTE",
        "https://gsmweb.cz/seznamy/okresy.php?seznam=vflte",
        "vflte",
        "vflte",
    ),
    SourceDef(
        "T-Mobile",
        "LTE",
        "https://gsmweb.cz/seznamy/okresy.php?seznam=Tlte",
        "Tlte",
        "Tlte",
    ),
    SourceDef(
        "O2",
        "GSM",
        "https://gsmweb.cz/seznamy/okresy.php?seznam=o2",
        "eurotel",
        "o2",
    ),
    SourceDef(
        "Vodafone",
        "GSM",
        "https://gsmweb.cz/seznamy/okresy.php?seznam=vodafone",
        "oskar",
        "vodafone",
    ),
    SourceDef(
        "T-Mobile",
        "GSM",
        "https://gsmweb.cz/seznamy/okresy.php?seznam=tmobile",
        "paegas",
        "tmobile",
    ),
)


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response:
        raw = response.read()

    for encoding in ("cp1250", "windows-1250", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return " ".join(html.unescape(text).replace("\xa0", " ").split())


def parse_czech_date(value: str) -> str | None:
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def infer_gsm_band_from_bcch(bcch: int) -> int | None:
    if 1 <= bcch <= 124 or 975 <= bcch <= 1023:
        return 900
    return None


def get_district_codes(source: SourceDef) -> list[str]:
    page = fetch_html(source.districts_url)
    pattern = rf"/search\.php\?op={re.escape(source.search_op)}&amp;park=okres&amp;udaj=([A-Z]{{2}})&amp;gps=only"
    codes = sorted(set(re.findall(pattern, page)))
    return codes


def build_search_url(source: SourceDef, district_code: str) -> str:
    return (
        f"https://gsmweb.cz/search.php?op={source.search_op}"
        f"&park=okres&udaj={district_code}&gps=only&razeni=cid&smer=vzestupne"
    )


def parse_row_cells(row_html: str) -> list[str]:
    return re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)


def extract_coordinates(row_html: str) -> tuple[float, float] | None:
    row_html = html.unescape(row_html)
    match = re.search(r"[?&]x=([0-9.]+).*?[?&]y=([0-9.]+)", row_html)
    if not match:
        return None
    lon = float(match.group(1))
    lat = float(match.group(2))
    return lat, lon


def iter_sites_for_source(source: SourceDef):
    for district_code in get_district_codes(source):
        page_url = build_search_url(source, district_code)
        page = fetch_html(page_url)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.IGNORECASE | re.DOTALL)
        for row_html in rows:
            if "MAPA" not in row_html:
                continue
            coords = extract_coordinates(row_html)
            if not coords:
                continue
            cells = [strip_tags(cell) for cell in parse_row_cells(row_html)]
            if not cells:
                continue

            date_index = next(
                (idx for idx, cell in enumerate(cells) if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", cell)),
                None,
            )
            if date_index is None or date_index + 2 >= len(cells):
                continue

            location_text = cells[date_index + 2]
            latest_seen_date = parse_czech_date(cells[date_index])

            if source.radio == "LTE":
                band_text = next((cell for cell in cells if re.fullmatch(r"(LTE|NR)\s+\d+", cell)), None)
                if not band_text:
                    continue
                band_mhz = int(re.search(r"(\d+)$", band_text).group(1))
                if band_mhz not in (800, 900):
                    continue
            else:
                if date_index < 2:
                    continue
                try:
                    bcch = int(cells[date_index - 2])
                except ValueError:
                    continue
                band_mhz = infer_gsm_band_from_bcch(bcch)
                if band_mhz != 900:
                    continue

            frequency_window = "791-821 MHz" if band_mhz == 800 else "880-915 MHz"
            lat, lon = coords
            site_key = hashlib.sha1(
                f"{source.operator}|{source.radio}|{band_mhz}|{district_code}|{location_text}|{lat:.6f}|{lon:.6f}".encode("utf-8")
            ).hexdigest()

            yield {
                "site_key": site_key,
                "operator": source.operator,
                "radio": source.radio,
                "band_mhz": band_mhz,
                "frequency_window": frequency_window,
                "district_code": district_code,
                "location_text": location_text,
                "latitude": lat,
                "longitude": lon,
                "cell_count": 1,
                "latest_seen_date": latest_seen_date,
                "source": SOURCE_NAME,
                "source_url": page_url,
            }


def aggregate_sites(rows: list[dict]) -> list[dict]:
    aggregated: dict[str, dict] = {}
    for row in rows:
        current = aggregated.get(row["site_key"])
        if current is None:
            aggregated[row["site_key"]] = row
            continue

        current["cell_count"] += 1
        if row["latest_seen_date"] and (
            not current["latest_seen_date"] or row["latest_seen_date"] > current["latest_seen_date"]
        ):
            current["latest_seen_date"] = row["latest_seen_date"]
    return list(aggregated.values())


def ensure_table(cursor) -> None:
    backend = (os.getenv("MALLA_DATABASE_BACKEND") or get_config().database_backend).lower()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mobile_bts_sites (
            id BIGSERIAL PRIMARY KEY,
            site_key TEXT NOT NULL UNIQUE,
            operator TEXT NOT NULL,
            radio TEXT NOT NULL,
            band_mhz BIGINT NOT NULL,
            frequency_window TEXT NOT NULL,
            district_code TEXT,
            location_text TEXT NOT NULL,
            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,
            cell_count BIGINT NOT NULL DEFAULT 1,
            latest_seen_date TEXT,
            source TEXT NOT NULL,
            source_url TEXT,
            imported_at DOUBLE PRECISION NOT NULL
        )
        """
        if backend == "postgres"
        else """
        CREATE TABLE IF NOT EXISTS mobile_bts_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_key TEXT NOT NULL UNIQUE,
            operator TEXT NOT NULL,
            radio TEXT NOT NULL,
            band_mhz INTEGER NOT NULL,
            frequency_window TEXT NOT NULL,
            district_code TEXT,
            location_text TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            cell_count INTEGER NOT NULL DEFAULT 1,
            latest_seen_date TEXT,
            source TEXT NOT NULL,
            source_url TEXT,
            imported_at REAL NOT NULL
        )
        """
    )


def write_sites(sites: list[dict], truncate: bool) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    ensure_table(cursor)

    if truncate:
        cursor.execute("DELETE FROM mobile_bts_sites WHERE source = ?", (SOURCE_NAME,))

    imported_at = time.time()
    rows = [
        (
            site["site_key"],
            site["operator"],
            site["radio"],
            site["band_mhz"],
            site["frequency_window"],
            site["district_code"],
            site["location_text"],
            site["latitude"],
            site["longitude"],
            site["cell_count"],
            site["latest_seen_date"],
            site["source"],
            site["source_url"],
            imported_at,
        )
        for site in sites
    ]

    cursor.executemany(
        """
        INSERT INTO mobile_bts_sites (
            site_key, operator, radio, band_mhz, frequency_window, district_code,
            location_text, latitude, longitude, cell_count, latest_seen_date,
            source, source_url, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(site_key) DO UPDATE SET
            cell_count = excluded.cell_count,
            latest_seen_date = excluded.latest_seen_date,
            source_url = excluded.source_url,
            imported_at = excluded.imported_at
        """,
        rows,
    )

    conn.commit()
    conn.close()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Czech public mobile BTS sites")
    parser.add_argument("--truncate", action="store_true", help="Replace existing gsmweb.cz BTS rows")
    args = parser.parse_args()

    rows: list[dict] = []
    for source in SOURCES:
        rows.extend(iter_sites_for_source(source))

    aggregated = aggregate_sites(rows)
    count = write_sites(aggregated, truncate=args.truncate)
    print(f"Imported {count} BTS sites into mobile_bts_sites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
