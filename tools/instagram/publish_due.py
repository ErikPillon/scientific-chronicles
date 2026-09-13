#!/usr/bin/env python
"""Publish approved posts whose scheduled time has arrived.

Instagram has no native scheduling, so this runs on a short cron and does the
waiting itself: upload to R2, create a media container, publish it.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date
from pathlib import Path

import assets
import config
import instagram
import pipeline
import r2
import store
import telegram

MAX_ATTEMPTS = 3


def publish_one(conn, post) -> None:
    post_id = post["id"]
    meta = json.loads(post["meta"] or "{}")
    attempts = int(meta.get("attempts", 0)) + 1
    meta["attempts"] = attempts

    try:
        image_path = store.media_path(post["image_path"])
        if image_path is None or not image_path.is_file():
            print(f"post {post_id}: image missing, re-rendering", file=sys.stderr)
            image_path = pipeline.rerender(conn, post)
            if image_path is None or not image_path.is_file():
                raise RuntimeError(
                    f"rendered image missing and could not be rebuilt "
                    f"from {post['source_path']}")

        url = post["r2_url"]
        if not url:
            key = f"instagram/{date.today():%Y/%m}/{post_id}-{image_path.name}"
            url = r2.upload(image_path, key)
            store.update(conn, post_id, r2_key=key, r2_url=url)

        media_id, permalink = instagram.post(url, post["caption"])
        store.update(conn, post_id, status="published", ig_media_id=media_id,
                     ig_permalink=permalink, published_at=store.now(),
                     error=None, meta=json.dumps(meta))
        saved = None
        try:
            saved = assets.persist(post["source_path"], meta.get("asset", ""),
                                   meta.get("credit", ""))
        except Exception as exc:
            print(f"asset persist failed for {post['id']}: {exc}", file=sys.stderr)

        telegram.notify(
            f"📣 Published: <b>{post['title']}</b>"
            + (f"\n{permalink}" if permalink else "")
            + (f"\n🖼 saved to assets/images/{saved}" if saved else "")
        )
        print(f"published {post_id}: {post['title']} {permalink}")

    except Exception as exc:
        give_up = attempts >= MAX_ATTEMPTS
        store.update(conn, post_id, error=str(exc)[:900], meta=json.dumps(meta),
                     **({"status": "failed"} if give_up else {}))
        print(f"post {post_id} attempt {attempts} failed: {exc}", file=sys.stderr)
        if give_up:
            telegram.notify(
                f"⚠️ Giving up on <b>{post['title']}</b> after {attempts} attempts:\n"
                f"<code>{str(exc)[:500]}</code>"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, action="append", dest="ids", metavar="N",
                        help="publish exactly this post now, whatever its schedule "
                             "(repeatable). Prefer this over --force.")
    parser.add_argument("--force", action="store_true",
                        help="publish EVERY approved post now, ignoring every "
                             "scheduled time. Rarely what you want.")
    parser.add_argument("--yes", action="store_true",
                        help="confirm a --force that would publish future-dated posts")
    args = parser.parse_args()

    conn = store.connect()

    if args.ids:
        due = [r for r in (store.get_post(conn, i) for i in args.ids) if r]
        missing = set(args.ids) - {r["id"] for r in due}
        if missing:
            print(f"no such post: {sorted(missing)}", file=sys.stderr)
            return 1
        wrong = [r["id"] for r in due if r["status"] != "approved"]
        if wrong:
            print(f"not approved, refusing: {wrong}", file=sys.stderr)
            return 1
    elif args.force:
        # --force ignores every schedule, so say exactly what it is about to do.
        due = conn.execute(
            "SELECT * FROM posts WHERE status = 'approved' ORDER BY id").fetchall()
        future = [r for r in due if r["scheduled_for"] and r["scheduled_for"] > store.now()]
        if future:
            print("--force would publish posts scheduled for later:", file=sys.stderr)
            for r in future:
                print(f"  #{r['id']} {r['title']} — due {r['scheduled_for']} "
                      f"(target {r['target_date']})", file=sys.stderr)
            if not args.yes:
                print("\nRefusing. Use --id N to publish one post, or add --yes "
                      "to confirm publishing all of the above now.", file=sys.stderr)
                return 1
    else:
        due = list(store.due_for_publish(conn))

    if not due:
        return 0

    remote = instagram.quota_used()
    if remote is not None and remote >= 24:
        telegram.notify("⚠️ Instagram's 25-post/24h publishing limit is nearly used. Holding.")
        return 0

    # Budget is per target day, so a staggered run of same-day posts does not
    # starve itself the way a rolling 24h window would.
    spent: dict[str, int] = {}
    for post in due:
        day = post["target_date"] or date.today().isoformat()
        if day not in spent:
            spent[day] = store.published_on(conn, date.fromisoformat(day))
        if spent[day] >= config.MAX_POSTS_PER_DAY:
            print(f"day budget for {day} already used ({spent[day]})")
            continue
        publish_one(conn, post)
        if store.get_post(conn, post["id"])["status"] == "published":
            spent[day] += 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        telegram.notify(f"⚠️ Publisher crashed:\n<code>{exc}</code>")
        traceback.print_exc()
        sys.exit(1)
