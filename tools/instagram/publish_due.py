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

import config
import instagram
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
        image_path = Path(post["image_path"])
        if not image_path.is_file():
            raise RuntimeError(f"rendered image missing: {image_path}")

        url = post["r2_url"]
        if not url:
            key = f"instagram/{date.today():%Y/%m}/{post_id}-{image_path.name}"
            url = r2.upload(image_path, key)
            store.update(conn, post_id, r2_key=key, r2_url=url)

        media_id, permalink = instagram.post(url, post["caption"])
        store.update(conn, post_id, status="published", ig_media_id=media_id,
                     ig_permalink=permalink, published_at=store.now(),
                     error=None, meta=json.dumps(meta))
        telegram.notify(
            f"📣 Published: <b>{post['title']}</b>"
            + (f"\n{permalink}" if permalink else "")
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
    parser.add_argument("--force", action="store_true",
                        help="ignore the scheduled time and publish approved posts now")
    args = parser.parse_args()

    conn = store.connect()
    due = list(store.due_for_publish(conn))
    if args.force:
        due = conn.execute("SELECT * FROM posts WHERE status = 'approved' ORDER BY id").fetchall()
    if not due:
        return 0

    budget = config.MAX_POSTS_PER_DAY - store.published_last_24h(conn)
    if budget <= 0:
        print("daily post budget already used")
        return 0

    remote = instagram.quota_used()
    if remote is not None and remote >= 24:
        telegram.notify("⚠️ Instagram's 25-post/24h publishing limit is nearly used. Holding.")
        return 0

    for post in due[:budget]:
        publish_one(conn, post)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        telegram.notify(f"⚠️ Publisher crashed:\n<code>{exc}</code>")
        traceback.print_exc()
        sys.exit(1)
