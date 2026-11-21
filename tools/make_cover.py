#!/usr/bin/env python3
"""Draw the article cover: three clouds, each dropping its card into one chat window. No text.

usage: python3 tools/make_cover.py OUT_DIR
Writes devto-cover.<hash>.jpg (1376x578) and builder-cover.<hash>.jpg (1200x675).
"""

import hashlib
import io
import math
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFilter

S = 2
SURFACE = (26, 26, 25)
PAPER = (236, 234, 226)
RULE = (58, 58, 55)
MUTED = (128, 127, 120)
BLUE = (57, 135, 229)
ORANGE = (217, 89, 38)
TEAL = (38, 166, 154)


def cloud(d, cx, cy, r, colour):
    for dx, dy, k in [(-1.0, 0.25, 0.75), (0.0, -0.15, 1.0), (1.0, 0.25, 0.75), (-0.5, 0.45, 0.7), (0.5, 0.45, 0.7)]:
        rr = r * k
        x, y = cx + dx * r, cy + dy * r
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=colour)


def card(d, x, y, w, h, accent, kind):
    d.rounded_rectangle([x, y, x + w, y + h], radius=12 * S, fill=PAPER)
    d.rectangle([x, y, x + 8 * S, y + h], fill=accent)
    pad = 12 * S
    d.rounded_rectangle([x + 2 * pad, y + pad, x + w * 0.45, y + pad + 8 * S], radius=4 * S, fill=MUTED)
    bx0, by0, bx1, by1 = x + 2 * pad, y + pad + 16 * S, x + w - 2 * pad, y + h - pad
    if kind == "rate":
        mid = (by0 + by1) / 2
        d.rounded_rectangle([bx0, by0, bx0 + (bx1 - bx0) * 0.7, mid + 2 * S], radius=6 * S, fill=accent)
        d.rounded_rectangle([bx0, mid + 8 * S, bx0 + (bx1 - bx0) * 0.4, by1], radius=4 * S, fill=MUTED)
    elif kind == "line":
        pts = []
        for i in range(13):
            t = i / 12
            pts.append((bx0 + t * (bx1 - bx0), by1 - (0.25 + 0.5 * (0.5 + 0.5 * math.sin(t * 5.2 + 0.6)) * (0.6 + 0.4 * t)) * (by1 - by0)))
        d.line(pts, fill=accent, width=5 * S, joint="curve")
    else:
        n, gap = 4, 12 * S
        bw = ((bx1 - bx0) - gap * (n - 1)) / n
        for i, hgt in enumerate([0.55, 0.85, 0.4, 0.7]):
            x0 = bx0 + i * (bw + gap)
            d.rounded_rectangle([x0, by1 - hgt * (by1 - by0), x0 + bw, by1], radius=5 * S, fill=accent)


def draw(W, H):
    W2, H2 = W * S, H * S
    img = Image.new("RGB", (W2, H2), SURFACE)
    glow = Image.new("RGB", (W2, H2), SURFACE)
    g = ImageDraw.Draw(glow)
    d = ImageDraw.Draw(img)

    # the chat window, centre bottom
    cw, ch = W2 * 0.36, H2 * 0.5
    cx0, cy0 = (W2 - cw) / 2, H2 * 0.42
    g.rounded_rectangle([cx0 - 30, cy0 - 30, cx0 + cw + 30, cy0 + ch + 30], radius=40 * S, fill=(60, 60, 56))
    glow = glow.filter(ImageFilter.GaussianBlur(28 * S))
    img = Image.blend(img, glow, 0.6)
    d = ImageDraw.Draw(img)

    clouds = [(0.17, BLUE, "rate"), (0.5, ORANGE, "line"), (0.83, TEAL, "bar")]
    slots = []
    # three cards stacked inside the chat window
    sw, sh, sgap = cw * 0.86, (ch - 4 * 14 * S) / 3, 14 * S
    for i in range(3):
        slots.append((cx0 + (cw - sw) / 2, cy0 + sgap + i * (sh + sgap)))
    # links from each cloud to its card
    for (fx, colour, _), (sx, sy) in zip(clouds, slots):
        x0, y0 = W2 * fx, H2 * 0.2
        x1, y1 = sx + (0 if fx < 0.5 else sw if fx > 0.5 else sw / 2), sy + sh / 2
        if fx == 0.5:
            x1, y1 = sx + sw / 2, cy0
        pts = []
        for i in range(41):
            t = i / 40
            if fx == 0.5:
                pts.append((x0, y0 + t * (y1 - y0)))
            else:
                mx = x0 + (x1 - x0) * t
                my = y0 + (y1 - y0) * (1 - (1 - t) ** 2.2)
                pts.append((mx, my))
        for wdt, a in [(14 * S, 0.18), (4 * S, 1.0)]:
            c = tuple(int(SURFACE[k] + (colour[k] - SURFACE[k]) * a) for k in range(3))
            d.line(pts, fill=c, width=int(wdt), joint="curve")
    d.rounded_rectangle([cx0, cy0, cx0 + cw, cy0 + ch], radius=22 * S, fill=(38, 38, 36), outline=RULE, width=3 * S)
    for (fx, colour, kind), (sx, sy) in zip(clouds, slots):
        card(d, sx, sy, sw, sh, colour, kind)
        cloud(d, W2 * fx, H2 * 0.2, H2 * 0.075, colour)
    return img.resize((W, H), Image.LANCZOS)


def save(img, out_dir, stem):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    h = hashlib.sha256(buf.getvalue()).hexdigest()[:8]
    path = out_dir / f"{stem}.{h}.jpg"
    path.write_bytes(buf.getvalue())
    print("wrote", path, img.size)


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1])
    save(draw(1376, 578), out, "devto-cover")
    save(draw(1200, 675), out, "builder-cover")
