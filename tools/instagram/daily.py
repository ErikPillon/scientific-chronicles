#!/usr/bin/env python
"""Daily job: offer every candidate for an upcoming day, all at once.

Each morning this sends an index of everything available for the target day
followed by one preview per candidate, so the choice is made knowing the
whole field rather than one at a time. Approving a post assigns it the next
free publishing slot on its target day.
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


def _source_label(cand, path) -> str:
    return ("corpus asset" if cand.image else "wikimedia" if path else "card")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="target day, as YYYY-MM-DD")
    parser.add_argument("--days-ahead", type=int, default=config.LEAD_DAYS)
    parser.add_argument("--limit", type=int, default=config.OFFER_LIMIT,
                        help=f"most candidates to offer (default {config.OFFER_LIMIT})")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--again", action="store_true",
                        help="offer again even if this day was already offered")
    args = parser.parse_args()

    target = (date.fromisoformat(args.date) if args.date
              else date.today() + timedelta(days=args.days_ahead))
    conn = store.connect()

    already = store.offered_for(conn, target)
    if already and not args.again:
        live = [r for r in already if r["status"] in ("pending", "approved", "published")]
        print(f"{target} already offered: {len(already)} candidates, "
              f"{len(live)} still live")
        return 0

    candidates = pipeline.candidates_for(conn, target)
    if not candidates:
        telegram.notify(f"📭 No unposted candidates for {target:%d %b}.")
        print(f"no candidates for {target}")
        return 0

    chosen = candidates[: max(1, args.limit)]
    resolved = [(c, content.resolve_image(c, live=not args.dry_run)) for c in chosen]

    if args.dry_run:
        print(f"target {target} — {len(candidates)} candidates, would offer {len(chosen)}")
        for i, (cand, (path, _)) in enumerate(resolved, 1):
            print(f"  {i:2}. {cand.title[:36]:36} {cand.occasion or cand.kind:8} "
                  f"{cand.year or '—':>6}  [{_source_label(cand, path)}]")
        slots = ", ".join(pipeline.local_label(pipeline.scheduled_at(target, i))
                          for i in range(min(3, config.MAX_POSTS_PER_DAY)))
        print(f"  slots as approved: {slots} …")
        return 0

    # Index first, so the field is visible before the previews scroll past.
    lines = [f"🗓 <b>{target:%A %d %B}</b> — {len(chosen)} candidates\n"]
    for i, (cand, (path, _)) in enumerate(resolved, 1):
        what = cand.occasion.lower() if cand.occasion else cand.kind
        lines.append(f"{i}. <b>{telegram._esc(cand.title)}</b> — {what}"
                     f"{f' {cand.year}' if cand.year else ''} · {_source_label(cand, path)}")
    lines.append(f"\nApprove the ones you want. Each approval takes the next slot: "
                 f"{config.PUBLISH_AT} {config.TIMEZONE.split('/')[-1]}, then every "
                 f"{config.PUBLISH_STAGGER_MIN} min, up to {config.MAX_POSTS_PER_DAY}/day.")
    telegram.notify("\n".join(lines))

    for rank, (cand, _) in enumerate(resolved):
        post_id = pipeline.build_and_queue(conn, cand, target, rank=rank,
                                           total=len(resolved))
        print(f"offered {rank + 1}/{len(resolved)}: #{post_id} {cand.title}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        telegram.notify(f"⚠️ Daily Instagram job failed:\n<code>{exc}</code>")
        traceback.print_exc()
        sys.exit(1)
