#!/usr/bin/env python
"""Refresh the long-lived Instagram token before its ~60-day expiry.

Run monthly. Without this the pipeline fails silently once the token lapses.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

import config
import telegram


def main() -> int:
    token = config.require("SCIG_IG_ACCESS_TOKEN")
    base = config.get("SCIG_IG_API_BASE", "https://graph.facebook.com/v23.0").rstrip("/")

    if "graph.instagram.com" in base:
        response = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
    else:
        response = requests.get(
            f"{base}/oauth/access_token",
            params={"grant_type": "fb_exchange_token",
                    "client_id": config.require("SCIG_META_APP_ID"),
                    "client_secret": config.require("SCIG_META_APP_SECRET"),
                    "fb_exchange_token": token}, timeout=30)

    payload = response.json()
    if "access_token" not in payload:
        message = payload.get("error", {}).get("message", response.text[:300])
        telegram.notify(f"⚠️ Instagram token refresh failed:\n<code>{message}</code>")
        print(f"refresh failed: {message}", file=sys.stderr)
        return 1

    new_token = payload["access_token"]
    days = int(payload.get("expires_in", 0)) // 86400

    path = config.ENV_FILE
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(r"(?m)^SCIG_IG_ACCESS_TOKEN=.*$",
                             f"SCIG_IG_ACCESS_TOKEN={new_token}", text)
    if not count:
        updated = text.rstrip("\n") + f"\nSCIG_IG_ACCESS_TOKEN={new_token}\n"
    path.write_text(updated, encoding="utf-8")
    path.chmod(0o600)

    print(f"token refreshed; valid ~{days} days")
    telegram.notify(f"🔑 Instagram token refreshed — valid about {days} more days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
