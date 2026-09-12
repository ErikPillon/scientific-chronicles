"""Render a 1080x1350 (4:5) Instagram image for a candidate.

Two treatments, sharing one type system so the feed looks consistent:
  * photo  - the corpus asset, cover-cropped full bleed under a bottom scrim
  * card   - a typographic card, used when no image asset exists
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1350
PAD = 76

INK = (15, 23, 42)            # --text  #0f172a
INK_DEEP = (8, 13, 26)
ACCENT = (37, 99, 235)        # --accent #2563eb
CYAN = (6, 182, 212)          # #06b6d4
WHITE = (255, 255, 255)
MUTED = (203, 213, 225)

HELV = "/System/Library/Fonts/HelveticaNeue.ttc"
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
FACES = {
    "bold": (AVENIR, 0), "demi": (AVENIR, 2), "medium": (AVENIR, 5),
    "regular": (AVENIR, 7), "light": (HELV, 7), "ultralight": (HELV, 5),
}


def font(face: str, size: int) -> ImageFont.FreeTypeFont:
    path, index = FACES[face]
    return ImageFont.truetype(path, size, index=index)


def tracked(draw, xy, text, fnt, fill, tracking=0):
    """Draw text with letter-spacing; PIL has no native tracking."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=fnt, fill=fill)
        x += draw.textlength(char, font=fnt) + tracking
    return x - xy[0]


def tracked_width(draw, text, fnt, tracking=0) -> float:
    return sum(draw.textlength(c, font=fnt) for c in text) + tracking * max(len(text) - 1, 0)


def wrap(draw, text: str, fnt, max_width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit(draw, text: str, face: str, max_width: int, max_lines: int,
        start: int, minimum: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Largest size at which the text wraps into max_lines or fewer."""
    size = start
    while size > minimum:
        fnt = font(face, size)
        lines = wrap(draw, text, fnt, max_width)
        if len(lines) <= max_lines:
            return fnt, lines
        size -= 4
    fnt = font(face, minimum)
    lines = wrap(draw, text, fnt, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.;:") + "…"
    return fnt, lines


def _background() -> Image.Image:
    """Ink field with a soft accent glow in the upper right."""
    base = Image.new("RGB", (W, H), INK)
    top = Image.new("RGB", (W, H), (17, 31, 61))
    mask = Image.linear_gradient("L").resize((W, H))
    base = Image.composite(base, top, mask)

    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W - 520, -360, W + 260, 420], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    base.paste(Image.new("RGB", (W, H), ACCENT), (0, 0), glow)
    return base


def _rings(img: Image.Image) -> None:
    """Faint orbital rings — a quiet nod to the subject matter."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = W - 150, H - 130
    for radius, alpha in ((300, 26), (420, 18), (560, 12)):
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                     outline=(255, 255, 255, alpha), width=2)
    img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"), (0, 0))


# Crop is taken mostly off the bottom: in a portrait the head sits high, and
# the lower third of the frame is where the type goes anyway.
CROP_BIAS = 0.12


def _cover(photo: Image.Image) -> Image.Image:
    """Scale-and-crop to fill 1080x1350, keeping headroom for the subject."""
    photo = photo.convert("RGB")
    scale = max(W / photo.width, H / photo.height)
    new = (max(int(photo.width * scale + 0.5), W), max(int(photo.height * scale + 0.5), H))
    photo = photo.resize(new, Image.LANCZOS)
    left = (photo.width - W) // 2
    top = min(int((photo.height - H) * CROP_BIAS), photo.height - H)
    return photo.crop((left, top, left + W, top + H))


def _scrim(img: Image.Image, start: float = 0.30) -> None:
    """Darken the lower part so text stays legible over any photograph."""
    overlay = Image.new("RGB", (W, H), INK_DEEP)
    mask = Image.new("L", (1, H))
    top = int(H * start)
    for y in range(H):
        if y < top:
            value = 0
        else:
            t = (y - top) / max(H - top, 1)
            value = int(255 * min(t ** 1.35 * 1.15, 0.94))
        mask.putpixel((0, y), value)
    img.paste(overlay, (0, 0), mask.resize((W, H)))


# A photo must be big enough that upscaling to feed width still looks clean,
# and portrait enough that a 4:5 crop does not decapitate it.
MIN_PHOTO_WIDTH = 700
PORTRAIT_RATIO = 0.95

INSET_TOP = 150
INSET_MAX_H = 600


def _inset(img: Image.Image, photo: Image.Image) -> None:
    """Letterbox a wide or square image into a rounded panel up top.

    Cover-cropping these would destroy them — several corpus assets are
    quote graphics or diagrams where the whole frame carries the meaning.
    """
    box_w, box_h = W - 2 * PAD, INSET_MAX_H
    scale = min(box_w / photo.width, box_h / photo.height)
    size = (max(int(photo.width * scale), 1), max(int(photo.height * scale), 1))
    photo = photo.convert("RGB").resize(size, Image.LANCZOS)

    radius = 22
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1],
                                           radius=radius, fill=255)
    x = (W - size[0]) // 2
    y = INSET_TOP + (box_h - size[1]) // 2

    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rounded_rectangle(
        [x, y + 10, x + size[0], y + size[1] + 14], radius=radius, fill=120)
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)),
              (0, 0), shadow.filter(ImageFilter.GaussianBlur(28)))
    img.paste(photo, (x, y), mask)


def _load_photo(path: str) -> tuple[Image.Image, str] | None:
    """Open a corpus image and decide which treatment it can carry."""
    try:
        with Image.open(path) as src:
            src.load()
            photo = src.convert("RGB")
    except Exception:
        return None
    if photo.width < MIN_PHOTO_WIDTH:
        return None                                  # too small; card reads better
    if photo.height / photo.width >= PORTRAIT_RATIO:
        return photo, "photo"        # full bleed under a scrim — the default look
    return photo, "inset"            # too wide to crop without wrecking it


def _eyebrow(draw, text: str, y: int) -> None:
    fnt = font("demi", 27)
    tracked(draw, (PAD, y), text.upper(), fnt, CYAN, tracking=4.5)


def _footer(draw) -> None:
    fnt = font("medium", 25)
    y = H - PAD - 16
    draw.line([(PAD, y - 26), (PAD + 54, y - 26)], fill=ACCENT, width=3)
    tracked(draw, (PAD + 76, y - 38), "SCIENTIFIC CHRONICLES", fnt, MUTED, tracking=3.2)


def _headline_block(draw, headline: str, bottom: int, max_lines: int = 3) -> int:
    """Draw the headline upward from `bottom`; returns the new top edge."""
    if not headline:
        return bottom
    fnt, lines = fit(draw, headline, "regular", W - 2 * PAD - 40, max_lines, 38, 26)
    step = int(fnt.size * 1.42)
    top = bottom - step * len(lines)
    for i, line in enumerate(lines):
        draw.text((PAD, top + i * step), line, font=fnt, fill=MUTED)
    return top


def render(*, title: str, eyebrow: str, headline: str, year: int | None,
           photo_path: str | None, out_path: Path) -> str:
    """Write the post image. Returns 'photo' or 'card'."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    origin = "card"
    img = None

    loaded = _load_photo(photo_path) if photo_path else None
    if loaded:
        photo, origin = loaded
        if origin == "photo":
            img = _cover(photo)
            _scrim(img, start=0.26)
        else:
            img = _background()
            _inset(img, photo)

    if img is None:
        origin = "card"
        img = _background()
        _rings(img)

    draw = ImageDraw.Draw(img)

    # Lay out from the bottom up so the title always sits on the rule.
    block_bottom = H - PAD - 110
    probe = ImageDraw.Draw(Image.new("RGB", (W, H)))
    hl_font, hl_lines = (None, [])
    if headline:
        hl_font, hl_lines = fit(probe, headline, "regular", W - 2 * PAD - 40, 3, 38, 26)
    hl_step = int(hl_font.size * 1.42) if hl_font else 0
    headline_top = block_bottom - hl_step * len(hl_lines) if hl_lines else block_bottom

    rule_y = headline_top - 40 if hl_lines else block_bottom
    title_font, title_lines = fit(probe, title, "bold", W - 2 * PAD, 3, 96, 46)
    title_step = int(title_font.size * 1.12)
    title_top = (rule_y - 46) - title_step * len(title_lines)

    # Oversized year, ghosted behind the title — card treatment only.
    if origin == "card" and year:
        yf = font("ultralight", 300)
        text = str(year)
        width = probe.textlength(text, font=yf)
        ghost = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ghost).text(
            (W - PAD - width, title_top - 268), text, font=yf, fill=(255, 255, 255, 38)
        )
        img = Image.alpha_composite(img.convert("RGBA"), ghost).convert("RGB")
        draw = ImageDraw.Draw(img)

    for i, line in enumerate(title_lines):
        draw.text((PAD, title_top + i * title_step), line, font=title_font, fill=WHITE)
    draw.line([(PAD, rule_y), (PAD + 96, rule_y)], fill=CYAN, width=5)
    for i, line in enumerate(hl_lines):
        draw.text((PAD, headline_top + i * hl_step), line, font=hl_font, fill=MUTED)
    _footer(draw)

    _eyebrow(draw, eyebrow, PAD)
    img.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True,
                            progressive=True, subsampling=0)
    return origin


def eyebrow_for(kind: str, occasion: str, today: date) -> str:
    stamp = today.strftime("%B %-d")
    if kind == "scientist":
        return f"{'Born' if occasion == 'Birth' else 'Died'} · {stamp}"
    return f"On this day · {stamp}"
