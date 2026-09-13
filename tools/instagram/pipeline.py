"""Shared pipeline steps: turn a candidate into a queued, previewed post."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

import config
import content
import render
import store
import telegram


def scheduled_at(target_day: date, slot: int = 0) -> str:
    """UTC time for a slot on its target day.

    Slots are spaced by PUBLISH_STAGGER_MIN from PUBLISH_AT. The day is never
    moved: a post prepared for the 13th publishes on the 13th. Only a slot
    that is already past on the current day is pulled forward to now.
    """
    hour, _, minute = config.PUBLISH_AT.partition(":")
    local = (datetime.combine(target_day, dtime(int(hour), int(minute or 0)),
                              tzinfo=config.tz())
             + timedelta(minutes=slot * config.PUBLISH_STAGGER_MIN))
    target = local.astimezone(timezone.utc)
    if target_day <= date.today():
        target = max(target, datetime.now(timezone.utc))
    return target.isoformat(timespec="seconds")


def local_label(iso: str) -> str:
    moment = datetime.fromisoformat(iso).astimezone(config.tz())
    return moment.strftime("%a %d %b, %H:%M %Z")


def build_and_queue(conn: sqlite3.Connection, cand: content.Candidate, target_day: date,
                    *, rank: int, total: int) -> int:
    """Render the image, queue the post, and send the approval preview."""
    config.ensure_dirs()
    # Resolve the image first: a Wikimedia credit has to reach the caption.
    photo_path, credit = content.resolve_image(cand)
    cand.credit = credit
    caption = content.build_caption(cand, target_day)
    slug = Path(cand.source_path).stem[:48]
    image_path = config.MEDIA_DIR / f"{target_day.isoformat()}-{rank:02d}-{slug}.jpg"

    origin = render.render(
        title=cand.title,
        eyebrow=render.eyebrow_for(cand.kind, cand.occasion, target_day),
        headline=cand.headline,
        year=cand.year,
        photo_path=photo_path,
        out_path=image_path,
    )

    # No time yet: the publishing slot is assigned when you approve, so the
    # order reflects what you actually chose rather than what was offered.
    post_id = store.add_post(
        conn,
        mmdd=target_day.strftime("%m-%d"),
        target_date=target_day.isoformat(),
        source_kind=cand.kind,
        source_path=cand.source_path,
        title=cand.title,
        caption=caption,
        image_path=image_path.name,
        image_origin=origin,
        status="pending",
        tg_chat_id=telegram.chat_id(),
        scheduled_for=None,
        meta={"rank": rank, "score": round(cand.score, 1),
              "asset": photo_path or "", "credit": credit,
              "day": target_day.isoformat()},
    )

    message = telegram.send_preview(
        image_path=image_path,
        caption_text=telegram.preview_caption(
            title=cand.title, source_path=cand.source_path, image_origin=origin,
            scheduled_for=f"{target_day:%a %d %b} — slot assigned when you approve",
            caption=caption,
            rank=f"{rank + 1} of {total}",
        ),
        post_id=post_id,
        full_caption=caption,
    )
    store.update(conn, post_id, tg_message_id=message["message_id"])
    return post_id


def candidates_for(conn: sqlite3.Connection, target_day: date) -> list[content.Candidate]:
    return content.pick(target_day.strftime("%m-%d"), target_day,
                        store.recently_posted(conn))


def assign_slot(conn: sqlite3.Connection, post) -> str | None:
    """Give an approved post the earliest free slot on its target day.

    Slots are matched on their actual times rather than counted, so declining
    an approved post frees its slot and the next approval reuses it instead of
    colliding with one still held.

    Returns the local label, or None when every slot is taken.
    """
    target_day = (date.fromisoformat(post["target_date"]) if post["target_date"]
                  else date.today())
    taken = {
        row["scheduled_for"]
        for row in conn.execute(
            """SELECT scheduled_for FROM posts
                WHERE target_date = ? AND id != ?
                  AND status IN ('approved', 'published')""",
            (target_day.isoformat(), post["id"]),
        )
        if row["scheduled_for"]
    }
    for slot in range(config.MAX_POSTS_PER_DAY):
        when = scheduled_at(target_day, slot)
        if when in taken:
            continue
        meta = json.loads(post["meta"] or "{}")
        meta["slot"] = slot
        store.update(conn, post["id"], status="approved", scheduled_for=when,
                     meta=json.dumps(meta))
        return local_label(when)
    return None


def rerender(conn: sqlite3.Connection, post) -> Path | None:
    """Rebuild a post's image from its source, for when the file is gone.

    A queue synced between machines arrives without the rendered JPEGs, and
    losing an approved post to a missing file is worse than spending a second
    regenerating it.
    """
    import json as _json
    meta = _json.loads(post["meta"] or "{}")
    target_day = (date.fromisoformat(post["target_date"]) if post["target_date"]
                  else date.today())
    for cand in content.collect(post["mmdd"]):
        if cand.source_path != post["source_path"]:
            continue
        photo_path, credit = content.resolve_image(cand)
        out = config.MEDIA_DIR / Path(post["image_path"]).name
        origin = render.render(
            title=cand.title,
            eyebrow=render.eyebrow_for(cand.kind, cand.occasion, target_day),
            headline=cand.headline, year=cand.year,
            photo_path=photo_path, out_path=out,
        )
        store.update(conn, post["id"], image_path=out.name, image_origin=origin)
        return out
    return None
