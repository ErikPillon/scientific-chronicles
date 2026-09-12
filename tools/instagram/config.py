"""Configuration for the Instagram auto-posting pipeline.

Secrets are never stored in the repo. They are read from, in order of
precedence: the process environment, then the env file at
``~/.config/sc-instagram/env`` (KEY=value, ``#`` comments allowed).
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(os.environ.get("SCIG_ENV_FILE", "~/.config/sc-instagram/env")).expanduser()

_file_env: dict[str, str] = {}
if ENV_FILE.is_file():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        _file_env[key.strip()] = value.strip().strip("'\"")


def get(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or _file_env.get(name) or default


def require(name: str) -> str:
    value = get(name)
    if not value:
        raise SystemExit(
            f"Missing required setting {name}.\n"
            f"Add it to {ENV_FILE} as {name}=... (see tools/instagram/env.example)"
        )
    return value


# Repository holding the content. Defaults to the main checkout, not this
# worktree, so scheduled runs keep working after the branch is merged.
REPO = Path(get("SCIG_REPO", "~/GitHub/scientific-chronicles")).expanduser()

STATE_DIR = Path(get("SCIG_STATE_DIR", "~/.local/state/sc-instagram")).expanduser()
MEDIA_DIR = STATE_DIR / "media"
DB_PATH = STATE_DIR / "queue.db"
LOG_DIR = STATE_DIR / "logs"

# How many days must pass before the same source item may be posted again.
REPOST_COOLDOWN_DAYS = int(get("SCIG_REPOST_COOLDOWN_DAYS", "365"))

# Publishing times are pinned to a real timezone rather than the host's, so
# the same schedule holds whether this runs on a laptop in Rome or a server
# whose clock is UTC.
TIMEZONE = get("SCIG_TIMEZONE", "Europe/Rome")


def tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(TIMEZONE)


# Time of the first publishing slot in TIMEZONE (HH:MM, 24h).
PUBLISH_AT = get("SCIG_PUBLISH_AT", "08:00")

# Minutes between consecutive slots on the same day.
PUBLISH_STAGGER_MIN = int(get("SCIG_PUBLISH_STAGGER_MIN", "30"))

# How many candidates to offer for review each morning. Every one of them is
# sent up front so the choice is made knowing the whole field.
OFFER_LIMIT = int(get("SCIG_OFFER_LIMIT", "10"))

# How far ahead to prepare. 1 means each morning previews tomorrow, giving a
# full day to approve before anything is due.
LEAD_DAYS = int(get("SCIG_LEAD_DAYS", "1"))

# Hard ceiling on how many of the offered candidates can be approved for one
# day. Approvals are the real control; this only stops runaway. Instagram
# allows 25 per rolling 24h.
MAX_POSTS_PER_DAY = int(get("SCIG_MAX_POSTS_PER_DAY", "6"))


def ensure_dirs() -> None:
    for directory in (STATE_DIR, MEDIA_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)


# Some hosts advertise IPv6 routes that black-hole. Every outbound call then
# waits for the v6 attempt to time out before falling back, which turned a
# 0.1s R2 upload into 120s. Filtering resolution to IPv4 sidesteps it without
# root; fixing the host's routing is the real cure.
if get("SCIG_FORCE_IPV4", "0") == "1":
    import socket as _socket

    _real_getaddrinfo = _socket.getaddrinfo

    def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        results = _real_getaddrinfo(host, port, _socket.AF_INET, type, proto, flags)
        return results or _real_getaddrinfo(host, port, family, type, proto, flags)

    _socket.getaddrinfo = _ipv4_only
