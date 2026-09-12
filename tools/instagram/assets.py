"""Persist a used Wikimedia portrait into the repo and point the corpus at it.

Only runs for images that actually got published, so nothing you declined
ends up committed. Attribution is written alongside the filename, because
once the file is a local asset the caption builder can no longer ask
Wikimedia who took the picture.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

import config

# Repo copies are for the website and for rendering; neither needs more.
REPO_MAX_WIDTH = 1200
REPO_QUALITY = 86

COMMIT = config.get("SCIG_ASSET_COMMIT", "0") == "1"


def _images_dir() -> Path:
    path = config.REPO / "assets" / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _unique_name(stem: str) -> tuple[Path, str]:
    directory = _images_dir()
    name = f"{stem}.jpg"
    if not (directory / name).exists():
        return directory / name, name
    for n in range(2, 50):
        name = f"{stem}-{n}.jpg"
        if not (directory / name).exists():
            return directory / name, name
    raise RuntimeError(f"cannot find a free filename for {stem}")


def _set_field(front: str, key: str, value: str) -> str:
    """Set or replace a frontmatter scalar, keeping the block's ordering."""
    escaped = value.replace('"', "'")
    line = f'{key}: "{escaped}"'
    pattern = rf"(?m)^{re.escape(key)}:.*$"
    if re.search(pattern, front):
        return re.sub(pattern, line, front, count=1)
    return front.rstrip("\n") + "\n" + line


def persist(source_path: str, photo_path: str, credit: str) -> str | None:
    """Copy the portrait into assets/images and relink the markdown file.

    Returns the new filename, or None when there is nothing to do.
    """
    if not photo_path:
        return None
    photo = Path(photo_path)
    markdown = config.REPO / source_path
    if not photo.is_file() or not markdown.is_file():
        return None

    # Already a repo asset — the corpus points at it by definition.
    try:
        if photo.resolve().is_relative_to(_images_dir().resolve()):
            return None
    except AttributeError:                       # Python < 3.9 fallback
        if str(photo.resolve()).startswith(str(_images_dir().resolve())):
            return None

    target, name = _unique_name(markdown.stem)
    try:
        with Image.open(photo) as src:
            src.load()
            image = src.convert("RGB")
            if image.width > REPO_MAX_WIDTH:
                height = round(image.height * REPO_MAX_WIDTH / image.width)
                image = image.resize((REPO_MAX_WIDTH, height), Image.LANCZOS)
            image.save(target, "JPEG", quality=REPO_QUALITY, optimize=True,
                       progressive=True)
    except Exception:
        shutil.copy2(photo, target)

    text = markdown.read_text(encoding="utf-8")
    match = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", text, re.S)
    if not match:
        return name
    opening, front, closing, body = match.groups()
    front = _set_field(front, "image", name)
    if credit:
        front = _set_field(front, "image_credit", credit)
    markdown.write_text(opening + front + closing + body, encoding="utf-8")

    if COMMIT:
        _commit(target, markdown, name)
    return name


def _commit(image: Path, markdown: Path, name: str) -> None:
    try:
        subprocess.run(["git", "-C", str(config.REPO), "add",
                        str(image.relative_to(config.REPO)),
                        str(markdown.relative_to(config.REPO))],
                       check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "-C", str(config.REPO), "commit", "-m",
                        f"Add portrait for {markdown.stem} ({name})"],
                       check=True, capture_output=True, timeout=30)
    except Exception as exc:
        print(f"asset commit skipped: {exc}")
