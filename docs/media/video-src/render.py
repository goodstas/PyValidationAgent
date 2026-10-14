"""Render stage.html frame-by-frame (deterministic setTime(t)) into an MP4 via ffmpeg, or into preview PNGs."""
import os
import subprocess
import sys

from playwright.sync_api import sync_playwright

mode, out = sys.argv[1], sys.argv[2]
FPS = 30
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
    pg = b.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
    pg.goto(os.environ.get("STAGE_URL", "http://127.0.0.1:8765/stage.html")); pg.evaluate("window.ready"); pg.wait_for_timeout(300)
    total = pg.evaluate("window.T_TOTAL")
    if mode == "preview":
        for t in (1.2, 4.0, 6.5, 9.2, 10.8, 12.0, 14.0, 16.2, 18.8):
            pg.evaluate(f"setTime({t})"); pg.screenshot(path=f"{out}/prev_{t:05.1f}.png")
    else:
        ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
                               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
        n = int(total * FPS)
        for i in range(n):
            pg.evaluate(f"setTime({i / FPS})")
            ff.stdin.write(pg.screenshot(type="png"))
        ff.stdin.close(); ff.wait(); print("frames", n, "rc", ff.returncode)
    b.close()
