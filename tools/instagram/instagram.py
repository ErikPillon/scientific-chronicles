"""Instagram Content Publishing: create a media container, then publish it.

Requires an Instagram Business/Creator account, a Meta app, and a long-lived
token with instagram_business_content_publish. Containers expire after 24h,
so one is created at publish time rather than at approval time.
"""
from __future__ import annotations

import time

import requests

import config

# Meta retires Graph API versions on a rolling basis; keep this configurable
# so a version bump never needs a code change. `doctor.py` verifies it.
def base() -> str:
    return config.get("SCIG_IG_API_BASE", "https://graph.facebook.com/v23.0").rstrip("/")


def _user_id() -> str:
    return config.require("SCIG_IG_USER_ID")


def _token() -> str:
    return config.require("SCIG_IG_ACCESS_TOKEN")


class InstagramError(RuntimeError):
    pass


def _request(method: str, path: str, **params):
    params["access_token"] = _token()
    response = requests.request(method, f"{base()}/{path}", params=params, timeout=60)
    try:
        payload = response.json()
    except ValueError:
        raise InstagramError(f"Non-JSON response ({response.status_code}): {response.text[:300]}")
    if "error" in payload:
        error = payload["error"]
        raise InstagramError(
            f"{error.get('type')} {error.get('code')}: {error.get('message')}"
            + (f" — {error['error_user_msg']}" if error.get("error_user_msg") else "")
        )
    return payload


def create_container(image_url: str, caption: str) -> str:
    return _request("POST", f"{_user_id()}/media",
                    image_url=image_url, caption=caption)["id"]


def wait_ready(creation_id: str, *, timeout: int = 300, interval: int = 5) -> None:
    """Poll the container until Instagram finishes fetching the image."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        payload = _request("GET", creation_id, fields="status_code,status")
        status = payload.get("status_code", "")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Container {status}: {payload.get('status', '')}")
        last = status or last
        time.sleep(interval)
    raise InstagramError(f"Container not ready after {timeout}s (last status: {last or 'unknown'})")


def publish(creation_id: str) -> str:
    return _request("POST", f"{_user_id()}/media_publish", creation_id=creation_id)["id"]


def permalink(media_id: str) -> str:
    try:
        return _request("GET", media_id, fields="permalink").get("permalink", "")
    except InstagramError:
        return ""


def post(image_url: str, caption: str) -> tuple[str, str]:
    """Full publish flow. Returns (media_id, permalink)."""
    creation_id = create_container(image_url, caption)
    wait_ready(creation_id)
    media_id = publish(creation_id)
    return media_id, permalink(media_id)


def quota_used() -> int | None:
    """Posts Instagram counts against the rolling 25-per-24h publishing limit."""
    try:
        payload = _request("GET", f"{_user_id()}/content_publishing_limit",
                           fields="quota_usage,config")
        return int(payload["data"][0]["quota_usage"])
    except Exception:
        return None
