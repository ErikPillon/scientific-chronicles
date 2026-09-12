#!/usr/bin/env python
"""Preflight: verify every credential and hop before trusting the automation."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import config

OK, BAD, WARN = "  ✅", "  ❌", "  ⚠️ "
failures = 0


def check(label: str, fn):
    global failures
    try:
        detail = fn()
        print(f"{OK} {label}" + (f" — {detail}" if detail else ""))
    except Exception as exc:
        failures += 1
        print(f"{BAD} {label} — {exc}")


def main() -> int:
    print(f"\nenv file : {config.ENV_FILE}"
          f"{'' if config.ENV_FILE.is_file() else '  (missing)'}")
    print(f"repo     : {config.REPO}")
    print(f"state    : {config.STATE_DIR}\n")

    print("Content")
    def corpus():
        import content
        today = date.today()
        found = content.collect(today.strftime("%m-%d"))
        if not found:
            raise RuntimeError("no items matched today's date — check SCIG_REPO")
        with_image = sum(1 for c in found if c.image)
        return f"{len(found)} items today, {with_image} with an image asset"
    check("corpus readable", corpus)

    print("\nRendering")
    def rendering():
        import render, store
        store.connect()
        out = config.MEDIA_DIR / "_doctor.jpg"
        origin = render.render(title="Scientific Chronicles", eyebrow="Doctor check",
                               headline="Render pipeline is working.", year=2026,
                               photo_path=None, out_path=out)
        size = out.stat().st_size
        out.unlink(missing_ok=True)
        return f"{origin} treatment, {size // 1024} KB"
    check("image renderer", rendering)

    print("\nTelegram")
    def bot():
        import telegram
        me = telegram.call("getMe")
        return f"@{me.get('username')}"
    check("bot token", bot)

    def owner():
        import telegram
        chat = telegram.call("getChat", chat_id=telegram.chat_id())
        return chat.get("username") and f"@{chat['username']}" or str(chat.get("id"))
    check("owner chat reachable", owner)

    def distinct():
        import json as _json
        import telegram
        path = Path("~/.openclaw/openclaw.json").expanduser()
        if not path.is_file():
            return "openclaw config not found; skipped"
        oc = _json.load(open(path)).get("channels", {}).get("telegram", {}).get("botToken")
        if oc and oc == config.get("SCIG_TELEGRAM_BOT_TOKEN"):
            raise RuntimeError(
                "this is openclaw's own bot token — two long-poll consumers on one "
                "token steal each other's updates. Make a separate bot in @BotFather."
            )
        return "separate from openclaw's bot"
    check("token is not openclaw's", distinct)

    print("\nCloudflare R2")
    def r2_rw():
        import r2, requests
        out = config.MEDIA_DIR / "_doctor_r2.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("scientific-chronicles doctor probe")
        key = "instagram/_doctor/probe.txt"
        url = r2.upload(out, key)
        out.unlink(missing_ok=True)
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"uploaded, but {url} returned HTTP {response.status_code}. "
                "Instagram must be able to fetch the image — enable public access "
                "on the bucket (custom domain, or the r2.dev subdomain)."
            )
        r2.delete(key)
        return f"upload + public read OK ({url.split('/')[2]})"
    check("bucket read/write + public URL", r2_rw)

    print("\nInstagram")
    def account():
        import instagram
        data = instagram._request("GET", instagram._user_id(),
                                  fields="username,account_type,media_count")
        kind = data.get("account_type", "?")
        if kind not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
            raise RuntimeError(f"account_type is {kind}; publishing needs Business or Creator")
        return f"@{data.get('username')} ({kind}, {data.get('media_count')} posts)"
    check("account + token", account)

    def quota():
        import instagram
        used = instagram.quota_used()
        if used is None:
            raise RuntimeError("could not read content_publishing_limit")
        return f"{used}/25 posts used in the last 24h"
    check("publishing quota", quota)

    print()
    if failures:
        print(f"{failures} check(s) failed — fix these before enabling the automations.\n")
    else:
        print("All checks passed. Safe to enable the automations.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
