"""Prints products whose labelled calories disagree with their macros by more than 20%.

Usage (from the repo root, after scripts/setup_db.py):
    python scripts/audit_data.py

Reads the nutrition_audit view (see schema.sql), which compares labelled calories with
4*protein + 4*carbs + 9*fat. Flagged rows are sorted by percent error, largest first. The
source is the data file each name loads from under setup_db.py's merge rules (the database
doesn't record it); rows that are in no data file show as "database only".
"""
import contextlib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db
import setup_db

FLAGGED_QUERY = """
SELECT name, location, category, calories, protein, carbs, fat, atwater_kcal, kcal_difference, percent_error
FROM nutrition_audit
WHERE flagged
ORDER BY percent_error DESC NULLS FIRST, name;
"""


def source_by_name():
    """The data file each product name loads from (later, higher-priority sources win)."""
    with contextlib.redirect_stdout(io.StringIO()):
        sources = setup_db.read_sources(with_seeds=True, with_trader_joes=True)
    winners = {}
    for label, rows in sources:
        for row in rows:
            winners[row["name"]] = label
    return winners


def fmt(value):
    return "-" if value is None else f"{float(value):g}"


def main():
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(*) FILTER (WHERE flagged) FROM nutrition_audit;")
            total, flagged_count = cur.fetchone()
            cur.execute(FLAGGED_QUERY)
            rows = cur.fetchall()
    finally:
        conn.close()

    sources = source_by_name()
    print(f"{flagged_count} of {total} products flagged (labelled calories off from 4P + 4C + 9F by more than 20%)\n")
    if not rows:
        return
    header = (f"{'error':>7}  {'label':>6}  {'atwater':>7}  {'diff':>7}  {'P':>5} {'C':>5} {'F':>5}  "
              f"{'name':<42} {'category':<13} source")
    print(header)
    print("-" * len(header))
    for name, location, category, calories, protein, carbs, fat, atwater, difference, error in rows:
        source = sources.get(name, "database only")
        print(f"{fmt(error) + '%':>7}  {fmt(calories):>6}  {fmt(atwater):>7}  {float(difference):>+7g}  "
              f"{fmt(protein):>5} {fmt(carbs):>5} {fmt(fat):>5}  {name[:42]:<42} {category:<13} {source}")


if __name__ == "__main__":
    main()
