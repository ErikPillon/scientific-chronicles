#!/usr/bin/env python
"""Build a contact sheet of every corpus image the pipeline could publish.

The assets were collected for a personal website; posting them to a public
Instagram account is a different bar. Review this sheet once and list anything
watermarked, third-party, or otherwise not yours in the blocklist file.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

import config
import render

COLS, THUMB, LABEL, PAD = 5, 300, 34, 16


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="image-review.jpg")
    args = parser.parse_args()

    usable = []
    for path in sorted((config.REPO / "assets" / "images").iterdir()):
        if not path.is_file():
            continue
        loaded = render._load_photo(str(path))
        if loaded:
            usable.append((path, loaded[0], loaded[1]))

    if not usable:
        print("no publishable images found")
        return 1

    rows = (len(usable) + COLS - 1) // COLS
    cell_h = THUMB + LABEL
    sheet = Image.new("RGB", (COLS * (THUMB + PAD) + PAD,
                              rows * (cell_h + PAD) + PAD), (245, 247, 250))
    draw = ImageDraw.Draw(sheet)
    font = render.font("medium", 15)

    for index, (path, photo, treatment) in enumerate(usable):
        col, row = index % COLS, index // COLS
        x = PAD + col * (THUMB + PAD)
        y = PAD + row * (cell_h + PAD)
        thumb = photo.copy()
        thumb.thumbnail((THUMB, THUMB), Image.LANCZOS)
        draw.rectangle([x, y, x + THUMB, y + THUMB], fill=(225, 230, 238))
        sheet.paste(thumb, (x + (THUMB - thumb.width) // 2,
                            y + (THUMB - thumb.height) // 2))
        name = path.name
        while draw.textlength(name, font=font) > THUMB and len(name) > 8:
            name = name[:-5] + "…"
        draw.text((x, y + THUMB + 6), name, font=font, fill=(15, 23, 42))
        draw.text((x, y + THUMB + 22), treatment, font=font, fill=(100, 116, 139))

    out = Path(args.out).expanduser().resolve()
    sheet.save(out, "JPEG", quality=88, optimize=True)
    print(f"{len(usable)} publishable images -> {out}")
    import content
    print(f"policy = {content.IMAGE_POLICY}; "
          f"{sum(1 for p, _, _ in usable if content.image_permitted(p.name))} currently permitted")
    print(f"Add the filenames you own or that are public domain to "
          f"{content.ALLOWLIST_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
