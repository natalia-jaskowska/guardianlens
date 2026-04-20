"""Render every Minecraft scene as a real-gameplay screenshot.

Uses ``outputs/demo_html/minecraft_real.html`` — a 1280×720 template
that overlays the scene's chat in classic Minecraft in-game style
(white text with drop-shadow, player tags in colour, translucent
black background) on a real Minecraft gameplay photo.

Writes PNGs to ``outputs/video_feeds/demo_script/<tag>.png`` and
symlinks them into ``outputs/screenshots/<tag>.png`` so the FastAPI
``/screenshots/`` mount can serve them.

Run from repo root::

    python scripts/render_minecraft_html_scenes.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_demo_db import SCENES  # noqa: E402


TEMPLATE_URL = (PROJECT_ROOT / "outputs" / "demo_html" / "minecraft_real.html").resolve().as_uri()
DEMO_DIR = PROJECT_ROOT / "outputs" / "video_feeds" / "demo_script"
SCREENS_DIR = PROJECT_ROOT / "outputs" / "screenshots"


def build_scene_json(scene: dict) -> dict:
    messages = []
    for sender, text in scene["messages"]:
        messages.append({"sender": sender, "text": text})
    return {
        "child":    "ava_l",
        "messages": messages,
    }


async def render_all() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    SCREENS_DIR.mkdir(parents=True, exist_ok=True)

    mc_scenes = [s for s in SCENES if s["platform"] == "Minecraft"]
    print(f"Rendering {len(mc_scenes)} Minecraft scene(s)…")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for i, scene in enumerate(mc_scenes):
                tag = scene["tag"]
                scene_json = build_scene_json(scene)
                url = f"{TEMPLATE_URL}?v={i}#{quote(json.dumps(scene_json))}"

                page = await browser.new_page(
                    viewport={"width": 1280, "height": 720},
                    device_scale_factor=2,
                )
                try:
                    await page.goto(url, wait_until="networkidle")
                    await page.wait_for_timeout(500)

                    out_png = DEMO_DIR / f"{tag}.png"
                    await page.screenshot(
                        path=str(out_png),
                        clip={"x": 0, "y": 0, "width": 1280, "height": 720},
                    )
                finally:
                    await page.close()

                link = SCREENS_DIR / f"{tag}.png"
                if link.exists() or link.is_symlink():
                    link.unlink()
                try:
                    link.symlink_to(out_png.resolve())
                except OSError:
                    link.write_bytes(out_png.read_bytes())

                print(f"  rendered {tag}.png")
        finally:
            await browser.close()

    print(f"\n✓ {len(mc_scenes)} Minecraft scene(s) rendered → {DEMO_DIR}")


if __name__ == "__main__":
    asyncio.run(render_all())
