"""
Tests for Product Photo -> 3D (parametric core, CPU only).

Run: python tests/test_product3d.py
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402
from reavectors.ai import product3d  # noqa: E402


def make_bottle(w=400, h=800):
    """Synthetic front-facing bottle: body + shoulder + neck + cap + a label band."""
    img = Image.new("RGB", (w, h), (240, 240, 240))
    d = ImageDraw.Draw(img)
    d.rectangle([120, 300, 280, 760], fill=(30, 90, 160))      # body
    d.polygon([(120, 300), (200, 195), (280, 300)], fill=(30, 90, 160))  # shoulder
    d.rectangle([180, 150, 220, 200], fill=(30, 90, 160))      # neck
    d.rectangle([174, 138, 226, 156], fill=(200, 60, 60))      # cap
    d.rectangle([124, 420, 276, 620], fill=(250, 250, 250))    # label
    d.text((150, 500), "AQUA", fill=(20, 20, 20))
    return img


def make_can(w=400, h=700):
    img = Image.new("RGB", (w, h), (245, 245, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([120, 140, 280, 660], fill=(40, 140, 60))      # straight can
    return img


def test_bottle_detected_with_neck():
    b = io.BytesIO(); make_bottle().save(b, "PNG")
    spec = product3d.analyze_product(b.getvalue())
    assert spec["package"]["type"] == "bottle", spec["package"]
    assert spec["package"]["has_neck"] is True
    assert len(spec["profile"]) >= 10
    assert spec["profile"][0][0] > 0 and spec["profile"][-1][0] > 0


def test_can_detected_no_neck():
    b = io.BytesIO(); make_can().save(b, "PNG")
    spec = product3d.analyze_product(b.getvalue())
    assert spec["package"]["type"] in ("can", "container"), spec["package"]


def test_label_rectified_from_photo():
    b = io.BytesIO(); make_bottle().save(b, "PNG")
    spec = product3d.analyze_product(b.getvalue())
    assert spec["label"]["source"] == "rectified_from_photo"
    assert spec["label"]["image"].startswith("data:image/png;base64,")
    assert spec["label"]["quad"] is not None


def test_supplied_label_is_used_verbatim():
    b = io.BytesIO(); make_bottle().save(b, "PNG")
    lab = io.BytesIO(); Image.new("RGB", (600, 300), (255, 210, 0)).save(lab, "PNG")
    spec = product3d.analyze_product(b.getvalue(), label_bytes=lab.getvalue())
    assert spec["label"]["source"] == "supplied_asset"


def test_rectify_label_size():
    img = make_bottle()
    out = product3d.rectify_label(img, [(120, 420), (280, 420), (280, 620), (120, 620)])
    assert out.size == (640, 480)


def test_quality_report_warns_inference():
    b = io.BytesIO(); make_bottle().save(b, "PNG")
    spec = product3d.analyze_product(b.getvalue())
    q = spec["quality"]
    assert q["confidence"] in ("low", "medium", "high")
    assert any("INFERRED" in w for w in q["warnings"])


def test_blank_image_rejected():
    b = io.BytesIO(); Image.new("RGB", (200, 200), (250, 250, 250)).save(b, "PNG")
    try:
        product3d.analyze_product(b.getvalue()); assert False, "should reject a blank image"
    except ValueError:
        pass


def test_materials_are_labelled_as_inferred():
    b = io.BytesIO(); make_bottle().save(b, "PNG")
    spec = product3d.analyze_product(b.getvalue())
    assert spec["materials"]["note"].lower().startswith("material is inferred")


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1; print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests)-failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_all())
