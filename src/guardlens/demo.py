"""Synthetic 'fake game chat' screenshot generator for headless demos.

When the dev server has no display (SSH session, no X11), `mss` cannot
capture real screenshots. This module renders Pillow PNGs of staged chat
scenarios so the rest of the pipeline (analyzer, database, dashboard) can
still be exercised end-to-end.

Three scenarios:

- ``safe``     : ordinary multiplayer game banter
- ``grooming`` : staged grooming pattern (age + DM proposal + secrecy)
- ``bullying`` : repeated targeted harassment

Used by:

- :func:`guardlens.monitor.capture_loop` when ``MonitorConfig.demo_mode`` is True
- :mod:`scripts.smoke_test` for one-shot pipeline verification
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

Scenario = Literal["safe", "grooming", "bullying"]

DEMO_SCENARIOS: tuple[Scenario, ...] = ("safe", "grooming", "safe", "bullying")
"""Default rotation order used by the demo monitor loop."""


_SCENARIO_LINES: dict[Scenario, list[tuple[str, str]]] = {
    "safe": [
        ("<DiamondMiner42>", "anyone got iron to trade?"),
        ("<BlazeKnight>", "i have 12 iron, want diamonds for them"),
        ("<DiamondMiner42>", "yeah sure meet at spawn"),
        ("<PixelBuilder>", "nice base btw, the roof looks cool"),
        ("<BlazeKnight>", "thanks took 3 days lol"),
        ("<DiamondMiner42>", "anyone want to raid the end portal tomorrow?"),
        ("<PixelBuilder>", "yes! im in"),
    ],
    "grooming": [
        ("<KidGamer09>", "hi! anyone want to play together?"),
        ("<CoolGuy99>", "sure :) how old are you?"),
        ("<KidGamer09>", "im 12"),
        ("<CoolGuy99>", "youre very mature for 12 :)"),
        ("<CoolGuy99>", "wanna add me on discord? i can give you free skins"),
        ("<CoolGuy99>", "dont tell your parents about it ok? its our secret"),
        ("<KidGamer09>", "umm ok i guess"),
    ],
    "bullying": [
        ("<KidGamer09>", "hey can i join your team?"),
        ("<MeanKid01>", "lol no go away noob"),
        ("<MeanKid01>", "nobody wants you here"),
        ("<MeanKid02>", "yeah youre trash at this game"),
        ("<MeanKid01>", "delete the game already"),
        ("<KidGamer09>", "stop please"),
        ("<MeanKid02>", "lol cry about it"),
    ],
}


def render_demo_chat(path: Path, scenario: Scenario) -> Path:
    """Render a fake Minecraft-style chat overlay for ``scenario`` as a PNG.

    Parameters
    ----------
    path:
        Where to write the PNG. Parent directories are created if missing.
    scenario:
        Which staged conversation to render. See :data:`DEMO_SCENARIOS`.

    Returns
    -------
    Path
        Same as ``path``.
    """
    width, height = 1024, 640
    image = Image.new("RGB", (width, height), color=(20, 20, 20))
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSansMono.ttf", 22)
        title_font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
        title_font = font

    draw.text((20, 20), "Minecraft - Survival Multiplayer", fill=(255, 255, 255), font=title_font)
    draw.rectangle((20, 80, width - 20, height - 20), fill=(0, 0, 0), outline=(80, 80, 80))

    path.parent.mkdir(parents=True, exist_ok=True)
    y = 100
    for user, msg in _SCENARIO_LINES[scenario]:
        draw.text((40, y), user, fill=(120, 200, 255), font=font)
        draw.text((300, y), msg, fill=(230, 230, 230), font=font)
        y += 38

    image.save(path)
    return path
