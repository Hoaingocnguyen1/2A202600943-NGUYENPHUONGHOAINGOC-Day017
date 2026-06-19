"""Extension #4 — idempotent, date-windowed backfill.

    python bonus/backfill.py --date 2026-06-01      # one day
    python bonus/backfill.py                          # all days (full rebuild of the window)

The graded main.py rebuilds the warehouse from scratch each run (safe, but it can't
backfill a single day). This adds a `--date` window and makes re-runs idempotent:
re-running the same date produces the SAME Silver rows — no duplication (README ext.
#4, deck §14).

How idempotency is achieved: Silver is keyed by day. A backfill for date D does
`DELETE FROM silver WHERE created_at = D` then re-inserts D's deduplicated, validated
rows. So replaying D (or a crashed/retried job) converges to the same state instead
of appending duplicates — the core property a safe backfill needs. Bad rows still go
to quarantine; dedup-on-order_id still happens per day.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import config
from pipeline.validate import validate

BACKFILL_WAREHOUSE = config.ROOT / "backfill_warehouse.duckdb"
SILVER = "silver_orders_bf"


def _ensure_silver(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""CREATE TABLE IF NOT EXISTS {SILVER} (
                order_id INTEGER, user_id VARCHAR, product VARCHAR,
                amount DOUBLE, status VARCHAR, created_at VARCHAR)"""
    )


def backfill(con: duckdb.DuckDBPyConnection, date: str | None = None, raw_csv: Path | None = None) -> dict:
    """Validate + dedup + idempotently upsert the rows for `date` (or all dates)."""
    _ensure_silver(con)
    raw = pd.read_csv(raw_csv or config.RAW_CSV, dtype=str)
    if date is not None:
        raw = raw[raw["created_at"] == date].reset_index(drop=True)

    clean, bad = validate(raw)
    # dedup on the natural key, keeping the latest created_at (same rule as transform.py)
    if len(clean):
        clean = (clean.sort_values("created_at")
                      .drop_duplicates("order_id", keep="last")
                      .reset_index(drop=True))

    # --- idempotent upsert: replace the partition(s) this backfill owns ---
    if date is not None:
        con.execute(f"DELETE FROM {SILVER} WHERE created_at = ?", [date])
    elif len(clean):
        con.execute(f"DELETE FROM {SILVER} WHERE created_at IN "
                    f"({','.join('?' * clean['created_at'].nunique())})",
                    list(clean["created_at"].unique()))
    if len(clean):
        con.register("clean_bf", clean)
        con.execute(f"INSERT INTO {SILVER} SELECT order_id, user_id, product, amount, status, created_at FROM clean_bf")

    (total,) = con.execute(f"SELECT count(*) FROM {SILVER}").fetchone()
    return {"date": date or "ALL", "validated": len(clean), "quarantined": len(bad),
            "silver_total": total}


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description="Idempotent date-windowed backfill")
    ap.add_argument("--date", help="YYYY-MM-DD to backfill (omit = all dates)")
    args = ap.parse_args(argv)

    con = duckdb.connect(str(BACKFILL_WAREHOUSE))
    try:
        first = backfill(con, args.date)
        second = backfill(con, args.date)        # prove re-run does not duplicate
        print("=== Ext #4: idempotent date-windowed backfill ===")
        print(f"  window              : {first['date']}")
        print(f"  validated rows      : {first['validated']}  (quarantined {first['quarantined']})")
        print(f"  silver after run 1  : {first['silver_total']}")
        print(f"  silver after run 2  : {second['silver_total']}  "
              f"({'idempotent — no duplication' if first['silver_total'] == second['silver_total'] else 'CHANGED!'})")
        return second
    finally:
        con.close()


if __name__ == "__main__":
    main()
