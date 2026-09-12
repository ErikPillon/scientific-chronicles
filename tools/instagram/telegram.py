"""Telegram Bot API helpers for the approval loop.

Uses a bot token dedicated to this pipeline. It must NOT be the token
openclaw's Telegram plugin uses: two long-poll consumers on one token steal
each other's updates.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

import config

API = "https://api.telegram.org/bot{token}/{method}"
PHOTO_CAPTION_LIMIT = 1024      # Telegram caps photo captions well below IG's 2200
MESSAGE_LIMIT = 4096


def _token() -> str:
    return config.require("SCIG_TELEGRAM_BOT_TOKEN")


def chat_id() -> str:
    return config.require("SCIG_TELEGRAM_CHAT_ID")


def call(method: str, *, files=None, http_timeout: int = 30, **params) -> dict[str, Any]:
    """POST to the Bot API. `http_timeout` is the socket timeout; any other
    kwarg (including Telegram's own long-poll `timeout`) is sent as a param."""
    for key, value in list(params.items()):
        if isinstance(value, (dict, list)):
            params[key] = json.dumps(value)
    response = requests.post(
        API.format(token=_token(), method=method),
        data=params, files=files, timeout=http_timeout,
    )
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {payload.get('description')}")
    return payload["result"]


def keyboard(post_id: int, *, has_next: bool) -> dict:
    rows = [[
        {"text": "✅ Approve", "callback_data": f"a:{post_id}"},
        {"text": "🚫 Decline", "callback_data": f"d:{post_id}"},
    ]]
    if has_next:
        rows.append([{"text": "🔀 Show next candidate", "callback_data": f"n:{post_id}"}])
    return {"inline_keyboard": rows}


def preview_caption(*, title: str, source_path: str, image_origin: str,
                    scheduled_for: str, caption: str, rank: str) -> str:
    origin_label = {
        "photo": "corpus photo (full bleed)",
        "inset": "corpus image (inset — check for watermarks)",
        "card": "generated card",
    }.get(image_origin, image_origin)
    header = (
        f"<b>{_esc(title)}</b>\n"
        f"<i>{_esc(rank)} · {_esc(origin_label)}</i>\n"
        f"Source: <code>{_esc(source_path)}</code>\n"
        f"Publishes: {_esc(scheduled_for)}\n"
        f"{'─' * 18}\n"
    )
    room = PHOTO_CAPTION_LIMIT - len(header) - 24
    body = caption if len(caption) <= room else caption[:room].rstrip() + "…"
    return header + _esc(body)


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def send_preview(*, image_path: Path, caption_text: str, post_id: int,
                 has_next: bool, full_caption: str) -> dict:
    with open(image_path, "rb") as handle:
        message = call(
            "sendPhoto",
            chat_id=chat_id(),
            caption=caption_text,
            parse_mode="HTML",
            reply_markup=keyboard(post_id, has_next=has_next),
            files={"photo": (image_path.name, handle, "image/jpeg")},
            http_timeout=60,
        )
    # The photo caption is truncated; send the exact text that will be posted.
    for chunk in _chunks(f"Full caption as it will post:\n\n{full_caption}"):
        call("sendMessage", chat_id=chat_id(), text=chunk,
             disable_web_page_preview=True)
    return message


def _chunks(text: str):
    while text:
        yield text[:MESSAGE_LIMIT]
        text = text[MESSAGE_LIMIT:]


def notify(text: str) -> None:
    try:
        call("sendMessage", chat_id=chat_id(), text=text,
             parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        pass


def settle(message: dict, verdict: str) -> None:
    """Strip the buttons and stamp the outcome onto the preview message."""
    try:
        call("editMessageCaption",
             chat_id=message["chat"]["id"], message_id=message["message_id"],
             caption=(message.get("caption", "")[:PHOTO_CAPTION_LIMIT - 40] + f"\n\n{verdict}"),
             reply_markup={"inline_keyboard": []})
    except Exception:
        try:
            call("editMessageReplyMarkup",
                 chat_id=message["chat"]["id"], message_id=message["message_id"],
                 reply_markup={"inline_keyboard": []})
        except Exception:
            pass
