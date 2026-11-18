"""Reusable motion presets for product ads (Blender + FFmpeg)."""

PRESETS = {
    "turntable": {"frames": 120, "fps": 24, "rotate": 360.0, "camera": "locked", "push": 0.0},
    "reveal":    {"frames": 96,  "fps": 24, "rotate": 40.0,  "camera": "locked", "push": 0.18},
    "orbit":     {"frames": 144, "fps": 24, "rotate": 300.0, "camera": "orbit",  "push": 0.0},
    "push_in":   {"frames": 72,  "fps": 24, "rotate": 15.0,  "camera": "locked", "push": 0.28},
    "pull_out":  {"frames": 72,  "fps": 24, "rotate": 15.0,  "camera": "locked", "push": -0.24},
}


def get(name: str) -> dict:
    return dict(PRESETS.get(name, PRESETS["turntable"]))