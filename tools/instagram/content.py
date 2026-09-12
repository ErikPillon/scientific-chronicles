"""Read the Hugo content corpus and pick the day's best Instagram candidate.

Mirrors the date-matching logic in layouts/date/single.html: scientists match
on the month-day of birth_date or death_date, events on the month-day of date.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

import config

FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
DATE_RE = re.compile(r"^(\d{1,4})-(\d{2})-(\d{2})$")

# "other-events" are civic/cultural anniversaries (festivals, holidays) rather
# than science. Off-brand for the feed, so they are opt-in.
INCLUDE_OTHER_EVENTS = config.get("SCIG_INCLUDE_OTHER_EVENTS", "0") == "1"

BRAND_HASHTAGS = ["#ScientificChronicles", "#OnThisDay", "#HistoryOfScience"]
MAX_CAPTION = 2200
MAX_HASHTAGS = 30


@dataclass
class Candidate:
    kind: str                 # scientist | event | other
    source_path: str          # repo-relative
    title: str
    headline: str
    body: str
    image: str | None         # resolved absolute path, or None
    year: int | None
    occasion: str             # "Birth" | "Death" | "" for events
    disciplines: list[str] = field(default_factory=list)
    credit: str = ""
    score: float = 0.0
    meta: dict = field(default_factory=dict)


def _parse(path: Path) -> tuple[dict, str] | None:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8", errors="replace"))
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    return meta, match.group(2).strip()


def _mmdd(value) -> tuple[str, int] | None:
    """Return (MM-DD, year) for a frontmatter date, or None if unusable."""
    if isinstance(value, date):
        return f"{value.month:02d}-{value.day:02d}", value.year
    match = DATE_RE.match(str(value or "").strip())
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{month:02d}-{day:02d}", year


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [p.strip() for p in value.strip("[]").split(",") if p.strip()]
    return []


# Corpus images come from an earlier project of the author's. A few carry
# third-party watermarks from wherever they were originally collected, so the
# blocklist stays available; `all` is the default.
#
#   all (default) - every corpus image
#   blocklist     - everything except filenames in the blocklist file
#   allowlist     - only filenames listed in the allowlist file
IMAGE_POLICY = config.get("SCIG_IMAGE_POLICY", "all").strip().lower()
ALLOWLIST_FILE = Path(config.get(
    "SCIG_IMAGE_ALLOWLIST", "~/.config/sc-instagram/image-allowlist.txt")).expanduser()
BLOCKLIST_FILE = Path(config.get(
    "SCIG_IMAGE_BLOCKLIST", "~/.config/sc-instagram/image-blocklist.txt")).expanduser()


def _read_list(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


_ALLOWED = _read_list(ALLOWLIST_FILE)
_BLOCKED = _read_list(BLOCKLIST_FILE)


def image_permitted(filename: str) -> bool:
    if IMAGE_POLICY == "all":
        return True
    if IMAGE_POLICY == "blocklist":
        return filename not in _BLOCKED
    return filename in _ALLOWED


def _resolve_image(name) -> str | None:
    """Absolute path to a publishable image, or None to fall back to a card."""
    if not name:
        return None
    filename = str(name).strip()
    if not image_permitted(filename):
        return None
    candidate = config.REPO / "assets" / "images" / filename
    return str(candidate) if candidate.is_file() else None


def people(mmdd: str | None = None) -> list[Candidate]:
    """Every scientist, or only those matching MM-DD. One pass over the files."""
    out: list[Candidate] = []
    repo = config.REPO
    for path in sorted((repo / "assets" / "scientists").glob("*.md")):
        parsed = _parse(path)
        if not parsed:
            continue
        meta, body = parsed
        name = " ".join(str(meta.get(k, "")).strip() for k in ("name", "surname")).strip()
        if not name or not body:
            continue
        birth = _mmdd(meta.get("birth_date"))
        death = _mmdd(meta.get("death_date"))
        for resolved, occasion in ((birth, "Birth"), (death, "Death")):
            if not resolved:
                continue
            if mmdd is not None and resolved[0] != mmdd:
                continue
            out.append(Candidate(
                kind="scientist",
                source_path=str(path.relative_to(repo)),
                title=name,
                headline=str(meta.get("headline", "")).strip(),
                body=body,
                image=_resolve_image(meta.get("image")),
                year=resolved[1],
                occasion=occasion,
                disciplines=_as_list(meta.get("disciplines")),
                meta={"nationality": meta.get("nationality", ""),
                      "surname": str(meta.get("surname", "")).strip(),
                      "image_credit": str(meta.get("image_credit", "")).strip(),
                      "birth_year": (birth or (None, None))[1],
                      "death_year": (death or (None, None))[1],
                      "dates": [d[0] for d in (birth, death) if d]},
            ))
            if mmdd is None:
                break        # one entry per person when enumerating everyone
    return out


def collect(mmdd: str) -> list[Candidate]:
    """Every corpus item whose date falls on this MM-DD."""
    out: list[Candidate] = people(mmdd)
    repo = config.REPO

    sources = [("event", repo / "assets" / "events")]
    if INCLUDE_OTHER_EVENTS:
        sources.append(("other", repo / "assets" / "other-events"))
    for kind, directory in sources:
        for path in sorted(directory.glob("*.md")):
            parsed = _parse(path)
            if not parsed:
                continue
            meta, body = parsed
            resolved = _mmdd(meta.get("date"))
            title = str(meta.get("title", "")).strip()
            if not resolved or resolved[0] != mmdd or not title or not body:
                continue
            out.append(Candidate(
                kind=kind,
                source_path=str(path.relative_to(repo)),
                title=title,
                headline=str(meta.get("headline", "")).strip(),
                body=body,
                image=_resolve_image(meta.get("image")),
                year=resolved[1],
                occasion="",
                disciplines=_as_list(meta.get("disciplines")),
                meta={"event_type": meta.get("event_type", "")},
            ))
    return out


def plain(text: str) -> str:
    """Strip Markdown. Instagram renders captions literally, so leftover
    asterisks and link syntax would show up as-is in the post."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)       # links -> label
    text = re.sub(r"`([^`]*)`", r"\1", text)                     # inline code
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text, flags=re.S)  # bold
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)    # headings
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)         # blockquotes
    text = re.sub(r"<[^>]+>", "", text)                          # stray HTML
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


WIKIMEDIA_ENABLED = config.get("SCIG_WIKIMEDIA", "1") == "1"


def portrait_key(cand: "Candidate") -> str | None:
    """Cache key for a Wikimedia lookup, or None if one should not be tried.

    Only people are looked up. An event title does not reliably map to a
    correct image, and a wrong picture is worse than a generated card.
    """
    if not WIKIMEDIA_ENABLED or cand.kind != "scientist":
        return None
    import wikimedia
    return wikimedia.slug(cand.title)


def resolve_image(cand: "Candidate", *, live: bool = True) -> tuple[str | None, str]:
    """Best available image for a candidate, as (path, credit).

    Corpus asset first, then a verified Wikimedia portrait, then nothing —
    in which case render.py falls back to a generated card.
    """
    if cand.image:
        # A persisted portrait keeps its credit in frontmatter, since the
        # caption builder can no longer ask Wikimedia who took it.
        return cand.image, cand.meta.get("image_credit", "")
    key = portrait_key(cand)
    if not key:
        return None, ""
    import wikimedia
    hit = wikimedia.cached(key)
    if isinstance(hit, wikimedia.Portrait):
        return hit.path, hit.credit
    if hit == "miss" or not live:
        return None, ""
    birth = cand.meta.get("birth_year")
    death = cand.meta.get("death_year")
    found = wikimedia.fetch(cand.title, surname=cand.meta.get("surname", ""),
                            birth_year=birth, death_year=death)
    return (found.path, found.credit) if found else (None, "")


def has_cached_portrait(cand: "Candidate") -> bool:
    """Disk-only check, used for ranking so scoring never hits the network."""
    key = portrait_key(cand)
    if not key:
        return False
    import wikimedia
    return isinstance(wikimedia.cached(key), wikimedia.Portrait)


def anniversary(cand: Candidate, today: date) -> int | None:
    """Years elapsed, when the item has a usable year in the past."""
    if not cand.year or cand.year < 100 or cand.year >= today.year:
        return None
    return today.year - cand.year


def score(cand: Candidate, today: date) -> float:
    points = 0.0
    if cand.image or has_cached_portrait(cand):
        points += 40                       # a real photograph beats a rendered card
    points += min(len(cand.body), 1200) / 100.0
    if cand.headline:
        points += 5
    points += {"event": 12, "scientist": 10, "other": 0}.get(cand.kind, 0)
    if cand.occasion == "Birth":
        points += 4                        # birthdays read better than death dates
    if cand.disciplines:
        points += 3
    years = anniversary(cand, today)
    if years:
        if years % 100 == 0:
            points += 25
        elif years % 50 == 0:
            points += 15
        elif years % 25 == 0:
            points += 8
    return points


def hashtags(cand: Candidate) -> list[str]:
    tags: list[str] = []
    for discipline in cand.disciplines:
        tag = "#" + re.sub(r"[^A-Za-z0-9]", "", discipline.title())
        if len(tag) > 1 and tag not in tags:
            tags.append(tag)
    for tag in BRAND_HASHTAGS:
        if tag not in tags:
            tags.append(tag)
    return tags[:MAX_HASHTAGS]


def build_caption(cand: Candidate, today: date) -> str:
    years = anniversary(cand, today)
    if cand.kind == "scientist":
        verb = "born" if cand.occasion == "Birth" else "died"
        head = f"{cand.title} — {verb} on this day"
        if cand.year:
            head += f" in {cand.year}"
        if years:
            head += f" ({years} years ago)"
    else:
        head = cand.title
        if cand.year:
            head += f" — {cand.year}"
        if years:
            head += f" ({years} years ago)"

    # The headline is rendered on the image itself, so repeating it here would
    # show the reader the same sentence twice. The caption carries only what
    # the picture does not: the anniversary line and the body.
    parts = [head, plain(cand.body)]

    if cand.credit:
        parts.append(cand.credit)
    tags = " ".join(hashtags(cand))
    caption = "\n\n".join(parts)
    budget = MAX_CAPTION - len(tags) - 2
    if len(caption) > budget:
        caption = caption[: budget - 1].rstrip() + "…"
    return f"{caption}\n\n{tags}"


def pick(mmdd: str, today: date, exclude: set[str] | None = None) -> list[Candidate]:
    """Today's candidates, best first, excluding already-used source paths."""
    exclude = exclude or set()
    candidates = [c for c in collect(mmdd) if c.source_path not in exclude]
    for cand in candidates:
        cand.score = score(cand, today)
    return sorted(candidates, key=lambda c: (-c.score, c.source_path))
