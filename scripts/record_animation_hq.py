"""Record guardianlens_animation.html at full quality using Xvfb + ffmpeg.

Strategy (2-phase):
  Phase 1 — capture: x11grab → lossless H.264 (ultrafast, qp 0).
            Very low CPU overhead so ffmpeg never drops frames and the
            animation plays at exactly real-time speed.
  Phase 2 — encode: lossless source → ProRes 422 HQ MOV + H.264 CRF 15 MP4.

Run from repo root:
    python scripts/record_animation_hq.py
"""

import subprocess
import time
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR      = PROJECT_ROOT / "outputs"
LOSSLESS     = OUT_DIR / "guardianlens_capture.mkv"   # temp, deleted after
MP4          = OUT_DIR / "guardianlens_demo.mp4"
MOV          = OUT_DIR / "guardianlens_demo.mov"

ANIMATION_URL      = "http://127.0.0.1:8090/guardianlens_animation.html?record"
ANIMATION_DURATION = 54      # seconds — enough for full animation + fade-out
DISPLAY_NUM        = 99
WIDTH, HEIGHT      = 1920, 1080
FPS                = 30

DISPLAY = f":{DISPLAY_NUM}"
SCREEN  = f"{DISPLAY}.0"


def run(*args, **kwargs):
    return subprocess.Popen(list(args), **kwargs)


def kill(proc):
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


procs = []

def cleanup(*_):
    for p in procs:
        kill(p)
    sys.exit(0)

signal.signal(signal.SIGINT,  cleanup)
signal.signal(signal.SIGTERM, cleanup)


def phase1_capture():
    print("Starting Xvfb …")
    xvfb = run(
        "Xvfb", DISPLAY,
        "-screen", "0", f"{WIDTH}x{HEIGHT}x24",
        "-ac", "+extension", "GLX", "+render", "-noreset",
    )
    procs.append(xvfb)
    time.sleep(1.5)

    print("Launching Chromium …")
    chrome = run(
        "chromium",
        f"--display={DISPLAY}",
        f"--app={ANIMATION_URL}",
        f"--window-size={WIDTH},{HEIGHT}",
        "--start-maximized",
        "--noerrdialogs",
        "--disable-infobars",
        "--no-first-run",
        "--disable-session-crashed-bubble",
        "--disable-extensions",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-font-subpixel-positioning",
        "--font-render-hinting=full",
        "--ignore-gpu-blocklist",
        "--enable-gpu-rasterization",
        env={**__import__("os").environ, "DISPLAY": DISPLAY},
    )
    procs.append(chrome)
    time.sleep(3)   # let page fully load and animation start

    # Lossless capture — ultrafast preset + qp 0 keeps CPU usage minimal
    # so the encoder never lags behind real-time capture.
    print(f"Capturing {ANIMATION_DURATION}s → lossless MKV …")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "x11grab",
        "-draw_mouse", "0",
        "-framerate", str(FPS),
        "-video_size", f"{WIDTH}x{HEIGHT}",
        "-i", SCREEN,
        "-t", str(ANIMATION_DURATION),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-qp", "0",
        str(LOSSLESS),
    ], check=True)
    size_mb = LOSSLESS.stat().st_size // (1024 * 1024)
    print(f"  → {LOSSLESS} ({size_mb} MB)")

    kill(chrome)
    kill(xvfb)
    procs.clear()


def phase2_encode():
    # ── MOV: ProRes 422 HQ ──────────────────────────────────────────────
    print("Encoding MOV (ProRes 422 HQ) …")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(LOSSLESS),
        "-c:v", "prores_ks",
        "-profile:v", "3",       # 422 HQ
        "-vendor", "apl0",
        "-pix_fmt", "yuv422p10le",
        str(MOV),
    ], check=True)
    print(f"  → {MOV} ({MOV.stat().st_size // (1024*1024)} MB)")

    # ── MP4: H.264 CRF 15 (near-lossless, web-compatible) ───────────────
    print("Encoding MP4 (H.264 CRF 15) …")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(LOSSLESS),
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "15",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(MP4),
    ], check=True)
    print(f"  → {MP4} ({MP4.stat().st_size // 1024} KB)")

    LOSSLESS.unlink(missing_ok=True)
    print("  (temp lossless file removed)")


if __name__ == "__main__":
    phase1_capture()
    phase2_encode()
    print("\n✓ Done.")
    print(f"   MOV : {MOV}")
    print(f"   MP4 : {MP4}")
