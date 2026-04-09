"""Synthetic 'fake game/social chat' screenshot generator for headless demos.

When the dev server has no display (SSH session, no X11), ``mss`` cannot
capture real screenshots. This module renders Pillow PNGs of staged chat
scenarios so the rest of the pipeline (analyzer, database, dashboard)
can be exercised end-to-end.

Three platforms, three scenarios each:

- ``minecraft`` — Minecraft multiplayer chat overlay
- ``discord``   — Discord channel view (sidebar + chat with avatars)
- ``instagram`` — Instagram DM thread (header + chat bubbles)

- ``safe``     — ordinary banter
- ``grooming`` — staged grooming pattern
- ``bullying`` — repeated targeted harassment

Used by:

- :func:`guardlens.monitor.capture_loop` when ``MonitorConfig.demo_mode`` is True
- :mod:`scripts.smoke_test` for one-shot pipeline verification
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

Platform = Literal["minecraft", "discord", "instagram", "tiktok"]
Scenario = Literal["safe", "grooming", "bullying"]

# Default rotation used by the demo monitor loop. Mixes platforms and
# scenarios so the dashboard timeline shows real variety.
DEMO_SCENARIO_SEQUENCE: tuple[tuple[Platform, Scenario], ...] = (
    ("minecraft", "safe"),
    ("discord", "grooming"),
    ("tiktok", "safe"),
    ("instagram", "grooming"),
    ("discord", "bullying"),
    ("instagram", "safe"),
    ("tiktok", "bullying"),
    ("minecraft", "grooming"),
)
"""Cycled by :func:`guardlens.monitor._demo_capture_loop`."""

# Backwards-compatible single-platform scenario tuple (still used by smoke_test).
DEMO_SCENARIOS: tuple[Scenario, ...] = ("safe", "grooming", "safe", "bullying")

# Maps a demo scenario's chat-line index to the indicator the dashboard
# should highlight on it. Used by the "fake browser" capture view to
# outline dangerous bubbles in red. Indices match _SCENARIO_LINES order.
DEMO_FLAGS: dict[tuple[str, str], dict[int, str]] = {
    ("minecraft", "grooming"): {
        1: "age inquiry",
        4: "gift offering",
        5: "isolation",
    },
    ("minecraft", "bullying"): {
        1: "exclusion",
        2: "exclusion",
        3: "personal attack",
        4: "self-harm bait",
        6: "personal attack",
    },
    ("discord", "grooming"): {
        2: "false age claim",
        3: "age inquiry",
        5: "grooming flattery",
        6: "isolation",
        7: "secrecy",
    },
    ("discord", "bullying"): {
        1: "exclusion",
        2: "exclusion",
        3: "exclusion",
        4: "personal attack",
        6: "exclusion",
    },
    ("instagram", "grooming"): {
        1: "personal info request",
        3: "age inquiry",
        5: "grooming flattery",
        6: "false age claim",
        7: "image request + secrecy",
    },
    ("instagram", "bullying"): {
        1: "personal attack",
        2: "humiliation",
        4: "exclusion",
        5: "exclusion",
    },
    ("tiktok", "grooming"): {
        1: "age inquiry",
        3: "false age claim",
        4: "isolation",
        5: "secrecy",
    },
    ("tiktok", "bullying"): {
        1: "personal attack",
        2: "humiliation",
        3: "humiliation",
        5: "self-harm bait",
    },
}


def build_chat_messages(platform: str, scenario: str) -> list[dict[str, str | None]]:
    """Build the structured chat messages payload for a demo scenario.

    Returns a list of ``{sender, text, flag}`` dicts ready to be passed
    to :class:`guardlens.schema.ChatMessage`. Each line carries its
    pre-computed flag from :data:`DEMO_FLAGS` (or ``None`` if safe).
    """
    platform_lines = _SCENARIO_LINES.get(platform)
    if platform_lines is None:
        return []
    lines = platform_lines.get(scenario)
    if lines is None:
        return []
    flags = DEMO_FLAGS.get((platform, scenario), {})
    out: list[dict[str, str | None]] = []
    for idx, (sender, text) in enumerate(lines):
        out.append({"sender": sender, "text": text, "flag": flags.get(idx)})
    return out


# ----------------------------------------------------------------------- chat lines

_SCENARIO_LINES: dict[Platform, dict[Scenario, list[tuple[str, str]]]] = {
    "minecraft": {
        "safe": [
            ("DiamondMiner42", "anyone got iron to trade?"),
            ("BlazeKnight", "i have 12 iron, want diamonds for them"),
            ("DiamondMiner42", "yeah sure meet at spawn"),
            ("PixelBuilder", "nice base btw, the roof looks cool"),
            ("BlazeKnight", "thanks took 3 days lol"),
            ("DiamondMiner42", "anyone want to raid the end portal tomorrow?"),
            ("PixelBuilder", "yes! im in"),
        ],
        "grooming": [
            ("KidGamer09", "hi! anyone want to play together?"),
            ("CoolGuy99", "sure :) how old are you?"),
            ("KidGamer09", "im 12"),
            ("CoolGuy99", "youre very mature for 12 :)"),
            ("CoolGuy99", "wanna add me on discord? i can give you free skins"),
            ("CoolGuy99", "dont tell your parents about it ok? its our secret"),
            ("KidGamer09", "umm ok i guess"),
        ],
        "bullying": [
            ("KidGamer09", "hey can i join your team?"),
            ("MeanKid01", "lol no go away noob"),
            ("MeanKid01", "nobody wants you here"),
            ("MeanKid02", "yeah youre trash at this game"),
            ("MeanKid01", "delete the game already"),
            ("KidGamer09", "stop please"),
            ("MeanKid02", "lol cry about it"),
        ],
    },
    "discord": {
        "safe": [
            ("PixelBuilder", "yo, did anyone finish the math hw?"),
            ("Em_22", "ya it was easy lol"),
            ("PixelBuilder", "send help on q5 i cant figure it out"),
            ("Em_22", "ok one sec ill DM u"),
            ("Sammy7", "anyone wanna play among us tonight?"),
            ("PixelBuilder", "im down after homework"),
            ("Em_22", "same"),
        ],
        "grooming": [
            ("KidGamer09", "hey, you in a guild here?"),
            ("ShadowPro", "yeah but its private. you seem cool tho"),
            ("ShadowPro", "no way im 14 too lol what school u go to"),
            ("ShadowPro", "how old are you btw?"),
            ("KidGamer09", "13"),
            ("ShadowPro", "wow you write super mature for your age"),
            ("ShadowPro", "wanna move to snap? i can send you robux there"),
            ("ShadowPro", "just dont mention it to ur mom ok"),
        ],
        "bullying": [
            ("KidGamer09", "hi guys"),
            ("Maxxx_", "oh great its her"),
            ("Lyla.x", "nobody asked you to be here"),
            ("Maxxx_", "everyone literally muted you why are u back"),
            ("Lyla.x", "ur so cringe omg"),
            ("KidGamer09", "why are you doing this"),
            ("Maxxx_", "leave the server already"),
        ],
    },
    "instagram": {
        "safe": [
            ("them", "girlll did u see the new taylor video"),
            ("me", "YESSSS the choreo is insane"),
            ("them", "im learning it for tiktok lol"),
            ("me", "send me when ur done!!"),
            ("them", "k bring snacks tmr at lunch"),
            ("me", "got u"),
        ],
        "grooming": [
            ("them", "hey saw your dance vid, you're so talented"),
            ("them", "what school do you go to?"),
            ("me", "north middle"),
            ("them", "wow i used to live near there. how old are you"),
            ("me", "12"),
            ("them", "youre really pretty for your age"),
            ("them", "im 15 btw not creepy haha"),
            ("them", "send me a photo of you in that outfit again? our secret"),
        ],
        "bullying": [
            ("them", "saw ur post lol"),
            ("them", "you really thought that was cute??"),
            ("them", "everyone in class was laughing at it"),
            ("me", "stop"),
            ("them", "no one likes you just delete it"),
            ("them", "and ur acc while ur at it"),
        ],
    },
    "tiktok": {
        "safe": [
            ("@danceQueen", "guys this trend is so easy"),
            ("@livvyk", "OMG i need to learn this"),
            ("@bestieben", "tutorial pls"),
            ("@danceQueen", "ok ill post one tonight"),
            ("@livvyk", "yessss queen"),
        ],
        "grooming": [
            ("@k1dgamer09", "thx for the like"),
            ("@xx_proud", "you're so cute in that vid. how old r u"),
            ("@k1dgamer09", "12"),
            ("@xx_proud", "wow same haha (16 actually)"),
            ("@xx_proud", "wanna chat on snap instead? more private"),
            ("@xx_proud", "dont tell ur parents about us tho ok"),
        ],
        "bullying": [
            ("@k1dgamer09", "i tried the trend!!"),
            ("@hatemate", "lol you look so dumb"),
            ("@dpr0p", "delete this please for everyone's sanity"),
            ("@hatemate", "literally everyone in school is laughing"),
            ("@k1dgamer09", "why are you so mean"),
            ("@dpr0p", "kys lol jk... unless"),
        ],
    },
}


# ----------------------------------------------------------------------- font cache

_FONT_DIR = "/usr/share/fonts/TTF"


@lru_cache(maxsize=16)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Cached font loader. Falls back to Pillow's default if a TTF is missing."""
    try:
        return ImageFont.truetype(f"{_FONT_DIR}/{name}", size)
    except OSError:
        return ImageFont.load_default()


# ----------------------------------------------------------------------- dispatch


def render_demo_chat(
    path: Path,
    scenario: Scenario,
    *,
    platform: Platform = "minecraft",
) -> Path:
    """Render a fake chat screenshot to ``path`` and return the path.

    Parameters
    ----------
    path:
        Where to write the PNG. Parent directories are created if missing.
    scenario:
        Which staged conversation to render.
    platform:
        Which platform's visual style to use. Defaults to ``minecraft`` for
        backwards compatibility with earlier callers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform == "discord":
        image = _render_discord(scenario)
    elif platform == "instagram":
        image = _render_instagram(scenario)
    elif platform == "tiktok":
        image = _render_tiktok(scenario)
    else:
        image = _render_minecraft(scenario)
    image.save(path)
    return path


# ----------------------------------------------------------------------- minecraft


def _render_minecraft(scenario: Scenario) -> Image.Image:
    width, height = 1024, 640
    image = Image.new("RGB", (width, height), color=(20, 20, 20))
    draw = ImageDraw.Draw(image)

    title_font = _font("DejaVuSans-Bold.ttf", 28)
    chat_font = _font("DejaVuSansMono.ttf", 22)

    draw.text((20, 20), "Minecraft - Survival Multiplayer", fill=(255, 255, 255), font=title_font)
    draw.rectangle((20, 80, width - 20, height - 20), fill=(0, 0, 0), outline=(80, 80, 80))

    y = 100
    for user, msg in _SCENARIO_LINES["minecraft"][scenario]:
        draw.text((40, y), f"<{user}>", fill=(120, 200, 255), font=chat_font)
        draw.text((300, y), msg, fill=(230, 230, 230), font=chat_font)
        y += 38
    return image


# ----------------------------------------------------------------------- discord

# Discord-style palette
_DC_BG = (54, 57, 63)
_DC_SIDEBAR = (47, 49, 54)
_DC_CHANNEL_BG = (32, 34, 37)
_DC_HEADER = (54, 57, 63)
_DC_TEXT = (220, 221, 222)
_DC_USERNAME = (255, 255, 255)
_DC_TIMESTAMP = (114, 118, 125)
_DC_MENTION = (88, 101, 242)
_DC_DIVIDER = (32, 34, 37)

# Per-username role colors so different speakers stand out (cycled)
_DC_ROLE_COLORS = [
    (88, 101, 242),   # blurple
    (87, 242, 135),   # green
    (235, 69, 158),   # pink
    (254, 231, 92),   # yellow
    (235, 69, 69),    # red
    (153, 170, 181),  # default grey
]


def _render_discord(scenario: Scenario) -> Image.Image:
    width, height = 1280, 720
    image = Image.new("RGB", (width, height), color=_DC_BG)
    draw = ImageDraw.Draw(image)

    # ---- left server bar ----
    server_bar_w = 72
    draw.rectangle((0, 0, server_bar_w, height), fill=_DC_CHANNEL_BG)
    server_colors = [(88, 101, 242), (235, 69, 158), (87, 242, 135), (254, 231, 92)]
    for i, color in enumerate(server_colors):
        cy = 24 + i * 64
        draw.rounded_rectangle(
            (16, cy, 56, cy + 40),
            radius=20 if i > 0 else 12,
            fill=color,
        )

    # ---- channel sidebar ----
    sidebar_x = server_bar_w
    sidebar_w = 240
    draw.rectangle((sidebar_x, 0, sidebar_x + sidebar_w, height), fill=_DC_SIDEBAR)

    # Server name header
    server_name_font = _font("DejaVuSans-Bold.ttf", 16)
    draw.text(
        (sidebar_x + 16, 18),
        "Game Chat Server",
        fill=_DC_USERNAME,
        font=server_name_font,
    )
    draw.line(
        (sidebar_x + 12, 56, sidebar_x + sidebar_w - 12, 56),
        fill=_DC_CHANNEL_BG,
        width=1,
    )

    # Channel list
    section_font = _font("DejaVuSans-Bold.ttf", 11)
    channel_font = _font("DejaVuSans.ttf", 14)
    draw.text(
        (sidebar_x + 16, 76),
        "TEXT CHANNELS",
        fill=_DC_TIMESTAMP,
        font=section_font,
    )
    channels = [
        ("# announcements", False),
        ("# general-chat", True),  # active
        ("# memes", False),
        ("# game-night", False),
        ("# voice-chat", False),
    ]
    cy = 102
    for name, active in channels:
        if active:
            draw.rounded_rectangle(
                (sidebar_x + 8, cy - 2, sidebar_x + sidebar_w - 8, cy + 22),
                radius=4,
                fill=(64, 68, 75),
            )
            color = _DC_USERNAME
        else:
            color = _DC_TIMESTAMP
        draw.text((sidebar_x + 16, cy), name, fill=color, font=channel_font)
        cy += 28

    # ---- main channel area ----
    main_x = sidebar_x + sidebar_w
    main_w = width - main_x
    draw.rectangle((main_x, 0, width, height), fill=_DC_BG)

    # Channel header bar
    header_h = 48
    draw.rectangle((main_x, 0, width, header_h), fill=_DC_BG)
    draw.line((main_x, header_h, width, header_h), fill=_DC_DIVIDER, width=1)
    header_font = _font("DejaVuSans-Bold.ttf", 16)
    draw.text((main_x + 20, 14), "#", fill=_DC_TIMESTAMP, font=header_font)
    draw.text((main_x + 36, 14), "general-chat", fill=_DC_USERNAME, font=header_font)

    # Messages
    username_font = _font("DejaVuSans-Bold.ttf", 16)
    timestamp_font = _font("DejaVuSans.ttf", 11)
    message_font = _font("DejaVuSans.ttf", 15)

    lines = _SCENARIO_LINES["discord"][scenario]
    y = header_h + 28
    avatar_x = main_x + 20

    # Group consecutive messages by the same user (Discord-style stacking)
    last_user: str | None = None
    role_color_idx: dict[str, int] = {}

    for idx, (user, msg) in enumerate(lines):
        if user not in role_color_idx:
            role_color_idx[user] = len(role_color_idx) % len(_DC_ROLE_COLORS)
        username_color = _DC_ROLE_COLORS[role_color_idx[user]]

        if user != last_user:
            # New message group: avatar + username + timestamp
            if idx > 0:
                y += 6  # extra gap between groups
            # Avatar circle (colored with first letter)
            draw.ellipse(
                (avatar_x, y, avatar_x + 40, y + 40),
                fill=username_color,
            )
            initial = user[0].upper()
            initial_font = _font("DejaVuSans-Bold.ttf", 18)
            # Roughly center the letter (no need for textbbox here)
            draw.text(
                (avatar_x + 14, y + 9),
                initial,
                fill=_DC_USERNAME,
                font=initial_font,
            )
            # Username + timestamp
            draw.text(
                (avatar_x + 56, y + 2),
                user,
                fill=username_color,
                font=username_font,
            )
            timestamp = "Today at 14:" + f"{20 + idx:02d}"
            draw.text(
                (avatar_x + 56 + len(user) * 9 + 12, y + 6),
                timestamp,
                fill=_DC_TIMESTAMP,
                font=timestamp_font,
            )
            # First message line under the username
            draw.text(
                (avatar_x + 56, y + 24),
                msg,
                fill=_DC_TEXT,
                font=message_font,
            )
            y += 54
        else:
            # Continuation message — no avatar, just indented text
            draw.text(
                (avatar_x + 56, y - 18),
                msg,
                fill=_DC_TEXT,
                font=message_font,
            )
            y += 26

        last_user = user

    # Message input box at the bottom
    input_y = height - 64
    draw.rounded_rectangle(
        (main_x + 20, input_y, width - 20, input_y + 44),
        radius=8,
        fill=(64, 68, 75),
    )
    draw.text(
        (main_x + 40, input_y + 12),
        "Message #general-chat",
        fill=_DC_TIMESTAMP,
        font=message_font,
    )

    return image


# ----------------------------------------------------------------------- instagram

# Instagram dark-mode palette
_IG_BG = (0, 0, 0)
_IG_HEADER_BG = (0, 0, 0)
_IG_BORDER = (38, 38, 38)
_IG_OTHER_BUBBLE = (38, 38, 38)
_IG_SELF_BUBBLE = (52, 119, 239)  # IG message blue
_IG_TEXT = (255, 255, 255)
_IG_TEXT_DIM = (142, 142, 142)
_IG_LINK = (224, 241, 255)


def _render_instagram(scenario: Scenario) -> Image.Image:
    width, height = 720, 980
    image = Image.new("RGB", (width, height), color=_IG_BG)
    draw = ImageDraw.Draw(image)

    title_font = _font("DejaVuSans-Bold.ttf", 18)
    bubble_font = _font("DejaVuSans.ttf", 16)
    meta_font = _font("DejaVuSans.ttf", 11)

    # ---- top header ----
    header_h = 64
    draw.rectangle((0, 0, width, header_h), fill=_IG_HEADER_BG)
    draw.line((0, header_h, width, header_h), fill=_IG_BORDER, width=1)
    # Back arrow
    draw.text((20, 20), "<", fill=_IG_TEXT, font=title_font)
    # Profile circle
    draw.ellipse((52, 14, 92, 54), fill=(80, 80, 80))
    draw.ellipse((54, 16, 90, 52), fill=(140, 80, 200))
    # Username + status
    draw.text((104, 14), "lily.summer", fill=_IG_TEXT, font=title_font)
    draw.text((104, 38), "Active 3m ago", fill=_IG_TEXT_DIM, font=meta_font)
    # Right-side icons (camera + phone + info)
    icon_font = _font("DejaVuSans-Bold.ttf", 18)
    draw.text((width - 96, 20), "[c]", fill=_IG_TEXT, font=icon_font)
    draw.text((width - 64, 20), "[i]", fill=_IG_TEXT, font=icon_font)

    # ---- date stamp ----
    date_y = header_h + 24
    draw.text(
        (width // 2 - 40, date_y),
        "TUE 14:32",
        fill=_IG_TEXT_DIM,
        font=meta_font,
    )

    # ---- bubbles ----
    lines = _SCENARIO_LINES["instagram"][scenario]
    y = date_y + 32
    max_bubble_w = int(width * 0.66)
    pad_x = 14
    pad_y = 10
    radius = 22

    for sender, msg in lines:
        is_me = sender == "me"

        # Word-wrap the message into a few lines
        wrapped_lines = _wrap_text(msg, bubble_font, max_bubble_w - 2 * pad_x, draw)

        # Compute bubble dims
        line_h = 22
        text_h = line_h * len(wrapped_lines)
        bubble_h = text_h + 2 * pad_y
        text_w = max(
            int(draw.textlength(line, font=bubble_font)) for line in wrapped_lines
        )
        bubble_w = text_w + 2 * pad_x

        if is_me:
            x_right = width - 20
            x_left = x_right - bubble_w
            fill = _IG_SELF_BUBBLE
            text_color = _IG_TEXT
        else:
            x_left = 20
            x_right = x_left + bubble_w
            fill = _IG_OTHER_BUBBLE
            text_color = _IG_TEXT

        draw.rounded_rectangle(
            (x_left, y, x_right, y + bubble_h),
            radius=radius,
            fill=fill,
        )
        for i, line in enumerate(wrapped_lines):
            draw.text(
                (x_left + pad_x, y + pad_y + i * line_h),
                line,
                fill=text_color,
                font=bubble_font,
            )
        y += bubble_h + 12

    # ---- bottom message bar ----
    bar_y = height - 64
    draw.line((0, bar_y, width, bar_y), fill=_IG_BORDER, width=1)
    draw.rounded_rectangle(
        (60, bar_y + 14, width - 80, bar_y + 50),
        radius=18,
        outline=_IG_BORDER,
        width=1,
    )
    draw.text(
        (76, bar_y + 22),
        "Message...",
        fill=_IG_TEXT_DIM,
        font=bubble_font,
    )

    return image


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Cheap word-wrap that respects ``max_width`` (in pixels)."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


# ----------------------------------------------------------------------- tiktok

# TikTok comments overlay over a fake "video" frame.
_TT_BG = (0, 0, 0)
_TT_VIDEO = (24, 24, 24)
_TT_TEXT = (255, 255, 255)
_TT_TEXT_DIM = (160, 160, 160)
_TT_USERNAME = (255, 255, 255)
_TT_PINK = (254, 44, 85)
_TT_CYAN = (37, 244, 238)


def _render_tiktok(scenario: Scenario) -> Image.Image:
    width, height = 720, 980
    image = Image.new("RGB", (width, height), color=_TT_BG)
    draw = ImageDraw.Draw(image)

    # Fake "video" background — vertical dark gradient block
    draw.rectangle((0, 0, width, height), fill=_TT_VIDEO)
    for y in range(0, height, 4):
        shade = 20 + int(20 * (y / height))
        draw.line((0, y, width, y), fill=(shade, shade, shade + 4))

    # Top header — "For You" / "Following"
    title_font = _font("DejaVuSans-Bold.ttf", 18)
    section_font = _font("DejaVuSans.ttf", 15)
    draw.text((width // 2 - 80, 20), "Following", fill=_TT_TEXT_DIM, font=section_font)
    draw.text((width // 2 + 16, 20), "|", fill=_TT_TEXT_DIM, font=section_font)
    draw.text((width // 2 + 32, 20), "For You", fill=_TT_TEXT, font=title_font)
    draw.line((width // 2 + 32, 46, width // 2 + 116, 46), fill=_TT_TEXT, width=2)

    # Right-side action column (heart, comment, share, profile)
    icon_font = _font("DejaVuSans-Bold.ttf", 18)
    actions_x = width - 60
    icons = [
        ("♥", "1.2M"),
        ("c", "8,442"),
        ("s", "2.1K"),
        ("@", "save"),
    ]
    icon_y = 220
    for label, count in icons:
        draw.ellipse(
            (actions_x - 4, icon_y - 4, actions_x + 44, icon_y + 44),
            outline=(255, 255, 255, 100),
            width=1,
        )
        draw.text((actions_x + 12, icon_y + 8), label, fill=_TT_TEXT, font=icon_font)
        draw.text((actions_x - 4, icon_y + 48), count, fill=_TT_TEXT, font=section_font)
        icon_y += 92

    # Bottom-left — creator handle + caption + sound bar
    creator_font = _font("DejaVuSans-Bold.ttf", 18)
    caption_font = _font("DejaVuSans.ttf", 14)
    creator = "@danceQueen"
    if scenario == "grooming":
        creator = "@xx_proud"
    elif scenario == "bullying":
        creator = "@hatemate"

    draw.text((24, height - 240), creator, fill=_TT_TEXT, font=creator_font)
    captions = {
        "safe": "trying the new trend! #fyp #dance",
        "grooming": "lol you guys r the best fr #fyp",
        "bullying": "comment of the week LMAO #fyp",
    }
    draw.text(
        (24, height - 212),
        captions[scenario],
        fill=_TT_TEXT,
        font=caption_font,
    )
    draw.text(
        (24, height - 188),
        "♪ original sound - " + creator,
        fill=_TT_TEXT_DIM,
        font=caption_font,
    )

    # Comments panel slid up from bottom (like the comments drawer)
    panel_top = height - 156
    draw.rectangle((0, panel_top, width, height), fill=(0, 0, 0))
    draw.line((0, panel_top, width, panel_top), fill=(40, 40, 40), width=1)
    draw.text(
        (24, panel_top + 12),
        "Comments",
        fill=_TT_TEXT,
        font=creator_font,
    )

    comment_font = _font("DejaVuSans.ttf", 13)
    user_font = _font("DejaVuSans-Bold.ttf", 13)

    lines = _SCENARIO_LINES["tiktok"][scenario]
    y = panel_top + 44
    for user, msg in lines[-3:]:  # only the latest 3 fit in the drawer
        # Avatar circle
        draw.ellipse((24, y, 56, y + 32), fill=_TT_PINK)
        initial = user.lstrip("@")[0].upper()
        initial_font = _font("DejaVuSans-Bold.ttf", 16)
        draw.text((33, y + 6), initial, fill=_TT_TEXT, font=initial_font)
        # Username
        draw.text((68, y + 2), user, fill=_TT_TEXT_DIM, font=user_font)
        # Message (truncated)
        wrapped = msg if len(msg) < 64 else msg[:61] + "..."
        draw.text((68, y + 18), wrapped, fill=_TT_TEXT, font=comment_font)
        y += 38

    return image
