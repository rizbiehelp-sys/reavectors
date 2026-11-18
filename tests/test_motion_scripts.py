import ast, glob, os
SC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blender", "scripts")
def test_motion_scripts_parse():
    for f in ("presets.py", "animate_product.py", "render_video.py"):
        ast.parse(open(os.path.join(SC, f), encoding="utf-8").read(), filename=f)
def test_presets_present():
    s = open(os.path.join(SC, "presets.py"), encoding="utf-8").read()
    for p in ("turntable", "reveal", "orbit", "push_in", "pull_out"):
        assert p in s, p
def test_render_video_ffmpeg():
    s = open(os.path.join(SC, "render_video.py"), encoding="utf-8").read()
    assert "libx264" in s and "ffmpeg" in s
def run_all():
    ts = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    f = 0
    for t in ts:
        try: t(); print("PASS", t.__name__)
        except Exception as e: f += 1; print("FAIL", t.__name__, e)
    print(f"\n{len(ts)-f}/{len(ts)} passed"); return 1 if f else 0
if __name__ == "__main__": raise SystemExit(run_all())
