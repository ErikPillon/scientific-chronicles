#!/usr/bin/env python
"""Long-poll the approval bot and act on Approve / Decline / Next taps.

Runs as a launchd service. Only the configured owner chat may act; callbacks
from anyone else are refused, so a leaked bot username cannot publish.
"""
from __future__ import annotations

import sys
import time
import traceback

import config
import pipeline
import store
import telegram

POLL_TIMEOUT = 50


def _offset_path():
    config.ensure_dirs()
    return config.STATE_DIR / "tg_offset"


def _read_offset() -> int:
    path = _offset_path()
    try:
        return int(path.read_text().strip())
    except Exception:
        return 0


def _write_offset(value: int) -> None:
    _offset_path().write_text(str(value))


def handle_callback(conn, query: dict) -> None:
    data = query.get("data", "")
    message = query.get("message", {})
    from_id = str(query.get("from", {}).get("id", ""))
    owner = telegram.chat_id()

    if from_id != owner:
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="Not authorised.", show_alert=True)
        return

    action, _, raw_id = data.partition(":")
    if not raw_id.isdigit():
        telegram.call("answerCallbackQuery", callback_query_id=query["id"])
        return
    post = store.get_post(conn, int(raw_id))
    if post is None:
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="That post is gone.", show_alert=True)
        return

    if post["status"] == "published":
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="Already published — too late to change.", show_alert=True)
        telegram.settle(message, "— already published —")
        return

    if action == "a" and post["status"] == "approved":
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="Already approved.")
        return
    if action == "d" and post["status"] == "declined":
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="Already declined.")
        return

    if action == "a":
        when = pipeline.assign_slot(conn, post)
        if when is None:
            telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                          text=f"That day is full ({config.MAX_POSTS_PER_DAY} posts). "
                               f"Decline one first.", show_alert=True)
            return
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text=f"Approved — publishes {when}.")
        telegram.settle(message, f"✅ APPROVED — publishes {when}")

    elif action == "d":
        # Declining something already approved releases its slot for another.
        freed = post["status"] == "approved"
        store.update(conn, post["id"], status="declined", scheduled_for=None)
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="Slot released." if freed else "Declined.")
        telegram.settle(message, "🚫 DECLINED — slot released." if freed
                        else "🚫 DECLINED — nothing will be posted.")


def handle_message(conn, message: dict) -> None:
    """Answer the handful of text commands, owner only."""
    if str(message.get("chat", {}).get("id", "")) != telegram.chat_id():
        return
    text = (message.get("text") or "").strip().lower().split("@")[0]

    if text in ("/status", "/queue"):
        import status
        lines = status.summarise(conn, days=3, include_declined=False)
        header = (f"<b>Queue</b>\n{config.PUBLISH_AT} {config.TIMEZONE}, every "
                  f"{config.PUBLISH_STAGGER_MIN} min, max "
                  f"{config.MAX_POSTS_PER_DAY}/day\n")
        telegram.notify(header + "<pre>" + telegram._esc("\n".join(lines)) + "</pre>")

    elif text in ("/help", "/start"):
        telegram.notify(
            "<b>Scientific Chronicles</b>\n"
            "/status — what is approved, waiting and published\n\n"
            "Each morning you get every candidate for the next day. "
            "Approve the ones you want; each approval takes the next slot "
            f"from {config.PUBLISH_AT} {config.TIMEZONE.split('/')[-1]}, "
            f"{config.PUBLISH_STAGGER_MIN} min apart."
        )


def main() -> int:
    conn = store.connect()
    offset = _read_offset()
    print(f"approval bot listening (offset {offset})", flush=True)

    while True:
        try:
            updates = telegram.call(
                "getUpdates", offset=offset, timeout=POLL_TIMEOUT,
                allowed_updates=["callback_query", "message"],
                http_timeout=POLL_TIMEOUT + 15,
            )
        except Exception as exc:
            print(f"poll error: {exc}", file=sys.stderr, flush=True)
            time.sleep(10)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            _write_offset(offset)
            try:
                if "callback_query" in update:
                    handle_callback(conn, update["callback_query"])
                elif "message" in update:
                    handle_message(conn, update["message"])
            except Exception:
                traceback.print_exc()


if __name__ == "__main__":
    sys.exit(main())
