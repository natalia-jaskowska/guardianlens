"""High-fidelity Discord chat generator for demo video production.

Renders 1920x1080 frames of a fictional Discord channel using the current
(2024) Discord dark theme visual language. Supports:

- Full layout: guild bar, channel list, chat area, members panel
- Rich messages: role-coloured usernames, replies, reactions, GIF embeds,
  mentions, procedural avatars
- Progressive frame rendering (one message revealed per frame, typing
  indicator for the next speaker) so a short scenario turns into a set of
  frames ready for the ``--watch-folder`` pipeline
- Four threat scenarios: safe, grooming, bullying, scam

This module is **separate** from :mod:`guardlens.demo`. ``demo.py`` is the
lightweight monitor-loop renderer used by the app at runtime
(``--demo-mode``). This module is a production-quality generator whose
output is compiled into the demo video.

Typical use::

    from pathlib import Path
    from guardlens.discord_chat import render_scenario

    render_scenario("grooming", Path("outputs/video_feeds/discord_grooming"))

See ``scripts/render_discord.py`` for the CLI entry point.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Literal

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Colour palette (Discord 2024 refresh)
# ---------------------------------------------------------------------------

BG_PRIMARY = (49, 51, 56)  # #313338 — chat area
BG_SECONDARY = (43, 45, 49)  # #2b2d31 — channel list, members panel
BG_TERTIARY = (30, 31, 34)  # #1e1f22 — guild bar
BG_ACCENT = (53, 55, 60)  # #35373c — hover / active channel
BG_INPUT = (56, 58, 64)  # #383a40 — input box
BG_MENTION = (74, 77, 140)  # mention highlight row
BG_REACTION = (43, 45, 49)
BG_REACTION_SELF = (58, 64, 128)
BG_GIF = (32, 34, 37)

TEXT_NORMAL = (219, 222, 225)  # #dbdee1
TEXT_MUTED = (148, 155, 164)  # #949ba4
TEXT_HEADER = (242, 243, 245)  # #f2f3f5
TEXT_LINK = (0, 168, 252)  # #00a8fc
TEXT_MENTION = (201, 205, 251)  # #c9cdfb

BLURPLE = (88, 101, 242)  # #5865f2
ONLINE = (35, 165, 90)  # #23a55a
IDLE = (240, 178, 50)  # #f0b232
DND = (242, 63, 67)  # #f23f43

DIVIDER = (62, 64, 70)

# Discord's default avatar colours
AVATAR_COLORS: tuple[tuple[int, int, int], ...] = (
    (88, 101, 242),  # blurple
    (116, 127, 141),  # grey
    (59, 165, 93),  # green
    (250, 166, 26),  # yellow
    (237, 66, 69),  # red
    (235, 69, 158),  # fuchsia
)

# Role colours used for usernames in chat
ROLE_COLORS: tuple[tuple[int, int, int], ...] = (
    (255, 115, 250),  # pink
    (88, 101, 242),  # blurple
    (59, 165, 93),  # green
    (255, 200, 60),  # yellow
    (240, 102, 100),  # red
    (87, 242, 135),  # mint
    (255, 170, 30),  # orange
    (200, 130, 255),  # purple
)

# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------

_FONT_DIR = "/usr/share/fonts/TTF"
_REGULAR = "DejaVuSans.ttf"
_BOLD = "DejaVuSans-Bold.ttf"
_MONO = "DejaVuSansMono.ttf"


@lru_cache(maxsize=64)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Cached font loader. Falls back to Pillow's default if a TTF is missing."""
    try:
        return ImageFont.truetype(f"{_FONT_DIR}/{name}", size)
    except OSError:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

Status = Literal["online", "idle", "dnd", "offline"]
Scenario = Literal["safe", "grooming", "bullying", "scam"]


@dataclass
class Attachment:
    """A GIF/image embed below a message.

    Rendered as a rounded gradient tile with a "GIF" badge top-left, a
    centred caption, and a "via Tenor" label at the bottom. No real image
    asset required — fully procedural.
    """

    kind: Literal["gif", "image"] = "gif"
    caption: str = "reaction"
    source: str = "Tenor"
    width: int = 360
    height: int = 200
    palette: tuple[tuple[int, int, int], tuple[int, int, int]] = (
        (60, 70, 160),
        (220, 100, 200),
    )


@dataclass
class Reaction:
    """A reaction cluster displayed beneath a message."""

    emoji: str  # single-char or short label rendered inside the pill
    count: int = 1
    self_reacted: bool = False


@dataclass
class Message:
    author: str
    text: str
    timestamp: str = "14:22"  # HH:MM, rendered as "Today at HH:MM"
    reply_to: Message | None = None
    attachment: Attachment | None = None
    reactions: list[Reaction] = field(default_factory=list)
    mention: str | None = None  # @user span to highlight
    role_color: tuple[int, int, int] | None = None


@dataclass
class Channel:
    name: str
    topic: str = ""
    active: bool = False
    unread: bool = False
    mention_count: int = 0
    icon: str = "#"


@dataclass
class Member:
    name: str
    status: Status = "online"
    role_color: tuple[int, int, int] | None = None
    activity: str | None = None  # "Playing Minecraft" etc.


@dataclass
class Server:
    """Guild metadata: name shown at the top of the channel list + icon letter."""

    name: str
    icon: str = "S"
    color: tuple[int, int, int] = BLURPLE


# ---------------------------------------------------------------------------
# Deterministic helpers (avatars, role colours)
# ---------------------------------------------------------------------------


def _seed(name: str) -> int:
    return int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)


def _avatar_color(name: str) -> tuple[int, int, int]:
    return AVATAR_COLORS[_seed(name) % len(AVATAR_COLORS)]


def _role_color(name: str) -> tuple[int, int, int]:
    return ROLE_COLORS[_seed(name) % len(ROLE_COLORS)]


def _status_color(status: Status) -> tuple[int, int, int]:
    return {
        "online": ONLINE,
        "idle": IDLE,
        "dnd": DND,
        "offline": (128, 132, 142),
    }[status]


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------


def _draw_circle(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
) -> None:
    """Anti-aliased circle via 4x supersampling."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    ss = 4
    layer = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((0, 0, w * ss - 1, h * ss - 1), fill=(*fill, 255))
    layer = layer.resize((w, h), Image.LANCZOS)  # type: ignore[attr-defined]
    canvas.paste(layer, (x0, y0), layer)


def _draw_rounded(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int] | tuple[int, int, int, int],
) -> None:
    """Anti-aliased rounded rect via 2x supersampling."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    ss = 2
    fill_rgba = (*fill, 255) if len(fill) == 3 else fill
    layer = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, w * ss - 1, h * ss - 1),
        radius=radius * ss,
        fill=fill_rgba,
    )
    layer = layer.resize((w, h), Image.LANCZOS)  # type: ignore[attr-defined]
    canvas.paste(layer, (x0, y0), layer)


def _draw_avatar(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    name: str,
    status: Status | None = None,
    status_bg: tuple[int, int, int] = BG_PRIMARY,
) -> None:
    """Discord-style circular avatar with initial + optional status dot."""
    color = _avatar_color(name)
    _draw_circle(canvas, (x, y, x + size, y + size), color)

    initial = name[0].upper() if name else "?"
    font_size = int(size * 0.5)
    font = _font(_BOLD, font_size)
    iw = int(draw.textlength(initial, font=font))
    bbox = font.getbbox(initial)
    ih = bbox[3] - bbox[1]
    draw.text(
        (x + size // 2 - iw // 2, y + size // 2 - ih // 2 - bbox[1]),
        initial,
        fill=(255, 255, 255),
        font=font,
    )

    if status is not None:
        dot = max(10, size // 3)
        dx = x + size - dot - 1
        dy = y + size - dot - 1
        # Punch a hole into the background
        _draw_circle(
            canvas,
            (dx - 3, dy - 3, dx + dot + 3, dy + dot + 3),
            status_bg,
        )
        _draw_circle(
            canvas,
            (dx, dy, dx + dot, dy + dot),
            _status_color(status),
        )


def _wrap(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Greedy word wrap that honours an explicit newline in ``text``."""
    lines: list[str] = []
    for raw_line in text.split("\n"):
        words = raw_line.split(" ")
        current = ""
        for word in words:
            trial = word if not current else current + " " + word
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_gif_embed(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    attachment: Attachment,
) -> int:
    """Draw a fake GIF tile. Returns total height drawn (incl. footer)."""
    w, h = attachment.width, attachment.height
    (x, y, x + w, y + h)

    # Background gradient (procedural, diagonal)
    tile = Image.new("RGB", (w, h), attachment.palette[0])
    t_draw = ImageDraw.Draw(tile)
    start, end = attachment.palette
    for i in range(h):
        t = i / max(1, h - 1)
        r = int(start[0] * (1 - t) + end[0] * t)
        g = int(start[1] * (1 - t) + end[1] * t)
        b = int(start[2] * (1 - t) + end[2] * t)
        t_draw.line((0, i, w, i), fill=(r, g, b))
    # Soft diagonal light streak for motion feel
    for i in range(-h, w, 4):
        alpha_line = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(alpha_line).line((i, 0, i + h, h), fill=(255, 255, 255, 12), width=2)
        tile = Image.alpha_composite(tile.convert("RGBA"), alpha_line).convert("RGB")
    # Mask to rounded rect
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=8, fill=255)
    canvas.paste(tile, (x, y), mask)

    # Caption (big centred)
    caption_font = _font(_BOLD, 28)
    cw = int(draw.textlength(attachment.caption, font=caption_font))
    draw.text(
        (x + w // 2 - cw // 2, y + h // 2 - 22),
        attachment.caption,
        fill=(255, 255, 255),
        font=caption_font,
    )
    sub_font = _font(_REGULAR, 13)
    sub = "animated preview"
    sw = int(draw.textlength(sub, font=sub_font))
    draw.text(
        (x + w // 2 - sw // 2, y + h // 2 + 14),
        sub,
        fill=(235, 235, 235),
        font=sub_font,
    )

    # "GIF" badge top-left
    badge_font = _font(_BOLD, 12)
    badge_w, badge_h = 34, 20
    _draw_rounded(
        canvas,
        (x + 10, y + 10, x + 10 + badge_w, y + 10 + badge_h),
        radius=4,
        fill=(0, 0, 0, 180),
    )
    draw.text((x + 18, y + 12), "GIF", fill=(255, 255, 255), font=badge_font)

    # "via Tenor" footer
    footer_font = _font(_REGULAR, 11)
    draw.text(
        (x + 10, y + h + 4),
        f"via {attachment.source}",
        fill=TEXT_MUTED,
        font=footer_font,
    )
    return h + 18  # tile + footer


def _draw_reactions(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    reactions: Sequence[Reaction],
) -> int:
    """Draw reaction pills. Returns height consumed."""
    if not reactions:
        return 0
    cursor = x
    pill_font = _font(_BOLD, 13)
    for r in reactions:
        label = f" {r.emoji}  {r.count} "
        tw = int(draw.textlength(label, font=pill_font))
        pill_w = tw + 8
        pill_h = 26
        fill = BG_REACTION_SELF if r.self_reacted else BG_REACTION
        _draw_rounded(
            canvas,
            (cursor, y, cursor + pill_w, y + pill_h),
            radius=8,
            fill=fill,
        )
        draw.text(
            (cursor + 6, y + 5),
            label.strip(),
            fill=TEXT_MENTION if r.self_reacted else TEXT_NORMAL,
            font=pill_font,
        )
        cursor += pill_w + 6
    return 32


def _draw_reply_block(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    max_width: int,
    reply_to: Message,
) -> int:
    """Draw the quoted-reply strip above a reply message."""
    # Curved connector line
    line_color = DIVIDER
    draw.line((x - 32, y + 22, x - 32, y + 10), fill=line_color, width=2)
    draw.line((x - 32, y + 10, x - 4, y + 10), fill=line_color, width=2)

    # Tiny avatar
    av_size = 16
    _draw_avatar(canvas, draw, x, y + 2, av_size, reply_to.author)

    name_font = _font(_BOLD, 13)
    text_font = _font(_REGULAR, 13)
    name_color = reply_to.role_color or _role_color(reply_to.author)

    name_x = x + av_size + 6
    draw.text((name_x, y + 2), reply_to.author, fill=name_color, font=name_font)
    nw = int(draw.textlength(reply_to.author, font=name_font))

    preview = reply_to.text.replace("\n", " ")
    available = max_width - (nw + 14)
    if draw.textlength(preview, font=text_font) > available:
        while preview and draw.textlength(preview + "...", font=text_font) > available:
            preview = preview[:-1]
        preview = preview.rstrip() + "..."
    draw.text((name_x + nw + 8, y + 2), preview, fill=TEXT_MUTED, font=text_font)

    return 24


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

WIDTH = 1920
HEIGHT = 1080

GUILD_BAR_W = 72
CHANNEL_LIST_W = 240
MEMBERS_W = 240

HEADER_H = 48
INPUT_H = 92

CHAT_X0 = GUILD_BAR_W + CHANNEL_LIST_W  # 312
CHAT_X1 = WIDTH - MEMBERS_W  # 1680
CHAT_Y0 = HEADER_H  # 48
CHAT_Y1 = HEIGHT - INPUT_H  # 988

AVATAR_SIZE = 44
MESSAGE_LEFT_MARGIN = 16
MESSAGE_TEXT_X = CHAT_X0 + MESSAGE_LEFT_MARGIN + AVATAR_SIZE + 16  # 388
MESSAGE_TEXT_MAX_W = CHAT_X1 - MESSAGE_TEXT_X - 40  # 1252


# ---------------------------------------------------------------------------
# Region renderers
# ---------------------------------------------------------------------------


def _draw_guild_bar(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, GUILD_BAR_W, HEIGHT), fill=BG_TERTIARY)

    # Home / Discord logo pill
    home_y = 12
    _draw_rounded(canvas, (14, home_y, 58, home_y + 44), radius=14, fill=BLURPLE)
    logo_font = _font(_BOLD, 18)
    draw.text((27, home_y + 12), "D", fill=(255, 255, 255), font=logo_font)

    # Separator
    draw.line((18, 68, 54, 68), fill=(53, 55, 60), width=2)

    # Four sample guild icons (one active)
    guilds = [
        ("G", BLURPLE, True),
        ("M", (237, 66, 69), False),
        ("R", (59, 165, 93), False),
        ("K", (250, 166, 26), False),
    ]
    for i, (letter, color, active) in enumerate(guilds):
        gy = 82 + i * 58
        radius = 14 if active else 22
        _draw_rounded(canvas, (14, gy, 58, gy + 44), radius=radius, fill=color)
        lfw = _font(_BOLD, 17)
        lw = int(draw.textlength(letter, font=lfw))
        draw.text((36 - lw // 2, gy + 12), letter, fill=(255, 255, 255), font=lfw)
        if active:
            _draw_rounded(canvas, (0, gy + 6, 4, gy + 38), radius=2, fill=(255, 255, 255))


def _draw_channel_list(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    server: Server,
    channels: Sequence[Channel],
) -> None:
    x0 = GUILD_BAR_W
    x1 = x0 + CHANNEL_LIST_W
    draw.rectangle((x0, 0, x1, HEIGHT), fill=BG_SECONDARY)

    # Server header
    header_h = 48
    draw.line((x0, header_h, x1, header_h), fill=(24, 25, 28), width=2)
    name_font = _font(_BOLD, 15)
    draw.text((x0 + 16, 16), server.name, fill=TEXT_HEADER, font=name_font)
    # Dropdown chevron
    chev_font = _font(_BOLD, 14)
    draw.text((x1 - 24, 16), "v", fill=TEXT_MUTED, font=chev_font)

    # TEXT CHANNELS section label
    section_font = _font(_BOLD, 11)
    draw.text((x0 + 18, 64), "TEXT CHANNELS", fill=TEXT_MUTED, font=section_font)
    # "+" add-channel button
    draw.text((x1 - 22, 62), "+", fill=TEXT_MUTED, font=_font(_BOLD, 16))

    chan_font = _font(_REGULAR, 15)
    chan_font_bold = _font(_BOLD, 15)
    badge_font = _font(_BOLD, 11)
    cy = 90
    for ch in channels:
        row = (x0 + 8, cy - 4, x1 - 8, cy + 26)
        if ch.active:
            _draw_rounded(canvas, row, radius=4, fill=BG_ACCENT)
            color = TEXT_HEADER
            font = chan_font_bold
        elif ch.unread:
            color = TEXT_HEADER
            font = chan_font_bold
            # Unread pill indicator on the left edge
            draw.rectangle((x0, cy + 4, x0 + 3, cy + 18), fill=(255, 255, 255))
        else:
            color = TEXT_MUTED
            font = chan_font
        hash_font = _font(_REGULAR, 18)
        draw.text((x0 + 16, cy - 1), ch.icon, fill=color, font=hash_font)
        draw.text((x0 + 34, cy + 2), ch.name, fill=color, font=font)
        if ch.mention_count:
            # Red mention badge on the right
            label = str(ch.mention_count)
            lw = int(draw.textlength(label, font=badge_font))
            bw = max(18, lw + 10)
            _draw_rounded(
                canvas,
                (x1 - 16 - bw, cy + 4, x1 - 16, cy + 22),
                radius=9,
                fill=(242, 63, 67),
            )
            draw.text(
                (x1 - 16 - bw + (bw - lw) // 2, cy + 6),
                label,
                fill=(255, 255, 255),
                font=badge_font,
            )
        cy += 30

    # Voice channels section
    cy += 8
    draw.text((x0 + 18, cy), "VOICE CHANNELS", fill=TEXT_MUTED, font=section_font)
    cy += 24
    for voice_name in ("General", "Gaming"):
        draw.text((x0 + 14, cy), "[)", fill=TEXT_MUTED, font=_font(_REGULAR, 14))
        draw.text((x0 + 36, cy), voice_name, fill=TEXT_MUTED, font=chan_font)
        cy += 28

    # User panel at bottom
    panel_y = HEIGHT - 56
    draw.rectangle((x0, panel_y, x1, HEIGHT), fill=(36, 37, 41))
    _draw_avatar(
        canvas,
        draw,
        x0 + 10,
        panel_y + 10,
        36,
        "GuardianLens",
        status="online",
        status_bg=(36, 37, 41),
    )
    draw.text(
        (x0 + 54, panel_y + 10),
        "GuardianLens",
        fill=TEXT_HEADER,
        font=_font(_BOLD, 13),
    )
    draw.text(
        (x0 + 54, panel_y + 28),
        "#0001",
        fill=TEXT_MUTED,
        font=_font(_REGULAR, 11),
    )
    # Icons (mic / deafen / settings) — stylised with letters
    icon_font = _font(_BOLD, 14)
    for i, icon_char in enumerate(["M", "H", "*"]):
        draw.text((x1 - 72 + i * 22, panel_y + 20), icon_char, fill=TEXT_MUTED, font=icon_font)


def _draw_channel_header(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    channel: Channel,
) -> None:
    draw.rectangle((CHAT_X0, 0, WIDTH, HEADER_H), fill=BG_PRIMARY)
    draw.line((CHAT_X0, HEADER_H, WIDTH, HEADER_H), fill=(24, 25, 28), width=1)

    hash_font = _font(_REGULAR, 24)
    name_font = _font(_BOLD, 16)
    topic_font = _font(_REGULAR, 13)

    draw.text((CHAT_X0 + 16, 10), "#", fill=TEXT_MUTED, font=hash_font)
    draw.text((CHAT_X0 + 40, 14), channel.name, fill=TEXT_HEADER, font=name_font)
    nw = int(draw.textlength(channel.name, font=name_font))

    if channel.topic:
        sep_x = CHAT_X0 + 40 + nw + 14
        draw.line((sep_x, 14, sep_x, 34), fill=DIVIDER, width=1)
        draw.text((sep_x + 12, 17), channel.topic, fill=TEXT_MUTED, font=topic_font)

    # Right-aligned header affordances (search box + icon stubs).
    # We draw minimalist circles/rectangles for pin/bell/members/inbox/help
    # instead of letters — much closer to the real Discord toolbar.
    search_w = 180
    search_h = 24
    sx1 = WIDTH - 24
    sx0 = sx1 - search_w
    sy0 = 12
    _draw_rounded(canvas, (sx0, sy0, sx1, sy0 + search_h), radius=4, fill=BG_TERTIARY)
    draw.text(
        (sx0 + 10, sy0 + 4),
        "Search",
        fill=TEXT_MUTED,
        font=_font(_REGULAR, 12),
    )
    # Icon stubs: 6 small circles left of the search box
    icon_cy = 24
    cursor = sx0 - 18
    for _ in range(6):
        _draw_circle(
            canvas,
            (cursor - 7, icon_cy - 7, cursor + 7, icon_cy + 7),
            (60, 62, 68),
        )
        cursor -= 22


def _draw_day_separator(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str = "Today",
) -> int:
    sep_font = _font(_BOLD, 12)
    tw = int(draw.textlength(text, font=sep_font))
    center = (CHAT_X0 + CHAT_X1) // 2
    draw.line(
        (CHAT_X0 + 20, y, center - tw // 2 - 10, y),
        fill=DIVIDER,
        width=1,
    )
    draw.text((center - tw // 2, y - 8), text, fill=TEXT_MUTED, font=sep_font)
    draw.line(
        (center + tw // 2 + 10, y, CHAT_X1 - 20, y),
        fill=DIVIDER,
        width=1,
    )
    return 24


def _measure_message_height(
    draw: ImageDraw.ImageDraw,
    msg: Message,
    new_group: bool,
) -> int:
    """Pre-compute the vertical height this message will consume."""
    text_font = _font(_REGULAR, 15)
    total = 0
    if new_group:
        total += 10  # top padding
        if msg.reply_to is not None:
            total += 24
        total += 22  # username/timestamp row
    lines = _wrap(msg.text, text_font, MESSAGE_TEXT_MAX_W, draw)
    total += len(lines) * 22
    if msg.attachment is not None:
        total += 10 + msg.attachment.height + 18
    if msg.reactions:
        total += 10 + 32
    total += 4  # bottom padding
    return total


def _draw_message_group(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: int,
    msg: Message,
    new_group: bool,
) -> int:
    """Draw one message (possibly part of an existing group). Returns height."""
    start_y = y
    text_font = _font(_REGULAR, 15)

    if new_group:
        y += 10
        if msg.reply_to is not None:
            _draw_reply_block(canvas, draw, MESSAGE_TEXT_X, y, MESSAGE_TEXT_MAX_W, msg.reply_to)
            y += 24

        # Avatar
        _draw_avatar(
            canvas,
            draw,
            CHAT_X0 + MESSAGE_LEFT_MARGIN,
            y,
            AVATAR_SIZE,
            msg.author,
        )

        name_font = _font(_BOLD, 16)
        ts_font = _font(_REGULAR, 12)
        name_color = msg.role_color or _role_color(msg.author)
        draw.text(
            (MESSAGE_TEXT_X, y - 2),
            msg.author,
            fill=name_color,
            font=name_font,
        )
        nw = int(draw.textlength(msg.author, font=name_font))
        draw.text(
            (MESSAGE_TEXT_X + nw + 10, y + 2),
            f"Today at {msg.timestamp}",
            fill=TEXT_MUTED,
            font=ts_font,
        )
        y += 22
    else:
        # Continuation: no avatar, no name — just text under previous
        pass

    # Message text (with optional mention highlight)
    lines = _wrap(msg.text, text_font, MESSAGE_TEXT_MAX_W, draw)
    for line in lines:
        _draw_line_with_mention(draw, MESSAGE_TEXT_X, y, line, text_font, msg.mention)
        y += 22

    # Attachment
    if msg.attachment is not None:
        y += 10
        consumed = _draw_gif_embed(canvas, draw, MESSAGE_TEXT_X, y, msg.attachment)
        y += consumed

    # Reactions
    if msg.reactions:
        y += 10
        _draw_reactions(canvas, draw, MESSAGE_TEXT_X, y, msg.reactions)
        y += 32

    y += 4
    return y - start_y


def _draw_line_with_mention(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    mention: str | None,
) -> None:
    """Render a text line, highlighting ``@mention`` tokens if present."""
    if mention is None or mention not in text:
        draw.text((x, y), text, fill=TEXT_NORMAL, font=font)
        return

    # Split around the mention to colour it
    before, _, after = text.partition(mention)
    cursor = x
    if before:
        draw.text((cursor, y), before, fill=TEXT_NORMAL, font=font)
        cursor += int(draw.textlength(before, font=font))
    # Mention pill background
    mw = int(draw.textlength(mention, font=font))
    draw.rectangle(
        (cursor - 2, y - 1, cursor + mw + 2, y + 20),
        fill=BG_MENTION,
    )
    draw.text((cursor, y), mention, fill=TEXT_MENTION, font=font)
    cursor += mw
    if after:
        draw.text((cursor, y), after, fill=TEXT_NORMAL, font=font)


def _draw_messages(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    messages: Sequence[Message],
    typing: str | None,
) -> None:
    """Render messages inside the chat area, oldest → newest.

    If the total block is taller than the chat area, the oldest messages are
    dropped so the newest always stay visible (Discord auto-scroll).
    """
    # Build (new_group, msg) pairs
    groups: list[tuple[bool, Message]] = []
    last_author: str | None = None
    for m in messages:
        new_group = m.author != last_author or m.reply_to is not None
        groups.append((new_group, m))
        last_author = m.author

    # Reserve room for the day separator (22) and typing indicator (30 if any)
    reserved_top = 22
    reserved_bottom = 30 if typing else 0
    avail = (CHAT_Y1 - CHAT_Y0) - reserved_top - reserved_bottom

    heights = [_measure_message_height(draw, m, ng) for ng, m in groups]
    total = sum(heights)
    start_idx = 0
    while total > avail and start_idx < len(groups) - 1:
        total -= heights[start_idx]
        start_idx += 1

    # If the first surviving group is a continuation, promote it to a new group
    if start_idx > 0 and not groups[start_idx][0]:
        groups[start_idx] = (True, groups[start_idx][1])
        heights[start_idx] = _measure_message_height(draw, groups[start_idx][1], True)

    y = CHAT_Y0 + 8
    y += _draw_day_separator(canvas, draw, y + 8)
    for i in range(start_idx, len(groups)):
        new_group, msg = groups[i]
        h = _draw_message_group(canvas, draw, y, msg, new_group)
        y += h

    if typing:
        _draw_typing_indicator(canvas, draw, typing)


def _draw_typing_indicator(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    typing: str,
) -> None:
    """Render the 'X is typing...' strip above the input box."""
    y = CHAT_Y1 - 20
    # Three bouncing dots
    dot_x = CHAT_X0 + 20
    for i in range(3):
        cx = dot_x + i * 10
        cy = y + 10
        _draw_circle(canvas, (cx - 3, cy - 3, cx + 3, cy + 3), TEXT_MUTED)
    font = _font(_REGULAR, 13)
    font_bold = _font(_BOLD, 13)
    text_x = dot_x + 32
    draw.text((text_x, y + 2), typing, fill=TEXT_HEADER, font=font_bold)
    tw = int(draw.textlength(typing, font=font_bold))
    draw.text((text_x + tw + 6, y + 2), "is typing...", fill=TEXT_MUTED, font=font)


def _draw_input_box(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    channel: Channel,
) -> None:
    y0 = HEIGHT - INPUT_H + 8
    _draw_rounded(
        canvas,
        (CHAT_X0 + 16, y0, CHAT_X1 - 16, y0 + 48),
        radius=8,
        fill=BG_INPUT,
    )
    # Plus button
    plus_cx = CHAT_X0 + 40
    plus_cy = y0 + 24
    _draw_circle(
        canvas,
        (plus_cx - 11, plus_cy - 11, plus_cx + 11, plus_cy + 11),
        TEXT_MUTED,
    )
    draw.text(
        (plus_cx - 5, plus_cy - 10),
        "+",
        fill=BG_INPUT,
        font=_font(_BOLD, 16),
    )
    # Placeholder
    draw.text(
        (CHAT_X0 + 60, y0 + 14),
        f"Message #{channel.name}",
        fill=TEXT_MUTED,
        font=_font(_REGULAR, 14),
    )
    # Right-side icon stubs (gift / GIF / sticker / emoji) — drawn as small
    # rounded rects so they read as "icons" at thumbnail scale without the
    # clumsy letter placeholders.
    icon_cy = y0 + 24
    cursor = CHAT_X1 - 32
    # Rounded square for "GIF" button (only labelled icon — it's the most
    # recognisable affordance in Discord's input bar).
    _draw_rounded(
        canvas,
        (cursor - 14, icon_cy - 9, cursor + 14, icon_cy + 9),
        radius=3,
        fill=TEXT_MUTED,
    )
    gif_font = _font(_BOLD, 10)
    gw = int(draw.textlength("GIF", font=gif_font))
    draw.text(
        (cursor - gw // 2, icon_cy - 6),
        "GIF",
        fill=BG_INPUT,
        font=gif_font,
    )
    cursor -= 36
    for _ in range(3):
        _draw_circle(
            canvas,
            (cursor - 9, icon_cy - 9, cursor + 9, icon_cy + 9),
            TEXT_MUTED,
        )
        cursor -= 26


def _draw_members_panel(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    members: Sequence[Member],
) -> None:
    x0 = CHAT_X1
    draw.rectangle((x0, HEADER_H, WIDTH, HEIGHT), fill=BG_SECONDARY)

    section_font = _font(_BOLD, 12)
    row_font = _font(_REGULAR, 14)
    sub_font = _font(_REGULAR, 11)

    online = [m for m in members if m.status != "offline"]
    offline = [m for m in members if m.status == "offline"]

    y = HEADER_H + 18
    if online:
        draw.text(
            (x0 + 18, y),
            f"ONLINE — {len(online)}",
            fill=TEXT_MUTED,
            font=section_font,
        )
        y += 22
        for m in online:
            _draw_member_row(canvas, draw, x0, y, m, row_font, sub_font)
            y += 44
            if y > HEIGHT - 80:
                break

    if offline and y < HEIGHT - 80:
        y += 6
        draw.text(
            (x0 + 18, y),
            f"OFFLINE — {len(offline)}",
            fill=TEXT_MUTED,
            font=section_font,
        )
        y += 22
        for m in offline:
            _draw_member_row(canvas, draw, x0, y, m, row_font, sub_font)
            y += 44
            if y > HEIGHT - 80:
                break


def _draw_member_row(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    member: Member,
    name_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    sub_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    _draw_avatar(
        canvas,
        draw,
        x0 + 12,
        y,
        32,
        member.name,
        status=member.status,
        status_bg=BG_SECONDARY,
    )
    name_color = member.role_color or (
        _role_color(member.name) if member.status != "offline" else TEXT_MUTED
    )
    text_y = y + (4 if member.activity else 8)
    draw.text((x0 + 52, text_y), member.name, fill=name_color, font=name_font)
    if member.activity:
        draw.text(
            (x0 + 52, y + 22),
            member.activity,
            fill=TEXT_MUTED,
            font=sub_font,
        )


# ---------------------------------------------------------------------------
# Top-level frame renderer
# ---------------------------------------------------------------------------


def render_frame(
    server: Server,
    channels: Sequence[Channel],
    channel: Channel,
    messages: Sequence[Message],
    members: Sequence[Member],
    *,
    typing: str | None = None,
) -> Image.Image:
    """Render one complete 1920×1080 Discord frame."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG_PRIMARY)
    draw = ImageDraw.Draw(canvas)

    _draw_guild_bar(canvas, draw)
    _draw_channel_list(canvas, draw, server, channels)
    _draw_channel_header(canvas, draw, channel)
    _draw_members_panel(canvas, draw, members)
    _draw_messages(canvas, draw, messages, typing)
    _draw_input_box(canvas, draw, channel)

    return canvas


# ---------------------------------------------------------------------------
# Scenario library
# ---------------------------------------------------------------------------


@dataclass
class DiscordScenario:
    server: Server
    channels: list[Channel]
    channel: Channel
    members: list[Member]
    messages: list[Message]


def _safe_scenario() -> DiscordScenario:
    server = Server(name="Middle School Gaming", icon="M")
    channels = [
        Channel(name="announcements", icon="#"),
        Channel(name="general-chat", icon="#", active=True, topic="homework, games, memes"),
        Channel(name="among-us-squad", icon="#", unread=True),
        Channel(name="minecraft", icon="#"),
        Channel(name="homework-help", icon="#", mention_count=2),
        Channel(name="memes", icon="#"),
    ]
    members = [
        Member("PixelBuilder", "online"),
        Member("Em_22", "online", activity="Playing Roblox"),
        Member("Sammy7", "online"),
        Member("Leo.x", "idle"),
        Member("RainDrop", "dnd", activity="Do Not Disturb"),
        Member("ChatBot", "online", role_color=(88, 101, 242), activity="Moderator"),
        Member("JayK", "offline"),
        Member("MinaMoon", "offline"),
    ]

    # Classmates planning a study session — includes address-sharing and
    # age-asking in a clearly safe context (same school, parent awareness).
    m1 = Message("PixelBuilder", "yo did anyone start the science project yet?", timestamp="14:02")
    m2 = Message("Em_22", "yeah i picked volcanoes lol", timestamp="14:02")
    m3 = Message(
        "Sammy7",
        "me and jake are doing ours together, wanna join our group?",
        timestamp="14:03",
        reply_to=m2,
    )
    m4 = Message("PixelBuilder", "yeah sure! when are we meeting?", timestamp="14:03")
    m5 = Message(
        "Em_22",
        "we could do saturday at my house, my mom said its ok",
        timestamp="14:04",
        reactions=[Reaction("+1", 2, self_reacted=True)],
    )
    m6 = Message("Sammy7", "works for me. whats the address again?", timestamp="14:04")
    m7 = Message("Em_22", "412 oak street, come around 2", timestamp="14:05")
    m8 = Message(
        "PixelBuilder", "wait is jake in our class? how old is he", timestamp="14:05", reply_to=m3
    )
    m9 = Message("Sammy7", "yeah hes 13 hes in mr davis period 3", timestamp="14:06")
    m10 = Message(
        "PixelBuilder",
        "oh cool ok im bringing snacks",
        timestamp="14:07",
        attachment=Attachment(
            caption="snack time",
            palette=((50, 160, 80), (220, 200, 40)),
        ),
    )
    m11 = Message(
        "Em_22", "yesss get hot cheetos", timestamp="14:07", reactions=[Reaction("fire", 3)]
    )
    m12 = Message("Sammy7", "lol u guys always want hot cheetos", timestamp="14:08")

    return DiscordScenario(
        server=server,
        channels=channels,
        channel=channels[1],
        members=members,
        messages=[m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11, m12],
    )


def _grooming_scenario() -> DiscordScenario:
    server = Server(name="Roblox Friends", icon="R")
    channels = [
        Channel(name="welcome", icon="#"),
        Channel(name="general", icon="#", active=True, topic="just chatting"),
        Channel(name="trades", icon="#"),
        Channel(name="voice-chat", icon="#"),
    ]
    members = [
        Member("ShadowPro", "online", activity="Playing Roblox"),
        Member("KidGamer09", "online"),
        Member("BubbleBee", "idle"),
        Member("NightOwl", "dnd"),
        Member("ModBot", "online", role_color=(88, 101, 242)),
        Member("Kay_K", "offline"),
    ]

    # Slow-burn grooming: shared interest → rapport → age inquiry →
    # flattery → gift offering → platform switch → secrecy demand.
    # Longer than the old version so the escalation *pattern* is clear
    # and the model can distinguish it from normal teen chat.
    m1 = Message("ShadowPro", "gg that last round was crazy", timestamp="16:42")
    m2 = Message("KidGamer09", "thanks! ive been practicing a lot lately", timestamp="16:42")
    m3 = Message(
        "ShadowPro", "i can tell. how long have you been playing?", timestamp="16:43", reply_to=m2
    )
    m4 = Message("KidGamer09", "like 6 months maybe", timestamp="16:43")
    m5 = Message(
        "ShadowPro",
        "wow youre way better than i was at 6 months. how old are you btw?",
        timestamp="16:44",
    )
    m6 = Message("KidGamer09", "13", timestamp="16:44")
    m7 = Message(
        "ShadowPro",
        "nice im 15. you play super mature for your age tho",
        timestamp="16:45",
        attachment=Attachment(
            caption="heart eyes",
            palette=((220, 60, 120), (255, 180, 100)),
        ),
    )
    m8 = Message(
        "ShadowPro",
        "i could coach you if you want, i know some tricks most people dont",
        timestamp="16:46",
    )
    m9 = Message(
        "KidGamer09",
        "really? that would be awesome",
        timestamp="16:46",
        reactions=[Reaction("+1", 1)],
    )
    m10 = Message(
        "ShadowPro",
        "yeah for sure. do you have snap? way easier to send clips and stuff there",
        timestamp="16:47",
        reply_to=m9,
    )
    m11 = Message(
        "ShadowPro",
        "prob better not to mention it in the server tho, people get weird about private coaching",
        timestamp="16:47",
    )
    m12 = Message("KidGamer09", "oh ok", timestamp="16:48")
    m13 = Message(
        "ShadowPro",
        "ill send you some gift cards too for new skins, just keep it between us ok?",
        timestamp="16:48",
    )

    return DiscordScenario(
        server=server,
        channels=channels,
        channel=channels[1],
        members=members,
        messages=[m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11, m12, m13],
    )


def _bullying_scenario() -> DiscordScenario:
    server = Server(name="7th Grade Lounge", icon="7")
    channels = [
        Channel(name="rules", icon="#"),
        Channel(name="general", icon="#", active=True, topic="main chat"),
        Channel(name="gossip", icon="#", unread=True, mention_count=5),
        Channel(name="memes", icon="#"),
    ]
    members = [
        Member("Maxxx_", "online"),
        Member("Lyla.x", "online", activity="Posting"),
        Member("KidGamer09", "online"),
        Member("xJess", "idle"),
        Member("MeanKid01", "dnd"),
        Member("Quiet1", "offline"),
    ]

    # Coordinated exclusion + humiliation. Multiple attackers gang up,
    # escalate from gatekeeping ("invite only") to personal attacks and
    # screenshot-sharing. Victim tries to de-escalate repeatedly.
    m1 = Message("KidGamer09", "hey can i come to the movie night?", timestamp="20:12")
    m2 = Message("Maxxx_", "uhh this is invite only", timestamp="20:12", reply_to=m1)
    m3 = Message("Lyla.x", "yeah we already have enough people", timestamp="20:13")
    m4 = Message("KidGamer09", "oh, em said it was open to everyone", timestamp="20:13")
    m5 = Message(
        "Maxxx_",
        "well she was wrong. you specifically cant come",
        timestamp="20:14",
        reactions=[Reaction("skull", 3), Reaction("clown", 2)],
    )
    m6 = Message("Lyla.x", "literally nobody wants you there lol", timestamp="20:14")
    m7 = Message("xJess", "yikes just take the hint", timestamp="20:15")
    m8 = Message("KidGamer09", "why are you guys being like this", timestamp="20:15")
    m9 = Message(
        "Maxxx_",
        "because youre annoying and everyone thinks so",
        timestamp="20:16",
    )
    m10 = Message(
        "Maxxx_",
        "we made a whole gc without you btw",
        timestamp="20:16",
        reactions=[Reaction("+1", 4)],
    )
    m11 = Message(
        "Lyla.x",
        "screenshots of your cringey posts are in there too lmao",
        timestamp="20:17",
        attachment=Attachment(
            caption="cringe compilation",
            palette=((180, 30, 80), (60, 20, 100)),
        ),
    )
    m12 = Message("KidGamer09", "please stop", timestamp="20:17")
    m13 = Message(
        "Maxxx_",
        "then leave the server, nobody is stopping you",
        timestamp="20:18",
        reactions=[Reaction("+1", 3), Reaction("wave", 2)],
    )

    return DiscordScenario(
        server=server,
        channels=channels,
        channel=channels[1],
        members=members,
        messages=[m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11, m12, m13],
    )


def _scam_scenario() -> DiscordScenario:
    server = Server(name="Free Nitro Hub", icon="$")
    channels = [
        Channel(name="read-me", icon="#"),
        Channel(
            name="giveaway",
            icon="#",
            active=True,
            topic="FREE DISCORD NITRO — claim before it expires!",
        ),
        Channel(name="winners", icon="#", mention_count=12),
        Channel(name="claim-now", icon="#", unread=True),
    ]
    members = [
        Member("NitroBot", "online", role_color=(250, 166, 26), activity="Giving away Nitro"),
        Member("KidGamer09", "online"),
        Member("Sammy7", "online"),
        Member("Winner01", "idle"),
        Member("ModBot", "online", role_color=(88, 101, 242)),
    ]

    # Fake Discord Nitro phishing — urgency + typosquatted domain +
    # credential harvesting. A friend spots the scam at the end.
    m1 = Message(
        "NitroBot",
        "ATTENTION! Discord is giving FREE NITRO to all server members!",
        timestamp="18:30",
        role_color=(250, 166, 26),
        attachment=Attachment(
            caption="FREE NITRO",
            palette=((88, 101, 242), (240, 60, 200)),
        ),
    )
    m2 = Message(
        "NitroBot",
        "claim your free nitro now before it expires!",
        timestamp="18:30",
        role_color=(250, 166, 26),
    )
    m3 = Message(
        "NitroBot",
        "click the link and verify your discord account",
        timestamp="18:31",
        role_color=(250, 166, 26),
        reactions=[Reaction("fire", 14), Reaction("money", 8)],
    )
    m4 = Message("KidGamer09", "wait is this real??", timestamp="18:33")
    m5 = Message(
        "NitroBot",
        "100% real! limited time only, 47 spots left!",
        timestamp="18:33",
        role_color=(250, 166, 26),
        reply_to=m4,
    )
    m6 = Message("KidGamer09", "omg ok how do i get it", timestamp="18:34")
    m7 = Message(
        "NitroBot",
        "go to disc0rd-gifts.com and login with your discord email and password",
        timestamp="18:34",
        role_color=(250, 166, 26),
    )
    m8 = Message(
        "NitroBot",
        "hurry only 23 left now!!",
        timestamp="18:35",
        role_color=(250, 166, 26),
    )
    m9 = Message("Sammy7", "wait that url looks weird, is that legit?", timestamp="18:36")
    m10 = Message(
        "NitroBot",
        "its the official giveaway partner site. DM me if link doesnt work i can verify you manually",
        timestamp="18:36",
        role_color=(250, 166, 26),
        reply_to=m9,
    )
    m11 = Message(
        "NitroBot",
        "just send your login info and ill add nitro directly to your account",
        timestamp="18:37",
        role_color=(250, 166, 26),
    )

    return DiscordScenario(
        server=server,
        channels=channels,
        channel=channels[1],
        members=members,
        messages=[m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11],
    )


SCENARIO_BUILDERS: dict[Scenario, Callable[[], DiscordScenario]] = {
    "safe": _safe_scenario,
    "grooming": _grooming_scenario,
    "bullying": _bullying_scenario,
    "scam": _scam_scenario,
}


def build_scenario(name: Scenario) -> DiscordScenario:
    if name not in SCENARIO_BUILDERS:
        raise ValueError(f"unknown scenario {name!r}; expected one of {sorted(SCENARIO_BUILDERS)}")
    return SCENARIO_BUILDERS[name]()


# ---------------------------------------------------------------------------
# Progressive rendering
# ---------------------------------------------------------------------------


def render_progressive(
    scenario: DiscordScenario,
    *,
    include_typing: bool = True,
) -> list[Image.Image]:
    """Render one frame per message, growing the chat each step.

    If ``include_typing`` is True, each frame shows a typing indicator for
    the **next** message's author (so the frame *before* a new message lands
    already shows them typing). The final frame has no typing indicator.
    """
    frames: list[Image.Image] = []
    msgs = scenario.messages
    for i in range(1, len(msgs) + 1):
        visible = msgs[:i]
        next_author = msgs[i].author if (include_typing and i < len(msgs)) else None
        typing = next_author if next_author and next_author != msgs[i - 1].author else None
        frames.append(
            render_frame(
                scenario.server,
                scenario.channels,
                scenario.channel,
                visible,
                scenario.members,
                typing=typing,
            )
        )
    return frames


def render_scenario(
    name: Scenario,
    out_dir: Path,
    *,
    filename_prefix: str = "frame",
) -> list[Path]:
    """Render a scenario and write each frame as a sorted PNG into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scenario = build_scenario(name)
    frames = render_progressive(scenario)
    paths: list[Path] = []
    for idx, img in enumerate(frames, start=1):
        p = out_dir / f"{filename_prefix}_{idx:04d}.png"
        img.save(p)
        paths.append(p)
    return paths


__all__ = [
    "Attachment",
    "Channel",
    "DiscordScenario",
    "Member",
    "Message",
    "Reaction",
    "Scenario",
    "Server",
    "build_scenario",
    "render_frame",
    "render_progressive",
    "render_scenario",
]
