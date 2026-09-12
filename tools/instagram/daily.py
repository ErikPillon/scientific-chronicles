#!/usr/bin/env python
"""Daily job: pick today's best item, render it, and ask for approval."""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date

import config
import pipeline
import store
import telegram


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="override the day, as YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true",
                        help="render and print, but do not queue or send")
    parser.add_argument("--again", action="store_true",
                        help="queue another post even if today already has one")
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    conn = store.connect()

    # launchd fires a missed calendar job when the Mac wakes, so this can run
    # more than once a day. One post per day, unless --again is passed.
    if not args.again:
        existing = conn.execute(
            """SELECT id, title, status FROM posts
                WHERE mmdd = ? AND created_at >= ?
                  AND status IN ('pending', 'approved', 'published')
                ORDER BY id DESC LIMIT 1""",
            (today.strftime("%m-%d"), today.isoformat()),
        ).fetchone()
        if existing:
            print(f"already handled today: #{existing['id']} "
                  f"{existing['title']} ({existing['status']})")
            return 0

    candidates = pipeline.candidates_for(conn, today)

    if not candidates:
        telegram.notify(f"📭 No unposted candidates for {today:%d %b}.")
        print(f"no candidates for {today}")
        return 0

    pool = [c.source_path for c in candidates][:8]
    best = candidates[0]

    if args.dry_run:
        import content as content_mod
        path, credit = content_mod.resolve_image(best)
        source = ("corpus asset" if best.image else
                  "wikimedia" if path else "none — will render a card")
        print(f"{len(candidates)} candidates; best = {best.title} "
              f"(score {best.score:.1f}, image: {source})")
        if credit:
            print(f"credit: {credit}")
        best.credit = credit
        print("-" * 60)
        print(content_mod.build_caption(best, today))
        return 0

    post_id = pipeline.build_and_queue(conn, best, today, rank=0, pool=pool)
    print(f"queued post {post_id}: {best.title}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        telegram.notify(f"⚠️ Daily Instagram job failed:\n<code>{exc}</code>")
        traceback.print_exc()
        sys.exit(1)
