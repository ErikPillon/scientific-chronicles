#!/usr/bin/env python
"""Pre-fetch Wikimedia portraits for the whole corpus.

Daily runs read the cache, so running this once means the picker knows which
people have a portrait before it ranks them — and you can review the results
in one pass instead of discovering them one post at a time.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date

import content
import wikimedia


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="stop after this many lookups")
    parser.add_argument("--month", type=int, help="only this month (1-12)")
    parser.add_argument("--refresh", action="store_true",
                        help="re-query people already cached")
    parser.add_argument("--retry-misses", action="store_true",
                        help="re-query people previously recorded as not found")
    args = parser.parse_args()

    months = [args.month] if args.month else range(1, 13)
    seen: set[str] = set()
    people: list = []
    for month in months:
        for day in range(1, 32):
            try:
                date(2024, month, day)
            except ValueError:
                continue
            for cand in content.collect(f"{month:02d}-{day:02d}"):
                if cand.kind != "scientist" or cand.title in seen:
                    continue
                seen.add(cand.title)
                people.append(cand)

    print(f"{len(people)} distinct people in scope\n")
    stats = Counter()
    looked_up = 0

    for index, cand in enumerate(people, 1):
        key = wikimedia.slug(cand.title)
        hit = wikimedia.cached(key)
        if isinstance(hit, wikimedia.Portrait) and not args.refresh:
            stats["already cached"] += 1
            continue
        if hit == "miss" and not (args.retry_misses or args.refresh):
            stats["known miss"] += 1
            continue
        if args.limit and looked_up >= args.limit:
            stats["skipped (limit)"] += 1
            continue

        looked_up += 1
        found = wikimedia.fetch(
            cand.title, surname=cand.meta.get("surname", ""),
            birth_year=cand.meta.get("birth_year"),
            death_year=cand.meta.get("death_year"),
            refresh=args.refresh,
        )
        stats["fetched" if found else "not found"] += 1
        mark = "✅" if found else "· "
        print(f"  {mark} [{index}/{len(people)}] {cand.title[:46]:46} "
              f"{found.license_tag if found else ''}", flush=True)

    print("\nsummary")
    for key, value in stats.most_common():
        print(f"  {key:16} {value}")
    print(f"\ncache: {wikimedia.CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
