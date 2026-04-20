"""Record guardianlens_animation.html as MP4 and MOV.

Playwright records the browser as WebM, then ffmpeg converts to both formats.

Run from repo root:
    python scripts/record_animation.py
"""

import asyncio
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "outputs"
WEBM = OUT_DIR / "guardianlens_demo.webm"
MP4  = OUT_DIR / "guardianlens_demo.mp4"
MOV  = OUT_DIR / "guardianlens_demo.mov"

ANIMATION_URL = "http://127.0.0.1:8090/guardianlens_animation.html"
ANIMATION_DURATION_S = 50   # slightly longer than 47.5s to catch fade-out


async def record() -> None:
    from playwright.async_api import async_playwright

    print(f"Recording {ANIMATION_URL} …")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--autoplay-policy=no-user-gesture-required"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            record_video_dir=str(OUT_DIR),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = await ctx.new_page()
        await page.goto(ANIMATION_URL, wait_until="networkidle")

        # Give the page a moment to fully render fonts/images before the
        # animation timeline fires (it auto-starts 200ms after load).
        await page.wait_for_timeout(500)

        print(f"  waiting {ANIMATION_DURATION_S}s for animation to finish …")
        await page.wait_for_timeout(ANIMATION_DURATION_S * 1000)

        await page.close()
        video_path = await ctx.pages[0].video.path() if ctx.pages else None
        await ctx.close()
        await browser.close()

    # Playwright saves the video with a UUID filename; find it.
    webm_files = sorted(OUT_DIR.glob("*.webm"), key=lambda f: f.stat().st_mtime)
    if not webm_files:
        raise RuntimeError("No WebM output found — recording may have failed.")
    raw_webm = webm_files[-1]
    raw_webm.rename(WEBM)
    print(f"  raw recording → {WEBM} ({WEBM.stat().st_size // 1024} KB)")


def convert() -> None:
    # MP4 — H.264, high quality, web-compatible
    print("Converting to MP4 …")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(WEBM),
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(MP4),
    ], check=True)
    print(f"  → {MP4} ({MP4.stat().st_size // 1024} KB)")

    # MOV — Apple ProRes 422 HQ, best quality for editing / Quicktime
    print("Converting to MOV (ProRes 422 HQ) …")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(WEBM),
        "-c:v", "prores_ks",
        "-profile:v", "3",          # ProRes 422 HQ
        "-vendor", "apl0",
        "-pix_fmt", "yuv422p10le",
        str(MOV),
    ], check=True)
    print(f"  → {MOV} ({MOV.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(record())
    convert()
    print("\n✓ Done.")
    print(f"   MP4 : {MP4}")
    print(f"   MOV : {MOV}")
