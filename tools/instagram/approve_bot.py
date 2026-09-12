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

    if post["status"] != "pending":
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text=f"Already {post['status']}.", show_alert=True)
        telegram.settle(message, f"— already {post['status']} —")
        return

    if action == "a":
        store.update(conn, post["id"], status="approved")
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="Approved — queued to publish.")
        telegram.settle(message,
                        f"✅ APPROVED — publishes {pipeline.local_label(post['scheduled_for'])}")

    elif action == "d":
        store.update(conn, post["id"], status="declined")
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="Declined.")
        telegram.settle(message, "🚫 DECLINED — nothing will be posted.")

    elif action == "n":
        store.update(conn, post["id"], status="declined")
        telegram.call("answerCallbackQuery", callback_query_id=query["id"],
                      text="Fetching the next candidate…")
        telegram.settle(message, "⏭ SKIPPED — showing the next candidate.")
        if pipeline.advance(conn, post) is None:
            telegram.notify("That was the last candidate for today.")


def main() -> int:
    conn = store.connect()
    offset = _read_offset()
    print(f"approval bot listening (offset {offset})", flush=True)

    while True:
        try:
            updates = telegram.call(
                "getUpdates", offset=offset, timeout=POLL_TIMEOUT,
                allowed_updates=["callback_query"], http_timeout=POLL_TIMEOUT + 15,
            )
        except Exception as exc:
            print(f"poll error: {exc}", file=sys.stderr, flush=True)
            time.sleep(10)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            _write_offset(offset)
            if "callback_query" in update:
                try:
                    handle_callback(conn, update["callback_query"])
                except Exception:
                    traceback.print_exc()


if __name__ == "__main__":
    sys.exit(main())
