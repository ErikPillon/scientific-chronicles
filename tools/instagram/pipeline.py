"""Shared pipeline steps: turn a candidate into a queued, previewed post."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time as dtime, timezone
from pathlib import Path

import config
import content
import render
import store
import telegram


def scheduled_at(today: date) -> str:
    """Today at the configured publish time, in UTC. Never in the past."""
    hour, _, minute = config.PUBLISH_AT.partition(":")
    local = datetime.combine(today, dtime(int(hour), int(minute or 0))).astimezone()
    now = datetime.now(timezone.utc)
    target = local.astimezone(timezone.utc)
    return max(target, now).isoformat(timespec="seconds")


def local_label(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%a %d %b, %H:%M")


def build_and_queue(conn: sqlite3.Connection, cand: content.Candidate, today: date,
                    *, rank: int, pool: list[str]) -> int:
    """Render the image, queue the post, and send the approval preview."""
    config.ensure_dirs()
    # Resolve the image first: a Wikimedia credit has to reach the caption.
    photo_path, credit = content.resolve_image(cand)
    cand.credit = credit
    caption = content.build_caption(cand, today)
    slug = Path(cand.source_path).stem[:48]
    image_path = config.MEDIA_DIR / f"{today.isoformat()}-{rank:02d}-{slug}.jpg"

    origin = render.render(
        title=cand.title,
        eyebrow=render.eyebrow_for(cand.kind, cand.occasion, today),
        headline=cand.headline,
        year=cand.year,
        photo_path=photo_path,
        out_path=image_path,
    )

    when = scheduled_at(today)
    post_id = store.add_post(
        conn,
        mmdd=today.strftime("%m-%d"),
        source_kind=cand.kind,
        source_path=cand.source_path,
        title=cand.title,
        caption=caption,
        image_path=str(image_path),
        image_origin=origin,
        status="pending",
        tg_chat_id=telegram.chat_id(),
        scheduled_for=when,
        meta={"rank": rank, "pool": pool, "score": round(cand.score, 1),
              "asset": photo_path or "", "credit": credit,
              "day": today.isoformat()},
    )

    message = telegram.send_preview(
        image_path=image_path,
        caption_text=telegram.preview_caption(
            title=cand.title, source_path=cand.source_path, image_origin=origin,
            scheduled_for=local_label(when), caption=caption,
            rank=f"candidate {rank + 1} of {len(pool)}",
        ),
        post_id=post_id,
        has_next=rank + 1 < len(pool),
        full_caption=caption,
    )
    store.update(conn, post_id, tg_message_id=message["message_id"])
    return post_id


def candidates_for(conn: sqlite3.Connection, today: date) -> list[content.Candidate]:
    return content.pick(today.strftime("%m-%d"), today, store.recently_posted(conn))


def advance(conn: sqlite3.Connection, post: sqlite3.Row) -> int | None:
    """Queue the next-best candidate after the one in `post` was passed over."""
    meta = json.loads(post["meta"] or "{}")
    pool: list[str] = meta.get("pool", [])
    next_rank = int(meta.get("rank", 0)) + 1
    if next_rank >= len(pool):
        return None
    # Carry the original day forward so a --date run stays self-consistent.
    today = date.fromisoformat(meta["day"]) if meta.get("day") else date.today()
    wanted = pool[next_rank]
    for cand in content.pick(post["mmdd"], today, set()):
        if cand.source_path == wanted:
            return build_and_queue(conn, cand, today, rank=next_rank, pool=pool)
    return None
