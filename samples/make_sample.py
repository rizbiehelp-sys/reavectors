"""
Create a synthetic transparent PNG for testing reavectors.

Produces samples/sample-logo.png: a few flat shapes with hard-ish edges and some
anti-aliasing, on a fully transparent background. Entirely invented; nothing
here relates to any third party's artwork.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sample-logo.png")


def main():
    W = H = 512
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # badge ring
    d.ellipse([56, 56, 456, 456], fill=(11, 11, 11, 255))
    d.ellipse([86, 86, 426, 426], fill=(254, 86, 75, 255))
    d.ellipse([120, 120, 392, 392], fill=(254, 254, 254, 255))

    # a teal "R" block mark
    d.rectangle([196, 196, 246, 336], fill=(0, 209, 200, 255))
    d.rectangle([196, 196, 316, 246], fill=(0, 209, 200, 255))
    d.rectangle([266, 196, 316, 266], fill=(0, 209, 200, 255))
    d.rectangle([196, 246, 316, 266], fill=(0, 209, 200, 255))
    d.polygon([(266, 266), (316, 266), (316, 336), (266, 336)], fill=(0, 209, 200, 255))

    # a small white notch
    d.ellipse([180, 250, 210, 282], fill=(254, 254, 254, 255))

    img.save(OUT)
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
