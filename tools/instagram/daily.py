#!/usr/bin/env python
"""Daily job: prepare the next day's posts and send them for approval.

Runs each morning for the day after, so there is a full day to approve
before anything is due. Each post is pinned to its own target date and to a
staggered slot within it.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, timedelta

import config
import content
import pipeline
import store
import telegram


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="target day, as YYYY-MM-DD")
    parser.add_argument("--days-ahead", type=int, default=config.LEAD_DAYS,
                        help=f"days ahead to prepare (default {config.LEAD_DAYS})")
    parser.add_argument("--count", type=int, default=config.POSTS_PER_DAY,
                        help=f"posts to prepare (default {config.POSTS_PER_DAY})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be prepared, queue nothing")
    parser.add_argument("--again", action="store_true",
                        help="prepare more even if the day already has posts")
    args = parser.parse_args()

    target = (date.fromisoformat(args.date) if args.date
              else date.today() + timedelta(days=args.days_ahead))
    conn = store.connect()

    existing = store.queued_for(conn, target)
    if existing and not args.again:
        summary = ", ".join(f"#{r['id']} {r['title']} ({r['status']})" for r in existing)
        print(f"{target} already prepared: {summary}")
        return 0

    candidates = pipeline.candidates_for(conn, target)
    if not candidates:
        telegram.notify(f"📭 No unposted candidates for {target:%d %b}.")
        print(f"no candidates for {target}")
        return 0

    wanted = max(1, args.count)
    pool = [c.source_path for c in candidates][: wanted + 6]
    chosen = candidates[:wanted]
    first_slot = len(existing)

    if args.dry_run:
        print(f"target {target} — {len(candidates)} candidates, preparing {len(chosen)}")
        for offset, cand in enumerate(chosen):
            slot = first_slot + offset
            path, credit = content.resolve_image(cand, live=False)
            source = ("corpus asset" if cand.image else
                      "wikimedia" if path else "none — card")
            when = pipeline.local_label(pipeline.scheduled_at(target, slot))
            print(f"  slot {slot + 1}: {cand.title}  [{source}]  publishes {when}")
        return 0

    queued = []
    for offset, cand in enumerate(chosen):
        slot = first_slot + offset
        post_id = pipeline.build_and_queue(conn, cand, target, rank=offset,
                                           pool=pool, slot=slot)
        queued.append(f"#{post_id} {cand.title}")
        print(f"queued slot {slot + 1}: {cand.title}")

    telegram.notify(
        f"🗓 <b>{target:%A %d %B}</b> — {len(queued)} post(s) ready for review.\n"
        + "\n".join(queued)
        + f"\n\nApprove each one above. They publish on {target:%d %b}, "
          f"{config.PUBLISH_STAGGER_MIN} min apart from {config.PUBLISH_AT}."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        telegram.notify(f"⚠️ Daily Instagram job failed:\n<code>{exc}</code>")
        traceback.print_exc()
        sys.exit(1)
