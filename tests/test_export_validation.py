"""Export-structure validation (SVG/EPS/PDF, and .ai as PDF-compatible)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reavectors.export import validate_export  # noqa: E402


def test_svg_ok():
    ok, _ = validate_export("svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    assert ok


def test_svg_bad():
    ok, reason = validate_export("svg", b"not an svg")
    assert not ok and reason


def test_eps_ok():
    ok, _ = validate_export("eps", b"%!PS-Adobe-3.0 EPSF-3.0\n%%EOF\n")
    assert ok


def test_pdf_and_ai_ok():
    data = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\ntrailer\n%%EOF\n"
    assert validate_export("pdf", data)[0]
    assert validate_export("ai", data)[0]      # .ai is PDF-compatible


def test_pdf_bad():
    assert not validate_export("pdf", b"%PDF-1.7\nno eof")[0]


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