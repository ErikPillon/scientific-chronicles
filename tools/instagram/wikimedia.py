"""Fetch portraits from Wikipedia/Wikimedia Commons for corpus items.

Two things matter more than coverage here:

* **Identity.** A photo of the wrong person is worse than no photo, so a
  candidate page is only accepted when the surname matches the resolved
  title and a known birth/death year appears in the article intro.
* **Licence.** The rendered post overlays type on the image, which makes a
  derivative work. Share-alike licences propagate that obligation, so they
  are excluded by default; public domain, CC0 and plain CC BY are kept, and
  the credit is carried into the caption.

Results are cached on disk, negatives included, so repeat runs cost nothing.
"""
from __future__ import annotations

import html
import json
import re
import time
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

import config

from PIL import Image

WIKI_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH = 1400
MIN_WIDTH = 500

# The renderer needs 1080x1350. Anything wider than this is dead weight on
# disk, so downloads are re-encoded to JPEG once and kept at a usable size.
STORE_MAX_WIDTH = 1400
STORE_QUALITY = 88
REQUEST_PAUSE = 0.35

CACHE = config.STATE_DIR / "wikimedia"

# Wikimedia asks every client to identify itself; the default urllib3 agent
# gets throttled or refused.
USER_AGENT = config.get(
    "SCIG_WIKIMEDIA_USER_AGENT",
    "ScientificChronicles/1.0 (https://github.com/ErikPillon/scientific-chronicles)",
)
ALLOWED = {
    tag.strip().lower()
    for tag in config.get("SCIG_WIKIMEDIA_LICENSES", "pd,cc0,cc-by").split(",")
    if tag.strip()
}

_session: requests.Session | None = None


@dataclass
class Portrait:
    path: str
    license: str
    license_tag: str
    artist: str
    file_title: str
    page_title: str
    credit: str


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = USER_AGENT
    return _session


def _api(url: str, **params) -> dict:
    params.update(action="query", format="json", formatversion=2)
    response = session().get(url, params=params, timeout=40)
    response.raise_for_status()
    time.sleep(REQUEST_PAUSE)
    return response.json()


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def _strip_html(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    # Commons often stacks the same credit twice inside nested markup.
    half = len(text) // 2
    if text and len(text) % 2 == 1 and text[half] == " " and text[:half] == text[half + 1:]:
        text = text[:half]
    return text


def license_tag(name: str) -> str | None:
    """Map a Commons licence label onto the tags used by SCIG_WIKIMEDIA_LICENSES."""
    text = (name or "").lower()
    if not text:
        return None
    if "cc0" in text:
        return "cc0"
    # Flickr Commons / GLAM uploads use these instead of "Public domain".
    if ("public domain" in text or text.startswith("pd")
            or "no restrictions" in text or "no known copyright" in text):
        return "pd"
    if "sa" in re.sub(r"[^a-z]", " ", text).split():
        return "cc-by-sa"
    if "share" in text and "alike" in text:
        return "cc-by-sa"
    if "cc by-sa" in text or "cc-by-sa" in text:
        return "cc-by-sa"
    if "attribution" in text or "cc by" in text or "cc-by" in text:
        return "cc-by"
    return None


def _matches(page_title: str, extract: str, surname: str,
             birth_year: int | None, death_year: int | None) -> bool:
    """Guard against grabbing a photo of a different person entirely."""
    if surname and slug(surname) not in slug(page_title):
        return False
    years = [y for y in (birth_year, death_year) if y and y > 100]
    if not years:
        return False
    return any(str(year) in extract for year in years)


def _lookup(name: str, surname: str, birth_year: int | None,
            death_year: int | None) -> tuple[str, str] | None:
    """Return (page_title, pageimage file name) for a verified match."""
    payload = _api(
        WIKI_API, titles=name, redirects=1,
        prop="pageimages|extracts", piprop="name",
        exintro=1, explaintext=1,
    )
    pages = payload.get("query", {}).get("pages", [])
    for page in pages:
        if page.get("missing"):
            continue
        title = page.get("title", "")
        extract = page.get("extract", "") or ""
        if not _matches(title, extract, surname, birth_year, death_year):
            continue
        if page.get("pageimage"):
            return title, page["pageimage"]
    return None


def _file_info(file_name: str) -> dict | None:
    payload = _api(
        COMMONS_API, titles=f"File:{file_name}",
        prop="imageinfo", iiprop="url|extmetadata|size", iiurlwidth=THUMB_WIDTH,
        iiextmetadatafilter="LicenseShortName|Artist|Credit|LicenseUrl",
    )
    pages = payload.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    info = (pages[0].get("imageinfo") or [{}])[0]
    if not info:
        return None
    meta = info.get("extmetadata", {})
    return {
        "url": info.get("thumburl") or info.get("url"),
        "width": info.get("thumbwidth") or info.get("width") or 0,
        "license": _strip_html(meta.get("LicenseShortName", {}).get("value", "")),
        "artist": _strip_html(meta.get("Artist", {}).get("value", ""))[:80],
    }


def compact(path: Path) -> int:
    """Normalise a cached image to JPEG at a sane size. Returns bytes saved.

    Commons serves PNG and TIFF originals that run to several megabytes; the
    renderer only ever needs 1080x1350, so keeping them whole wastes disk.
    """
    before = path.stat().st_size
    try:
        with Image.open(path) as src:
            src.load()
            image = src.convert("RGB")
            if image.width > STORE_MAX_WIDTH:
                height = round(image.height * STORE_MAX_WIDTH / image.width)
                image = image.resize((STORE_MAX_WIDTH, height), Image.LANCZOS)
            if src.format == "JPEG" and before <= 400_000 and image.width <= STORE_MAX_WIDTH:
                return 0                      # already small and already JPEG
            image.save(path, "JPEG", quality=STORE_QUALITY, optimize=True,
                       progressive=True)
    except Exception:
        return 0
    return max(before - path.stat().st_size, 0)


def _cache_paths(key: str) -> tuple[Path, Path]:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{key}.jpg", CACHE / f"{key}.json"


def cached(key: str) -> Portrait | None | str:
    """Portrait, "miss" for a recorded negative, or None if never looked up."""
    image, sidecar = _cache_paths(key)
    if not sidecar.is_file():
        return None
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    if not record.get("ok"):
        return "miss"
    if not image.is_file():
        return None
    portrait = Portrait(**record["portrait"])
    # The sidecar records the absolute path of whichever machine fetched it.
    # A cache synced to another host would otherwise hand back a path that
    # does not exist there, and the render would silently fall back to a card.
    portrait.path = str(image)
    return portrait


def fetch(name: str, *, surname: str = "", birth_year: int | None = None,
          death_year: int | None = None, refresh: bool = False) -> Portrait | None:
    """Look up, verify, licence-check, download and cache a portrait."""
    key = slug(name)
    if not refresh:
        hit = cached(key)
        if isinstance(hit, Portrait):
            return hit
        if hit == "miss":
            return None

    image_path, sidecar = _cache_paths(key)

    def record_miss(reason: str) -> None:
        sidecar.write_text(json.dumps({"ok": False, "reason": reason, "name": name}),
                           encoding="utf-8")

    try:
        found = _lookup(name, surname or name.split()[-1], birth_year, death_year)
        if not found:
            record_miss("no verified page image")
            return None
        page_title, file_name = found

        info = _file_info(file_name)
        if not info or not info.get("url"):
            record_miss("no file info")
            return None

        tag = license_tag(info["license"])
        if tag not in ALLOWED:
            record_miss(f"licence not allowed: {info['license'] or 'unknown'}")
            return None
        if int(info["width"] or 0) < MIN_WIDTH:
            record_miss(f"too small: {info['width']}px")
            return None

        response = session().get(info["url"], timeout=60)
        response.raise_for_status()
        image_path.write_bytes(response.content)
        compact(image_path)
        time.sleep(REQUEST_PAUSE)

        artist = info["artist"] or "Unknown"
        credit = (f"Photo: {artist} via Wikimedia Commons"
                  + ("" if tag in ("pd", "cc0") else f" ({info['license']})"))
        portrait = Portrait(
            path=str(image_path), license=info["license"], license_tag=tag,
            artist=artist, file_title=f"File:{file_name}",
            page_title=page_title, credit=credit,
        )
        sidecar.write_text(json.dumps({"ok": True, "name": name,
                                       "portrait": asdict(portrait)}, indent=2),
                           encoding="utf-8")
        return portrait

    except Exception as exc:
        # Transient failures must not be cached as permanent negatives.
        if sidecar.is_file():
            sidecar.unlink()
        print(f"wikimedia: {name}: {exc}")
        return None
