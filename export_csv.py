"""PolluSense Data Export Tool.

Exports 15-minute aggregated records or raw 1-minute telemetry from SQLite
('data.db') to a standalone CSV file over any date/time window.
Useful for data analysis, MATLAB, Pandas, and IEEE paper evaluation.

Usage:
  # Export 15-min rolling mean data for a specific date range:
  python export_csv.py --start "2026-11-20" --end "2026-11-27" --out weekly_15min.csv

  # Export raw 1-minute telemetry for a specific day:
  python export_csv.py --table raw --start "2026-11-20 00:00:00" --end "2026-11-20 23:59:59" --out raw_day1.csv

  # Export all available 15-min data to CSV:
  python export_csv.py --all --out all_15min_records.csv
"""

import argparse
import csv
import json
import os
import sqlite3
import sys

DATA_DIR = os.path.expanduser("~/pollusense")
DB = os.path.join(DATA_DIR, "data.db")


def export_15min(db_path, start, end, out_path, all_data=False):
    con = sqlite3.connect(db_path)
    if all_data:
        query = "SELECT record FROM records_15min ORDER BY ts ASC"
        rows = con.execute(query).fetchall()
    elif start and end:
        query = "SELECT record FROM records_15min WHERE datetime_ist >= ? AND datetime_ist <= ? ORDER BY ts ASC"
        rows = con.execute(query, (start, end)).fetchall()
    else:
        query = "SELECT record FROM records_15min ORDER BY ts DESC LIMIT 100"
        rows = con.execute(query).fetchall()

    if not rows:
        print("No 15-minute records found matching criteria.")
        return

    records = [json.loads(r[0]) for r in rows]
    fields = list(records[0].keys())

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    print(f"Successfully exported {len(records)} 15-minute records to {out_path}")


def export_raw(db_path, start, end, out_path, all_data=False):
    con = sqlite3.connect(db_path)
    if all_data:
        query = "SELECT payload, datetime_ist, datetime_utc FROM raw_1min ORDER BY ts ASC"
        rows = con.execute(query).fetchall()
    elif start and end:
        query = "SELECT payload, datetime_ist, datetime_utc FROM raw_1min WHERE datetime_ist >= ? AND datetime_ist <= ? ORDER BY ts ASC"
        rows = con.execute(query, (start, end)).fetchall()
    else:
        query = "SELECT payload, datetime_ist, datetime_utc FROM raw_1min ORDER BY ts DESC LIMIT 100"
        rows = con.execute(query).fetchall()

    if not rows:
        print("No raw records found matching criteria.")
        return

    flat_records = []
    for payload_str, dt_ist, dt_utc in rows:
        try:
            d = json.loads(payload_str)
            d["datetime_ist"] = dt_ist
            d["datetime_utc"] = dt_utc
            flat_records.append(d)
        except Exception:
            continue

    if not flat_records:
        print("No valid JSON raw records to export.")
        return

    fields = list(flat_records[0].keys())
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flat_records)

    print(f"Successfully exported {len(flat_records)} raw records to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="PolluSense CSV Exporter")
    parser.add_argument(
        "--table",
        choices=["15min", "raw"],
        default="15min",
        help="Table to export (default: 15min)",
    )
    parser.add_argument(
        "--start",
        help="Start datetime in IST (e.g. '2026-11-20' or '2026-11-20 00:00:00')",
    )
    parser.add_argument(
        "--end",
        help="End datetime in IST (e.g. '2026-11-27' or '2026-11-27 23:59:59')",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all recorded data without date filter",
    )
    parser.add_argument(
        "--out",
        default="pollusense_export.csv",
        help="Output CSV file path (default: pollusense_export.csv)",
    )
    parser.add_argument(
        "--db", default=DB, help=f"Path to SQLite database (default: {DB})"
    )

    args = parser.parse_args()

    if not os.path.isfile(args.db):
        print(f"Error: Database {args.db} not found.")
        sys.exit(1)

    if args.table == "15min":
        export_15min(args.db, args.start, args.end, args.out, args.all)
    else:
        export_raw(args.db, args.start, args.end, args.out, args.all)


if __name__ == "__main__":
    main()
