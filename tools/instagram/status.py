#!/usr/bin/env python
"""Show the queue: what is approved, waiting, and recently published."""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone

import config
import pipeline
import store

ICON = {"approved": "✅", "pending": "⏳", "published": "📣",
        "declined": "🚫", "failed": "⚠️"}


def summarise(conn, *, days: int, include_declined: bool) -> list[str]:
    since = (date.today() - timedelta(days=days)).isoformat()
    until = (date.today() + timedelta(days=days)).isoformat()
    statuses = ("approved", "pending", "published", "failed") + (
        ("declined",) if include_declined else ())
    rows = conn.execute(
        f"""SELECT * FROM posts
             WHERE target_date BETWEEN ? AND ?
               AND status IN ({','.join('?' * len(statuses))})
             ORDER BY target_date, COALESCE(scheduled_for, '9'), id""",
        (since, until, *statuses),
    ).fetchall()

    if not rows:
        return ["Nothing queued."]

    out: list[str] = []
    current = None
    for row in rows:
        if row["target_date"] != current:
            current = row["target_date"]
            when = date.fromisoformat(current)
            label = {0: " (today)", 1: " (tomorrow)", -1: " (yesterday)"}.get(
                (when - date.today()).days, "")
            out.append(f"\n{when:%a %d %b}{label}")
        time = (pipeline.local_label(row["scheduled_for"]).split(", ")[-1]
                if row["scheduled_for"] else "—")
        line = (f"  {ICON.get(row['status'], '·')} {time:>12}  "
                f"#{row['id']:<4} {row['title'][:38]}")
        if row["status"] == "published" and row["ig_permalink"]:
            line += f"\n       {row['ig_permalink']}"
        if row["status"] == "failed" and row["error"]:
            line += f"\n       error: {row['error'][:90]}"
        out.append(line)
    return out


def run_sql(conn, query: str) -> int:
    """Run a SELECT and print it as an aligned table.

    Writes are refused: this is for looking, and a stray UPDATE here would
    desynchronise the queue from what Instagram and Telegram already believe.
    """
    lowered = query.strip().lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        print("Only SELECT / WITH queries are allowed here.", file=sys.stderr)
        return 2
    try:
        rows = conn.execute(query).fetchall()
    except Exception as exc:
        print(f"SQL error: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print("(no rows)")
        return 0

    names = rows[0].keys()
    cells = [[("" if r[n] is None else str(r[n])).replace("\n", " ")[:60] for n in names]
             for r in rows]
    widths = [max(len(n), *(len(row[i]) for row in cells)) for i, n in enumerate(names)]
    print("  ".join(n.ljust(w) for n, w in zip(names, widths)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))
    print(f"\n{len(rows)} row(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=3,
                        help="days either side of today (default 3)")
    parser.add_argument("--all", action="store_true", help="include declined")
    parser.add_argument("--sql", metavar="QUERY",
                        help="run a read-only SELECT against the queue and print a table")
    parser.add_argument("--columns", action="store_true",
                        help="list the columns of the posts table")
    args = parser.parse_args()

    conn = store.connect()

    if args.columns:
        for row in conn.execute("PRAGMA table_info(posts)"):
            print(f"  {row['name']:<14} {row['type']}")
        return 0

    if args.sql:
        return run_sql(conn, args.sql)
    print(f"queue: {config.DB_PATH}")
    print(f"slots: {config.PUBLISH_AT} {config.TIMEZONE}, every "
          f"{config.PUBLISH_STAGGER_MIN} min, max {config.MAX_POSTS_PER_DAY}/day")
    for line in summarise(conn, days=args.days, include_declined=args.all):
        print(line)

    upcoming = conn.execute(
        "SELECT COUNT(*) AS n FROM posts WHERE status = 'approved'").fetchone()["n"]
    waiting = conn.execute(
        "SELECT COUNT(*) AS n FROM posts WHERE status = 'pending'").fetchone()["n"]
    print(f"\n{upcoming} approved and waiting to publish, {waiting} awaiting your decision")
    return 0


if __name__ == "__main__":
    sys.exit(main())
