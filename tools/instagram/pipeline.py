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
    local = (datetime.combine(target_day, dtime(int(hour), int(minute or 0)))
             + timedelta(minutes=slot * config.PUBLISH_STAGGER_MIN)).astimezone()
    target = local.astimezone(timezone.utc)
    if target_day <= date.today():
        target = max(target, datetime.now(timezone.utc))
    return target.isoformat(timespec="seconds")


def local_label(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%a %d %b, %H:%M")


def build_and_queue(conn: sqlite3.Connection, cand: content.Candidate, target_day: date,
                    *, rank: int, pool: list[str], slot: int = 0) -> int:
    """Render the image, queue the post, and send the approval preview."""
    config.ensure_dirs()
    # Resolve the image first: a Wikimedia credit has to reach the caption.
    photo_path, credit = content.resolve_image(cand)
    cand.credit = credit
    caption = content.build_caption(cand, target_day)
    slug = Path(cand.source_path).stem[:48]
    image_path = config.MEDIA_DIR / f"{target_day.isoformat()}-{slot}-{rank:02d}-{slug}.jpg"

    origin = render.render(
        title=cand.title,
        eyebrow=render.eyebrow_for(cand.kind, cand.occasion, target_day),
        headline=cand.headline,
        year=cand.year,
        photo_path=photo_path,
        out_path=image_path,
    )

    when = scheduled_at(target_day, slot)
    post_id = store.add_post(
        conn,
        mmdd=target_day.strftime("%m-%d"),
        target_date=target_day.isoformat(),
        source_kind=cand.kind,
        source_path=cand.source_path,
        title=cand.title,
        caption=caption,
        image_path=str(image_path),
        image_origin=origin,
        status="pending",
        tg_chat_id=telegram.chat_id(),
        scheduled_for=when,
        meta={"rank": rank, "slot": slot, "pool": pool, "score": round(cand.score, 1),
              "asset": photo_path or "", "credit": credit,
              "day": target_day.isoformat()},
    )

    message = telegram.send_preview(
        image_path=image_path,
        caption_text=telegram.preview_caption(
            title=cand.title, source_path=cand.source_path, image_origin=origin,
            scheduled_for=local_label(when), caption=caption,
            rank=f"slot {slot + 1} · candidate {rank + 1} of {len(pool)}",
        ),
        post_id=post_id,
        has_next=rank + 1 < len(pool),
        full_caption=caption,
    )
    store.update(conn, post_id, tg_message_id=message["message_id"])
    return post_id


def candidates_for(conn: sqlite3.Connection, target_day: date) -> list[content.Candidate]:
    return content.pick(target_day.strftime("%m-%d"), target_day,
                        store.recently_posted(conn))


def advance(conn: sqlite3.Connection, post: sqlite3.Row) -> int | None:
    """Queue the next-best candidate after the one in `post` was passed over."""
    meta = json.loads(post["meta"] or "{}")
    pool: list[str] = meta.get("pool", [])
    slot = int(meta.get("slot", 0))
    next_rank = int(meta.get("rank", 0)) + 1

    # Do not offer something already taken by another slot for the same day.
    target_day = (date.fromisoformat(post["target_date"]) if post["target_date"]
                  else date.today())
    taken = {r["source_path"] for r in store.queued_for(conn, target_day)}

    while next_rank < len(pool):
        wanted = pool[next_rank]
        if wanted in taken:
            next_rank += 1
            continue
        for cand in content.pick(post["mmdd"], target_day, set()):
            if cand.source_path == wanted:
                return build_and_queue(conn, cand, target_day, rank=next_rank,
                                       pool=pool, slot=slot)
        next_rank += 1
    return None
