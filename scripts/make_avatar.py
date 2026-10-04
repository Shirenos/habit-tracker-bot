"""Generate docs/avatar.png: a green gradient tile with a target, a check mark and a streak flame.

Usage:  python scripts/make_avatar.py [output.png]      (requires: pip install pillow)

The picture is drawn at 2x and downsampled for smooth edges. Telegram crops bot photos to a
circle, so everything important stays inside the central ~80% of the square. Upload the result
through @BotFather -> /setuserpic (the Bot API cannot set a bot's photo).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
SCALE = 2
S = SIZE * SCALE

Color = tuple[int, ...]


def lerp(a: Color, b: Color, t: float) -> Color:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def gradient() -> Image.Image:
    """Diagonal emerald -> teal -> deep blue gradient."""
    stops = [(0.0, (34, 197, 94)), (0.55, (13, 148, 136)), (1.0, (14, 116, 144))]
    small = Image.new("RGB", (256, 256))
    px = small.load()
    for y in range(256):
        for x in range(256):
            t = (x + y) / 510
            for (t0, c0), (t1, c1) in zip(stops, stops[1:], strict=False):
                if t <= t1:
                    px[x, y] = lerp(c0, c1, (t - t0) / (t1 - t0))
                    break
    return small.resize((S, S), Image.Resampling.BICUBIC)


def shadow_layer(draw_fn, blur: float, offset: int = 0) -> Image.Image:
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer), offset)
    return layer.filter(ImageFilter.GaussianBlur(blur))


def thick_polyline(d: ImageDraw.ImageDraw, points, width: int, fill) -> None:
    """Polyline with round joins and caps."""
    d.line(points, fill=fill, width=width, joint="curve")
    r = width / 2
    for x, y in (points[0], points[-1], *points[1:-1]):
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def circle(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, **kwargs) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), **kwargs)


def flame_points(cx: float, cy: float, h: float, steps: int = 80) -> list[tuple[float, float]]:
    """Outline of a teardrop flame with a leaning tip; ``h`` is the total height."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        y = 1 - t  # 0 = tip, 1 = base
        width = math.sin(math.pi * t**0.8) * (0.5 + 0.15 * t)  # widest near the base
        sway = 0.18 * (1 - t) ** 2  # tip leans to the right
        pts.append((cx + (sway + width * 0.5) * h * 0.62, cy - h / 2 + (1 - y) * h))
    for i in range(steps, -1, -1):
        t = i / steps
        y = 1 - t
        width = math.sin(math.pi * t**0.8) * (0.5 + 0.15 * t)
        sway = 0.18 * (1 - t) ** 2
        pts.append((cx + (sway - width * 0.5) * h * 0.62, cy - h / 2 + (1 - y) * h))
    return pts


def draw_flame(d: ImageDraw.ImageDraw, cx: float, cy: float, h: float) -> None:
    d.polygon(flame_points(cx, cy, h), fill=(249, 115, 22, 255))
    d.polygon(flame_points(cx + h * 0.01, cy + h * 0.1, h * 0.72), fill=(253, 186, 36, 255))
    d.polygon(flame_points(cx + h * 0.02, cy + h * 0.2, h * 0.4), fill=(254, 240, 138, 255))


def build() -> Image.Image:
    img = gradient().convert("RGBA")

    # soft glow blobs for depth
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-S * 0.2, -S * 0.25, S * 0.6, S * 0.45), fill=(255, 255, 255, 70))
    gd.ellipse((S * 0.55, S * 0.65, S * 1.2, S * 1.25), fill=(255, 255, 255, 35))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(S * 0.06)))

    cx, cy, radius = S * 0.47, S * 0.47, S * 0.31

    # target: drop shadow, white disc, concentric green rings
    img = Image.alpha_composite(
        img,
        shadow_layer(
            lambda d, o: circle(d, cx, cy + o, radius, fill=(4, 47, 46, 150)),
            S * 0.025,
            int(S * 0.025),
        ),
    )
    d = ImageDraw.Draw(img)
    circle(d, cx, cy, radius, fill=(255, 255, 255, 255))
    circle(d, cx, cy, radius * 0.80, fill=(220, 252, 231, 255))
    circle(d, cx, cy, radius * 0.60, fill=(255, 255, 255, 255))
    circle(d, cx, cy, radius * 0.40, fill=(34, 197, 94, 255))

    # check mark in the bull's eye
    k = radius * 0.40
    check = [
        (cx - k * 0.52, cy + k * 0.02),
        (cx - k * 0.12, cy + k * 0.42),
        (cx + k * 0.58, cy - k * 0.40),
    ]
    thick_polyline(d, check, int(S * 0.036), (255, 255, 255, 255))

    # arrow-less "streak" ticks around the target (7 dots = a week)
    for i in range(7):
        a = math.radians(-90 + i * 360 / 7)
        px, py = cx + math.cos(a) * radius * 1.14, cy + math.sin(a) * radius * 1.14
        circle(d, px, py, S * 0.011, fill=(255, 255, 255, 220 if i < 5 else 110))

    # flame badge (bottom-right) = the streak
    bx, by, br = S * 0.73, S * 0.74, S * 0.145
    img = Image.alpha_composite(
        img,
        shadow_layer(
            lambda d, o: circle(d, bx, by + o, br, fill=(4, 47, 46, 140)), S * 0.018, int(S * 0.014)
        ),
    )
    d = ImageDraw.Draw(img)
    circle(d, bx, by, br, fill=(255, 255, 255, 255))
    circle(d, bx, by, br * 0.88, fill=(255, 237, 213, 255))
    draw_flame(d, bx, by + br * 0.04, br * 1.25)

    return img.resize((SIZE, SIZE), Image.Resampling.LANCZOS).convert("RGB")


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).parent.parent / "docs" / "avatar.png"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    build().save(out, optimize=True)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
