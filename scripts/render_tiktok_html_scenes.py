"""Render every TikTok scene as a portrait phone DM screenshot.

Uses ``outputs/demo_html/tiktok_dm.html`` (the iPhone-style TikTok DM
template — 390×844 portrait, no desktop frame) driven by scene JSON
through the URL hash. Playwright headless Chromium captures each
scene at 3× device scale for crisp output.

Writes PNGs to ``outputs/video_feeds/demo_script/<tag>.png`` and
symlinks them into ``outputs/screenshots/<tag>.png`` so the
FastAPI ``/screenshots/`` mount can serve them.

Run from repo root::

    python scripts/render_tiktok_html_scenes.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_demo_db import SCENES  # noqa: E402


TEMPLATE_URL = (PROJECT_ROOT / "outputs" / "demo_html" / "tiktok_dm.html").resolve().as_uri()
DEMO_DIR = PROJECT_ROOT / "outputs" / "video_feeds" / "demo_script"
SCREENS_DIR = PROJECT_ROOT / "outputs" / "screenshots"


# Per-scene cosmetic extras — keyed by scene tag.
# * `other_display` + `other_user`: only used for 1-on-1 DMs.
# * `title`:                        used for group DMs.
# * `verified`, `last_active`:      optional chrome.
SCENE_EXTRAS: dict[str, dict] = {
    # 3 friends/family comment under Emma's video — feels more like a
    # friendly group DM here (since the template is DM-only).
    "03_tiktok_safe_comments": {
        "title":       "💃 dance squad",
        "last_active": "Active now",
    },
    # Stranger creepily comments. In DM form this reads as an opening
    # cold-DM — exactly the real grooming vector on TikTok.
    "06_tiktok_warning_stranger": {
        "other_user":    "xvibesz",
        "other_display": "x.vibes.z",
        "verified":      False,
        "last_active":   "Active 22m ago",
    },
    # 4 peers pile on. Group DM framing works because that's the actual
    # TikTok experience — a target kid often gets added to a group chat
    # that forms specifically to harass them.
    "09_tiktok_alert_bullying": {
        "title":       "group chat",
        "last_active": "Active now",
    },
}


def _fmt_clock(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p")


def build_scene_json(scene: dict) -> dict:
    tag = scene["tag"]
    extras = SCENE_EXTRAS.get(tag, {})

    last_seen = datetime.now() - timedelta(minutes=int(scene["minutes_ago"]))
    first_seen = last_seen - timedelta(minutes=int(scene["duration_min"]))
    n = max(1, len(scene["messages"]))
    step = (last_seen - first_seen) / n

    child = "emma"
    messages = []
    # Only emit a `time` divider when the clock VISIBLY changes from
    # the previous message (otherwise the phone view gets one divider
    # per bubble, which is ugly).
    last_clock_label = None
    for i, (sender, text) in enumerate(scene["messages"]):
        is_child = (sender == "child")
        from_field = "me" if is_child else sender
        stamp_dt = first_seen + step * (i + 1)
        clock_label = f"Today {_fmt_clock(stamp_dt)}"

        entry = {
            "from": from_field,
            "text": text,
        }
        if clock_label != last_clock_label:
            entry["time"] = clock_label
            last_clock_label = clock_label
        messages.append(entry)

    # Sprinkle realistic reactions on specific messages.
    if tag == "06_tiktok_warning_stranger" and len(messages) >= 2:
        messages[1]["reactions"] = [{"emoji": "👀", "count": 1}]
    if tag == "09_tiktok_alert_bullying" and len(messages) >= 5:
        # "we made a gc laughing at u btw" — cruel laugh pile-on reactions
        messages[4]["reactions"] = [
            {"emoji": "💀", "count": 4},
            {"emoji": "😂", "count": 2},
        ]
    if tag == "03_tiktok_safe_comments" and len(messages) >= 1:
        messages[0]["reactions"] = [{"emoji": "🔥", "count": 2, "mine": True}]

    scene_json = {
        "status_time": last_seen.strftime("%-I:%M"),
        "child": child,
        "messages": messages,
    }
    scene_json.update(extras)
    return scene_json


async def render_all() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    SCREENS_DIR.mkdir(parents=True, exist_ok=True)

    tiktok_scenes = [s for s in SCENES if s["platform"] == "TikTok"]
    print(f"Rendering {len(tiktok_scenes)} TikTok scene(s)…")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for i, scene in enumerate(tiktok_scenes):
                tag = scene["tag"]
                scene_json = build_scene_json(scene)
                # Cache-bust so each navigation actually reloads.
                url = (
                    f"{TEMPLATE_URL}?v={i}"
                    f"#{quote(json.dumps(scene_json))}"
                )
                page = await browser.new_page(
                    viewport={"width": 390, "height": 844},
                    device_scale_factor=3,
                )
                try:
                    await page.goto(url, wait_until="networkidle")
                    await page.wait_for_timeout(500)  # fonts + emoji
                    out_png = DEMO_DIR / f"{tag}.png"
                    await page.screenshot(
                        path=str(out_png),
                        clip={"x": 0, "y": 0, "width": 390, "height": 844},
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

    print(f"\n✓ {len(tiktok_scenes)} TikTok scene(s) rendered → {DEMO_DIR}")


if __name__ == "__main__":
    asyncio.run(render_all())
