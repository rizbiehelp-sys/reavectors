"""Validates the Blender scripts parse and expose the expected shapes/exports.
(Blender itself isn't required here; this is a static check.)"""
from __future__ import annotations

import ast
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "blender", "scripts")


def test_scripts_parse():
    files = glob.glob(os.path.join(SCRIPTS, "*.py"))
    assert len(files) >= 4, files
    for f in files:
        ast.parse(open(f, encoding="utf-8").read(), filename=f)


def test_build_supports_shapes():
    s = open(os.path.join(SCRIPTS, "build_product.py"), encoding="utf-8").read()
    for kind in ("bottle", "jar", "can", "tube", "box"):
        assert kind in s, kind


def test_export_validates_glb():
    s = open(os.path.join(SCRIPTS, "export_glb.py"), encoding="utf-8").read()
    assert "glTF" in s and "valid_glb" in s


def test_common_has_uv_and_lathe():
    s = open(os.path.join(SCRIPTS, "common.py"), encoding="utf-8").read()
    assert "def lathe" in s and "def uv_cylindrical" in s and "export_scene.gltf" in s


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