"""Test helper (t_e2db63f0): a valid Your turn observation backed by a real temp screenshot file."""
import os, tempfile
_SHOT = os.path.join(tempfile.mkdtemp(prefix="yt-shot-"), "verify.png")
open(_SHOT, "wb").write(b"\x89PNG-test")

def obs(observed_type, day="2026-10-20", **kw):
    o = {"observed_type": observed_type, "screenshot": _SHOT, "price_seen": "none", "observed_at": day, "url": "https://a.example/verify"}
    o.update(kw); return o
