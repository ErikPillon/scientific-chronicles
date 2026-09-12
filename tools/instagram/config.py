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

# Local time of the first publishing slot (HH:MM, 24h).
PUBLISH_AT = get("SCIG_PUBLISH_AT", "17:00")

# Minutes between consecutive slots on the same day.
PUBLISH_STAGGER_MIN = int(get("SCIG_PUBLISH_STAGGER_MIN", "30"))

# How many posts to prepare and preview for each day.
POSTS_PER_DAY = int(get("SCIG_POSTS_PER_DAY", "2"))

# How far ahead to prepare. 1 means each morning previews tomorrow, giving a
# full day to approve before anything is due.
LEAD_DAYS = int(get("SCIG_LEAD_DAYS", "1"))

# Hard ceiling per calendar day. Instagram allows 25 per rolling 24h.
MAX_POSTS_PER_DAY = int(get("SCIG_MAX_POSTS_PER_DAY", str(POSTS_PER_DAY)))


def ensure_dirs() -> None:
    for directory in (STATE_DIR, MEDIA_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
