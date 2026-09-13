"""Render a 1080x1350 (4:5) Instagram image for a candidate.

Two treatments, sharing one type system so the feed looks consistent:
  * photo  - the corpus asset, cover-cropped full bleed under a bottom scrim
  * card   - a typographic card, used when no image asset exists
"""
from __future__ import annotations

import os
import sys
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

# Inter is bundled (SIL OFL) so a post renders identically on macOS and on a
# Linux server. The host-font fallbacks exist only for a stripped checkout;
# they change the look, so the bundled files are the real answer.
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
HELV = "/System/Library/Fonts/HelveticaNeue.ttc"
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
DEJAVU = "/usr/share/fonts/truetype/dejavu"

FACES = {
    #           bundled Inter                    macOS fallback   DejaVu fallback
    "bold":       ("InterDisplay-Bold.ttf",      (AVENIR, 0), "DejaVuSans-Bold.ttf"),
    "demi":       ("Inter-SemiBold.ttf",         (AVENIR, 2), "DejaVuSans-Bold.ttf"),
    "medium":     ("Inter-Medium.ttf",           (AVENIR, 5), "DejaVuSans.ttf"),
    "regular":    ("Inter-Regular.ttf",          (AVENIR, 7), "DejaVuSans.ttf"),
    "light":      ("Inter-Light.ttf",            (HELV, 7),   "DejaVuSans-ExtraLight.ttf"),
    "ultralight": ("InterDisplay-ExtraLight.ttf", (HELV, 5),  "DejaVuSans-ExtraLight.ttf"),
}


class FontsMissing(RuntimeError):
    pass


def font(face: str, size: int) -> ImageFont.FreeTypeFont:
    bundled, (mac_path, mac_index), dejavu = FACES[face]

    candidate = os.path.join(FONT_DIR, bundled)
    if os.path.isfile(candidate):
        return ImageFont.truetype(candidate, size)

    if os.path.isfile(mac_path):
        return ImageFont.truetype(mac_path, size, index=mac_index)

    candidate = os.path.join(DEJAVU, dejavu)
    if os.path.isfile(candidate):
        return ImageFont.truetype(candidate, size)

    raise FontsMissing(
        f"no font for '{face}'. Expected {os.path.join(FONT_DIR, bundled)} — "
        "the bundled Inter files are part of the repo; re-pull or re-deploy."
    )


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
# the lower third of the frame is where the type goes anyway. Used only when
# no face is found.
CROP_BIAS = 0.12

# Type occupies roughly the bottom 40%; a face must stay clear of it.
TEXT_TOP_FRACTION = 0.60
# Where a detected face should sit vertically in the finished frame.
FACE_TARGET = 0.30
# A face filling more than this much of the source means a tight head-shot:
# cropping only magnifies it further, so the whole frame is kept instead.
TIGHT_FACE_FRACTION = 0.38
# Detections smaller than this are noise, not the subject.
MIN_FACE_FRACTION = 0.10

# Vertical band the fit-blur photo may occupy: below the eyebrow, above the
# title. Keeping these explicit is what stops the type colliding with it.
FITBLUR_TOP = 132
FITBLUR_BOTTOM = 792

_detector = None
_detector_ready = False


def _face_detector():
    """Haar frontal-face detector, or None if OpenCV is unavailable."""
    global _detector, _detector_ready
    if _detector_ready:
        return _detector
    _detector_ready = True
    try:
        import cv2
        path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        if os.path.isfile(path):
            _detector = cv2.CascadeClassifier(path)
    except Exception:
        _detector = None
    return _detector


def face_box(photo: Image.Image):
    """(x, y, w, h) of the subject's face, or None when nothing is trustworthy."""
    detector = _face_detector()
    if detector is None:
        return None
    try:
        import cv2
        import numpy as np
        gray = cv2.cvtColor(np.array(photo.convert("RGB")), cv2.COLOR_RGB2GRAY)
        gray = cv2.equalizeHist(gray)
        found = detector.detectMultiScale(
            gray, 1.1, 5,
            minSize=(max(30, photo.width // 14), max(30, photo.height // 14)))
    except Exception:
        return None
    if len(found) == 0:
        return None
    x, y, w, h = max(found, key=lambda f: int(f[2]) * int(f[3]))
    if h < photo.height * MIN_FACE_FRACTION:
        return None            # too small to be the portrait subject
    return int(x), int(y), int(w), int(h)


def _cover(photo: Image.Image, face=None) -> Image.Image:
    """Scale-and-crop to fill 1080x1350, composing around the face when known."""
    photo = photo.convert("RGB")
    scale = max(W / photo.width, H / photo.height)
    new = (max(int(photo.width * scale + 0.5), W), max(int(photo.height * scale + 0.5), H))
    scaled = photo.resize(new, Image.LANCZOS)

    max_top = scaled.height - H
    max_left = scaled.width - W

    if face:
        fx, fy, fw, fh = (round(v * scale) for v in face)
        # Put the face at FACE_TARGET of the frame, then make sure the chin
        # clears the type; clamp to what the image actually allows.
        top = fy + fh / 2 - H * FACE_TARGET
        overlap = (fy + fh) - (top + H * TEXT_TOP_FRACTION)
        if overlap > 0:
            top += overlap
        left = fx + fw / 2 - W / 2
        top = int(max(0, min(top, max_top)))
        left = int(max(0, min(left, max_left)))
    else:
        top = min(int(max_top * CROP_BIAS), max_top)
        left = max_left // 2

    return scaled.crop((left, top, left + W, top + H))


def _fit_blur(photo: Image.Image) -> Image.Image:
    """Show the whole photograph over a blurred fill of itself.

    For a tight head-shot there is no headroom to crop into, so cropping just
    magnifies the face and pushes the chin under the type. Keeping the frame
    intact reads better and never truncates the subject.
    """
    photo = photo.convert("RGB")
    backdrop = _cover(photo).filter(ImageFilter.GaussianBlur(52))
    backdrop = Image.blend(backdrop, Image.new("RGB", (W, H), INK), 0.62)

    # The photo lives strictly between the eyebrow and the title, so neither
    # ever lands on top of it.
    box_w = W - 2 * PAD
    box_h = FITBLUR_BOTTOM - FITBLUR_TOP
    scale = min(box_w / photo.width, box_h / photo.height)
    size = (max(int(photo.width * scale), 1), max(int(photo.height * scale), 1))
    front = photo.resize(size, Image.LANCZOS)

    x = (W - size[0]) // 2
    y = FITBLUR_TOP + (box_h - size[1]) // 2
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rectangle([x, y + 12, x + size[0], y + size[1] + 16], fill=130)
    backdrop.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0),
                   shadow.filter(ImageFilter.GaussianBlur(30)))
    backdrop.paste(front, (x, y))
    return backdrop


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


def _load_photo(path: str) -> tuple[Image.Image, str, tuple | None] | None:
    """Open an image and decide which treatment suits it."""
    if not os.path.isfile(path):
        print(f"render: image not found, falling back to a card: {path}", file=sys.stderr)
        return None
    try:
        with Image.open(path) as src:
            src.load()
            photo = src.convert("RGB")
    except Exception as exc:
        print(f"render: cannot read {path} ({exc}); falling back to a card", file=sys.stderr)
        return None
    if photo.width < MIN_PHOTO_WIDTH:
        return None                                  # too small; card reads better
    if photo.height / photo.width < PORTRAIT_RATIO:
        return photo, "inset", None                  # too wide to crop safely

    face = face_box(photo)
    if face and face[3] >= photo.height * TIGHT_FACE_FRACTION:
        return photo, "fitblur", face                # tight head-shot; do not crop
    return photo, "photo", face


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
        photo, origin, face = loaded
        if origin == "photo":
            img = _cover(photo, face)
            _scrim(img, start=0.26)
        elif origin == "fitblur":
            img = _fit_blur(photo)
            _scrim(img, start=0.60)
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
