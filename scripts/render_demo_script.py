"""Render the 11-scene demo script as PNG screenshots.

Drives the existing ``guardlens.demo`` renderers by monkey-patching
``_SCENARIO_LINES`` per scene, so each scene gets its own custom
dialogue. The 11 scenarios match the demo flow documented in chat —
mostly-safe activity with two real alerts (grooming + bullying) and
two cautions (scam bot + creepy stranger comment).

Run from the repo root::

    python scripts/render_demo_script.py

Output goes to ``outputs/video_feeds/demo_script/`` — one PNG per scene,
numbered so the watch-folder loop processes them in script order when
you feed the folder to ``run.py --watch-folder``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without install.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from guardlens import demo


OUT_DIR = PROJECT_ROOT / "outputs" / "video_feeds" / "demo_script"


# Each scene = (filename_tag, platform, scenario_slot, [(sender, text), ...]).
#
# ``scenario_slot`` picks which of the render's built-in chrome variations
# to use. We use:
#   - "safe" slot for any truly-safe scene (cosmetic bubble/background is calm)
#   - "grooming" slot for grooming scenes (renderer accents age/DM bait colors)
#   - "bullying" slot for bullying (red tint for targeted messages)
#
# The pipeline reads the text only, so the slot choice is cosmetic.
SCENES: list[tuple[str, demo.Platform, demo.Scenario, list[tuple[str, str]]]] = [
    # ---- 1 · Discord SAFE — school project
    (
        "01_discord_safe_project",
        "discord",
        "safe",
        [
            ("mia_w",    "hey are we still doing cells or did you want to do plants?"),
            ("elan.nk",  "cells for sure, easier to draw"),
            ("ava_l",    "same, i made a doc"),
            ("mia_w",    "omg legend"),
            ("elan.nk",  "send link pls"),
            ("ava_l",    "[doc link]"),
            ("mia_w",    "ok meeting wednesday 4pm after practice?"),
            ("elan.nk",  "cool ill bring snacks"),
        ],
    ),
    # ---- 2 · Minecraft SAFE — building together
    (
        "02_minecraft_safe_build",
        "minecraft",
        "safe",
        [
            ("cobbly_fern",  "ok the castle needs another tower"),
            ("bluejaypath",  "im on stone duty"),
            ("ava_l",        "ill dig a moat"),
            ("cobbly_fern",  "creeper behind you!!"),
            ("ava_l",        "got him lol"),
            ("bluejaypath",  "gg team"),
        ],
    ),
    # ---- 3 · TikTok SAFE — friends comment on your video
    (
        "03_tiktok_safe_comments",
        "tiktok",
        "safe",
        [
            ("zoetbh",        "the transition at 0:12 icon"),
            ("malik.writes",  "teach me that step"),
            ("auntie_t",      "so proud! send me the song name"),
            ("ava_l",         "silk runner - remix, ill text u"),
        ],
    ),
    # ---- 4 · Discord SAFE — birthday surprise DM
    (
        "04_discord_safe_birthday",
        "discord",
        "safe",
        [
            ("skye.parc",  "ok so the plan: we distract her at lunch"),
            ("ava_l",      "and hide the cake in the art room?"),
            ("skye.parc",  "YES"),
            ("ava_l",      "ms reeves already said ok"),
            ("skye.parc",  "ur the best omg"),
        ],
    ),
    # ---- 5 · Minecraft CAUTION — mutual teasing (should NOT be alert)
    (
        "05_minecraft_caution_teasing",
        "minecraft",
        "safe",
        [
            ("slatepounce",  "stop stealing my iron noob"),
            ("ava_l",        "its a shared chest lmaoo"),
            ("slatepounce",  "im coming for you"),
            ("ava_l",        "bring it"),
            ("slatepounce",  "ok truce wanna go mining together"),
            ("ava_l",        "fine"),
        ],
    ),
    # ---- 6 · TikTok WARNING — creepy stranger comment
    (
        "06_tiktok_warning_stranger",
        "tiktok",
        "grooming",
        [
            ("x.vibes.z",  "ur really pretty how old r u"),
            ("x.vibes.z",  "dm me ill make u famous"),
        ],
    ),
    # ---- 7 · Discord WARNING — scam bot
    (
        "07_discord_warning_scam",
        "discord",
        "safe",
        [
            ("FreeNitroDaily",  "CONGRATS! You've been selected for FREE DISCORD NITRO"),
            ("FreeNitroDaily",  "Claim now before it expires - only 19 spots left"),
            ("FreeNitroDaily",  "discordnitro-claim.link/verify"),
            ("kade.x7",         "bruh this is so fake"),
            ("ava_l",           "yeah every server has this bot"),
            ("kade.x7",         "report and move"),
        ],
    ),
    # ---- 8 · Discord ALERT — grooming DM
    (
        "08_discord_alert_grooming",
        "discord",
        "grooming",
        [
            ("CoachMarcus",  "gg out there, you're actually really good"),
            ("CoachMarcus",  "how long have you been playing?"),
            ("ava_l",        "like a year ig"),
            ("CoachMarcus",  "no way you play that clean after a year lol. age?"),
            ("ava_l",        "13 almost 14"),
            ("CoachMarcus",  "cool im 16. dw im not a creep haha"),
            ("CoachMarcus",  "i run a private coaching server, invite only. you in?"),
            ("CoachMarcus",  "its on telegram tho discord is mid for voice"),
            ("CoachMarcus",  "dont tell anyone tho i only pick a few"),
        ],
    ),
    # ---- 9 · TikTok ALERT — targeted peer bullying
    (
        "09_tiktok_alert_bullying",
        "tiktok",
        "bullying",
        [
            ("jilliaaan",  "why do you always do the same dance lol"),
            ("tara.k_",    "literally cringe"),
            ("rhiiannn",   "nobody asked for this"),
            ("mo.lyn",     "imagine thinking ppl like u"),
            ("jilliaaan",  "we made a gc laughing at u btw"),
            ("tara.k_",    "go private loser"),
        ],
    ),
    # ---- 9b · Minecraft ALERT — targeted pile-on bullying
    (
        "09b_minecraft_alert_bullying",
        "minecraft",
        "bullying",
        [
            ("knifecore_",  "lol u built that?? embarrassing"),
            ("_shardrat_",  "literal 5yo build"),
            ("mooncrypt",   "get off MY server"),
            ("knifecore_",  "yeah pack it up ava"),
            ("_shardrat_",  "we just destroyed your base lmao"),
            ("ava_l",       "why are u guys like this"),
            ("knifecore_",  "bc nobody wants u here"),
            ("mooncrypt",   "try a baby server next time"),
        ],
    ),
    # ---- 10 · Minecraft SAFE — trade (cooldown scene after alerts)
    (
        "10_minecraft_safe_trade",
        "minecraft",
        "safe",
        [
            ("emerald.gus",  "2 diamonds for your enchanted book?"),
            ("ava_l",        "make it 3 its mending"),
            ("emerald.gus",  "fair deal"),
            ("ava_l",        "nice doing business"),
        ],
    ),
    # ---- 11 · Discord SAFE — goodnight to best friend
    (
        "11_discord_safe_goodnight",
        "discord",
        "safe",
        [
            ("ren_ot",  "night, see u tmrw"),
            ("ava_l",   "night ren"),
            ("ren_ot",  "dw about the tiktok stuff, theyre miserable"),
            ("ava_l",   "ty"),
        ],
    ),
]


def render_all() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Wipe any existing PNGs so removed scenes don't linger.
    for stale in OUT_DIR.glob("*.png"):
        stale.unlink()

    for tag, platform, slot, lines in SCENES:
        # Patch the scenario slot for this platform, then render. The demo
        # module caches nothing between calls — each render_demo_chat reads
        # _SCENARIO_LINES fresh, so overwriting the slot works.
        demo._SCENARIO_LINES[platform][slot] = lines
        out_path = OUT_DIR / f"{tag}.png"
        demo.render_demo_chat(out_path, slot, platform=platform)
        print(f"  rendered {out_path.name}")

    print(f"\n{len(SCENES)} scenes written to {OUT_DIR}")


if __name__ == "__main__":
    render_all()
