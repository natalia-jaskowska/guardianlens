"""Render every Discord scene in the demo as a realistic HTML screenshot.

Uses ``outputs/demo_html/discord.html`` (the Claude-Design-inspired
template) driven by scene JSON through the URL hash, and Playwright
headless Chromium to capture a 1280×720 PNG per scene.

Writes each PNG to ``outputs/video_feeds/demo_script/<tag>.png`` AND
symlinks it into ``outputs/screenshots/<tag>.png`` so the FastAPI
``/screenshots/`` mount can serve it — that's what the seeded
``screenshots_json`` rows in the DB already point at.

Run from repo root::

    python scripts/render_discord_html_scenes.py
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


TEMPLATE_URL = (PROJECT_ROOT / "outputs" / "demo_html" / "discord.html").resolve().as_uri()
DEMO_DIR = PROJECT_ROOT / "outputs" / "video_feeds" / "demo_script"
SCREENS_DIR = PROJECT_ROOT / "outputs" / "screenshots"


# Per-scene cosmetic overrides. Keyed by scene tag. Fills in server /
# channel / topic / known-user role so the rendered screenshot looks
# like a realistic Discord surface for that specific conversation.
SCENE_EXTRAS: dict[str, dict] = {
    "01_discord_safe_project": {
        "server":  "Lincoln Middle · 7B",
        "channel": "bio-project",
        "topic":   "group project — due friday",
        "date":    "Today",
    },
    "04_discord_safe_birthday": {
        "server":  "Squad Chat",
        "channel": "dm-skye",
        "topic":   "Direct Message",
        "date":    "Today",
    },
    "07_discord_warning_scam": {
        "server":  "Gaming Hub",
        "channel": "general",
        "topic":   "giveaway spam — report the bot",
        "date":    "Today",
        # Sprinkle some realistic reactions so scammers + friends feel alive
        "reactions_by_index": {
            2: [{"emoji": "⚠️", "count": 6}, {"emoji": "🤖", "count": 3}],
            3: [{"emoji": "💯", "count": 4, "mine": True}],
        },
    },
    "08_discord_alert_grooming": {
        "server":  "Shadow League",
        "channel": "dm-coachmarcus",
        "topic":   "Direct Message",
        "date":    "Today",
        "reactions_by_index": {
            0: [{"emoji": "👀", "count": 1}],
        },
    },
    "11_discord_safe_goodnight": {
        "server":  "Squad Chat",
        "channel": "dm-ren",
        "topic":   "Direct Message",
        "date":    "Today",
        "reactions_by_index": {
            3: [{"emoji": "💙", "count": 1, "mine": True}],
        },
    },
}


def _fmt_clock(dt: datetime) -> str:
    """Format as '3:42 PM' / '12:05 PM' (no leading zero on hour)."""
    return dt.strftime("%-I:%M %p")


def build_scene_json(scene: dict) -> dict:
    """Convert a seed-DB scene into the hash-JSON shape our template expects."""
    tag = scene["tag"]
    extras = SCENE_EXTRAS.get(tag, {})

    # Pick the child's handle shown on the user panel. If none of the
    # scene's messages use a literal 'child', default to 'emma'.
    child = "emma"
    # Derive realistic per-message timestamps. Spread them across the
    # scene's duration so repeated senders don't get the same HH:MM.
    last_seen = datetime.now() - timedelta(minutes=int(scene["minutes_ago"]))
    first_seen = last_seen - timedelta(minutes=int(scene["duration_min"]))
    n = max(1, len(scene["messages"]))
    step = (last_seen - first_seen) / n

    reactions_map = extras.get("reactions_by_index", {})

    messages = []
    for i, (sender, text) in enumerate(scene["messages"]):
        # 'child' sender in the seed data is the kid's own message — render
        # that as the child handle so the screenshot matches the user panel.
        display_sender = child if sender == "child" else sender
        stamp_dt = first_seen + step * (i + 1)
        entry = {
            "sender": display_sender,
            "text":   text,
            "time":   f"Today at {_fmt_clock(stamp_dt)}",
        }
        if i in reactions_map:
            entry["reactions"] = reactions_map[i]
        messages.append(entry)

    out = {
        "server":  extras.get("server",  "Server"),
        "channel": extras.get("channel", "general"),
        "topic":   extras.get("topic",   ""),
        "date":    extras.get("date",    last_seen.strftime("%A, %B %-d, %Y")),
        "child":   child,
        "status":  "📱 online",
        "messages": messages,
    }
    return out


async def render_all() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    SCREENS_DIR.mkdir(parents=True, exist_ok=True)

    discord_scenes = [s for s in SCENES if s["platform"] == "Discord"]
    print(f"Rendering {len(discord_scenes)} Discord scene(s)…")

    from playwright.async_api import async_playwright  # lazy import for error clarity

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for i, scene in enumerate(discord_scenes):
                tag = scene["tag"]
                scene_json = build_scene_json(scene)
                # Cache-bust param so page.goto actually reloads instead of
                # just updating the hash — otherwise scene N-1's DOM leaks
                # into scene N's screenshot.
                url = (
                    f"{TEMPLATE_URL}?v={i}"
                    f"#{quote(json.dumps(scene_json))}"
                )

                # Fresh page per scene — cheapest way to guarantee no leaked
                # state between screenshots.
                page = await browser.new_page(
                    viewport={"width": 1280, "height": 720},
                    device_scale_factor=2,
                )
                try:
                    await page.goto(url, wait_until="networkidle")
                    # Give web fonts + emoji sheet a beat to settle.
                    await page.wait_for_timeout(400)

                    out_png = DEMO_DIR / f"{tag}.png"
                    await page.screenshot(
                        path=str(out_png),
                        clip={"x": 0, "y": 0, "width": 1280, "height": 720},
                    )
                finally:
                    await page.close()

                # Symlink into outputs/screenshots so /screenshots/<basename>
                # returns the file at dashboard-serve time.
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

    # For completeness, also symlink any OTHER non-Discord Pillow-rendered
    # PNGs in demo_script/ into screenshots/, so the rest of the dashboard
    # can show its existing screenshots too.
    linked = 0
    for png in DEMO_DIR.glob("*.png"):
        link = SCREENS_DIR / png.name
        if link.exists() or link.is_symlink():
            continue
        try:
            link.symlink_to(png.resolve())
            linked += 1
        except OSError:
            link.write_bytes(png.read_bytes())
            linked += 1
    if linked:
        print(f"  also linked {linked} existing non-Discord PNG(s) into screenshots/")

    print(f"\n✓ {len(discord_scenes)} Discord scene(s) rendered → {DEMO_DIR}")
    print(f"✓ screenshots/ mount now has fresh PNGs for seeded conversations")


if __name__ == "__main__":
    asyncio.run(render_all())
