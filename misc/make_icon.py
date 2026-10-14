"""Generate the Spikeless app icon: one narrow radio-HPLC peak (magenta, tailing a little to
the right, as real peaks do) on a flat baseline, its apex marked by a white crosshair, on a
dark rounded tile. Run: python misc/make_icon.py  (needs Pillow)

Writes a multi-resolution .ico and a 256 px .png into the package assets, so the app and the
launcher show it without Pillow at runtime.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src" / "spikeless" / "assets"
PINK, FILL = (255, 45, 180, 255), (150, 20, 120, 255)


def render(size: int) -> Image.Image:
    ss = size * 4                                   # supersampled, then downscaled
    im = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, ss - 1, ss - 1], radius=ss // 6, fill=(35, 35, 35, 255))
    base, height, cx = ss * 0.80, ss * 0.52, ss * 0.47
    pts = []
    for i in range(401):                            # the trace, left to right
        x = ss * (0.10 + 0.80 * i / 400)
        sigma = ss * (0.022 if x < cx else 0.034)   # steeper front, longer tail
        pts.append((x, base - height * math.exp(-0.5 * ((x - cx) / sigma) ** 2)))
    d.polygon(pts + [(pts[-1][0], base), (pts[0][0], base)], fill=FILL)
    d.line(pts, fill=PINK, width=max(4, round(ss * 0.022)), joint="curve")
    ay = base - height                              # the crosshair on the apex
    arm, gap, w = ss * 0.08, ss * 0.035, max(3, round(ss * 0.014))
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        d.line([(cx + dx * gap, ay + dy * gap), (cx + dx * arm, ay + dy * arm)],
               fill=(255, 255, 255, 255), width=w)
    r = ss * 0.025
    d.ellipse([cx - r, ay - r, cx + r, ay + r], outline=(255, 255, 255, 255), width=w)
    return im.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 48, 64, 128, 256]
    imgs = [render(s) for s in sizes]
    imgs[-1].save(OUT / "spikeless.png")
    imgs[-1].save(OUT / "spikeless.ico", sizes=[(s, s) for s in sizes])
    print("wrote", OUT / "spikeless.ico", "and spikeless.png")


if __name__ == "__main__":
    main()
