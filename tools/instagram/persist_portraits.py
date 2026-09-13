#!/usr/bin/env python
"""Copy cached Wikimedia portraits into the repo and relink the corpus.

The pipeline persists a portrait when its post publishes, which fills the
website in at a few per day. This does the whole corpus at once so the site
is illustrated now.
"""
from __future__ import annotations

import argparse
import sys

import assets
import config
import content
import wikimedia


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    people = content.people()
    todo = []
    for cand in people:
        if cand.image:
            continue                       # already has a real file in the repo
        hit = wikimedia.cached(wikimedia.slug(cand.title))
        if isinstance(hit, wikimedia.Portrait):
            todo.append((cand, hit))
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(people)} scientists, {len(todo)} to persist "
          f"at {assets.REPO_MAX_WIDTH}px into {config.REPO / 'assets/images'}")
    if args.dry_run:
        for cand, hit in todo[:10]:
            print(f"  {cand.title[:40]:40} <- {hit.path.split('/')[-1]}")
        print("  …")
        return 0

    done = failed = 0
    for i, (cand, hit) in enumerate(todo, 1):
        try:
            name = assets.persist(cand.source_path, hit.path, hit.credit)
            done += bool(name)
        except Exception as exc:
            failed += 1
            print(f"  ! {cand.title}: {exc}", file=sys.stderr)
        if i % 200 == 0:
            print(f"  {i}/{len(todo)}…", flush=True)

    print(f"\npersisted {done}, failed {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
