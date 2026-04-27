"""Draw the GuardianLens architecture as a polished PNG.

Output: /home/natjas/guardianlens/docs/architecture.png

Style: Claude.ai-style cream background, soft rounded boxes, restrained
palette (slate + amber + rust accents), clean sans-serif typography.
No external Python deps beyond Pillow.
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# ---------- canvas ----------
W, H = 1800, 1280
BG = (250, 248, 243)            # warm cream
INK = (24, 24, 27)
DIM = (96, 96, 105)
ACCENT_AMBER = (180, 83, 9)     # Claude amber
ACCENT_RUST = (185, 28, 28)
ACCENT_TEAL = (15, 118, 110)
ACCENT_INDIGO = (49, 46, 129)
SHADOW = (0, 0, 0, 16)
BORDER = (212, 209, 200)

img = Image.new("RGB", (W, H), BG)
shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
shadow_draw = ImageDraw.Draw(shadow_layer)
draw = ImageDraw.Draw(img)


# ---------- fonts ----------
FONT_REG = "/usr/share/fonts/gnu-free/FreeSans.otf"
FONT_BLD = "/usr/share/fonts/gnu-free/FreeSansBold.otf"
FONT_MONO = "/usr/share/fonts/gnu-free/FreeMono.otf"


def F(size, bold=False, mono=False):
    return ImageFont.truetype(FONT_MONO if mono else (FONT_BLD if bold else FONT_REG), size)


# ---------- helpers ----------
def box(x, y, w, h, fill=None, border=BORDER, border_w=1, radius=14, shadow=True):
    if shadow:
        shadow_draw.rounded_rectangle((x + 4, y + 6, x + w + 4, y + h + 6), radius=radius, fill=(0, 0, 0, 22))
    if fill:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=fill)
    if border:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, outline=border, width=border_w)


def text(x, y, s, font, color=INK, anchor="lt"):
    draw.text((x, y), s, font=font, fill=color, anchor=anchor)


def chip(x, y, label, fill, fg=(255, 255, 255), pad_x=14, pad_y=6, font=None):
    f = font or F(15, bold=True)
    bbox = draw.textbbox((0, 0), label, font=f)
    w = bbox[2] - bbox[0] + pad_x * 2
    h = bbox[3] - bbox[1] + pad_y * 2
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=fill)
    draw.text((x + pad_x, y + pad_y - 2), label, font=f, fill=fg)
    return w, h


def arrow(x1, y1, x2, y2, color=ACCENT_AMBER, width=3, head=14):
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    # arrowhead
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - head * math.cos(angle - math.pi / 7),
          y2 - head * math.sin(angle - math.pi / 7))
    p2 = (x2 - head * math.cos(angle + math.pi / 7),
          y2 - head * math.sin(angle + math.pi / 7))
    draw.polygon([(x2, y2), p1, p2], fill=color)


# ---------- title ----------
text(60, 50, "GuardianLens — Architecture", F(40, bold=True))
text(60, 102, "On-device AI child-safety monitoring with Gemma 4 (via Ollama)",
     F(20), color=DIM)

# Tagline strip
chip(60, 145, "ON-DEVICE", ACCENT_TEAL, pad_x=12, pad_y=5, font=F(13, bold=True))
chip(195, 145, "MULTIMODAL", ACCENT_AMBER, pad_x=12, pad_y=5, font=F(13, bold=True))
chip(345, 145, "EXPLAINABLE", ACCENT_INDIGO, pad_x=12, pad_y=5, font=F(13, bold=True))
chip(495, 145, "ZERO CLOUD", ACCENT_RUST, pad_x=12, pad_y=5, font=F(13, bold=True))


# ---------- LEFT column: Child's Device ----------
LX, LY, LW, LH = 60, 220, 420, 580
box(LX, LY, LW, LH, fill=(255, 255, 255), border=BORDER)

# header
text(LX + 24, LY + 20, "CHILD'S DEVICE", F(13, bold=True), color=ACCENT_TEAL)
text(LX + 24, LY + 42, "Phone · tablet · home laptop", F(15), color=DIM)

# guardlens-client inner
inner_x, inner_y, inner_w = LX + 24, LY + 100, LW - 48
box(inner_x, inner_y, inner_w, 200, fill=(245, 251, 250), border=(167, 213, 207), border_w=2, shadow=False)
text(inner_x + 18, inner_y + 18, "guardlens-client", F(22, bold=True))
text(inner_x + 18, inner_y + 50, "Lightweight background process", F(15), color=DIM)

# bullets inside
text(inner_x + 18, inner_y + 92, "•  mss screen capture", F(17, mono=True))
text(inner_x + 36, inner_y + 116, "1 PNG / second of whatever's on screen", F(14), color=DIM)
text(inner_x + 18, inner_y + 148, "•  httpx sender", F(17, mono=True))
text(inner_x + 36, inner_y + 172, "POSTs each frame to the home server", F(14), color=DIM)

# privacy note
note_y = inner_y + 230
box(inner_x, note_y, inner_w, 110, fill=(252, 247, 234), border=(225, 192, 122), border_w=1, shadow=False)
text(inner_x + 18, note_y + 14, "Privacy by design", F(15, bold=True), color=ACCENT_AMBER)
text(inner_x + 18, note_y + 40,
     "No raw chat text ever leaves the device.", F(14))
text(inner_x + 18, note_y + 60,
     "Pixels go to the home server only, where", F(14))
text(inner_x + 18, note_y + 80,
     "Gemma 4 reads them locally.", F(14))


# ---------- RIGHT column: Home Server ----------
RX, RY, RW, RH = 720, 220, 1020, 720
box(RX, RY, RW, RH, fill=(255, 255, 255), border=BORDER)

# header
text(RX + 24, RY + 20, "PARENT'S HOME SERVER", F(13, bold=True), color=ACCENT_INDIGO)
text(RX + 24, RY + 42, "FastAPI + Ollama running Gemma 4 (~17 GB, T4 / consumer GPU)", F(15), color=DIM)

# 4-step pipeline
STEPS = [
    ("1", "Extract conversations", "Multimodal vision pass — Gemma reads the screenshot and emits a structured list of conversations: platform, participants, every message.",
     ACCENT_AMBER, "VISION"),
    ("2", "Match & merge history", "Deterministic Python: fuzzy-match each new fragment to the right ongoing conversation, dedupe OCR variants, append truly new messages.",
     ACCENT_TEAL, "DETERMINISTIC"),
    ("3", "Update conversation status", "Text pass — Gemma reasons over the full accumulated history, updates threat_level / category / confidence and writes a short reasoning sentence.",
     ACCENT_INDIGO, "REASONING"),
    ("4", "Surface to parent", "If threat_level ≥ warning + certainty ≥ medium, the dashboard fires a toast, the bell badges, and the conversation card jumps to the top.",
     ACCENT_RUST, "ALERT"),
]

step_x = RX + 28
step_y = RY + 100
step_w = RW - 56
step_h = 120
gap = 14

for i, (num, title, body, accent, badge) in enumerate(STEPS):
    y = step_y + i * (step_h + gap)
    box(step_x, y, step_w, step_h, fill=(252, 252, 250), border=BORDER, shadow=False)
    # number circle
    cx, cy, cr = step_x + 36, y + 36, 24
    draw.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=accent)
    draw.text((cx, cy + 2), num, font=F(22, bold=True), fill=(255, 255, 255), anchor="mm")
    # title
    text(step_x + 80, y + 18, title, F(20, bold=True))
    # badge
    chip(step_x + step_w - 130, y + 22, badge, accent, pad_x=10, pad_y=4, font=F(11, bold=True))
    # body
    # simple word wrap
    max_chars = 86
    words = body.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    for li, ln in enumerate(lines[:3]):
        text(step_x + 80, y + 56 + li * 22, ln, F(15), color=DIM)


# ---------- ARROW: client → server ----------
ax, ay = LX + LW + 10, LY + LH // 2 - 30
bx, by = RX - 10, RY + 130
draw.line((ax, ay, ax + 70, ay), fill=ACCENT_AMBER, width=3)
arrow(ax + 70, ay, bx, by, color=ACCENT_AMBER)
# label
mid_x, mid_y = (ax + bx) // 2 - 130, (ay + by) // 2 - 60
chip(mid_x, mid_y, "PNG · 1 Hz · POST /api/frames", ACCENT_AMBER, pad_x=14, pad_y=8, font=F(15, bold=True))


# ---------- bottom: persistence + dashboard ----------
PY = RY + RH + 30
PW_LEFT = (RW - 14) // 2

# SQLite
sql_x, sql_y, sql_w, sql_h = RX, PY, PW_LEFT, 130
box(sql_x, sql_y, sql_w, sql_h, fill=(251, 247, 240), border=(216, 191, 138), border_w=2, shadow=False)
text(sql_x + 22, sql_y + 16, "STATE", F(12, bold=True), color=ACCENT_AMBER)
text(sql_x + 22, sql_y + 34, "SQLite", F(22, bold=True))
text(sql_x + 22, sql_y + 70, "Conversations + classifications persisted after every step. Resilient to restart.",
     F(14), color=DIM)

# Dashboard
dx, dy, dw, dh = RX + PW_LEFT + 14, PY, PW_LEFT, 130
box(dx, dy, dw, dh, fill=(251, 244, 244), border=(218, 154, 154), border_w=2, shadow=False)
text(dx + 22, dy + 16, "PARENT-FACING", F(12, bold=True), color=ACCENT_RUST)
text(dx + 22, dy + 34, "Live dashboard (SSE :7860)", F(22, bold=True))
text(dx + 22, dy + 70, "Activity panel · alert toasts · per-conv AI Reasoning + Recommendations.",
     F(14), color=DIM)


# ---------- footer: Gemma 4 features ----------
FY = H - 80
text(60, FY - 26, "Gemma 4 features used", F(15, bold=True), color=DIM)
features = [
    ("Multimodal vision", ACCENT_AMBER),
    ("Structured / function-calling output", ACCENT_INDIGO),
    ("Explainable reasoning", ACCENT_TEAL),
    ("Local inference via Ollama", ACCENT_RUST),
]
fx = 60
for label, color in features:
    w, _ = chip(fx, FY, label, color, pad_x=18, pad_y=10, font=F(15, bold=True))
    fx += w + 12


# ---------- composite shadow on top ----------
img.paste(shadow_layer, (0, 0), shadow_layer)
img = Image.alpha_composite(img.convert("RGBA"), shadow_layer).convert("RGB")


# ---------- save ----------
out = Path("/home/natjas/guardianlens/docs/architecture.png")
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out, optimize=True)
print(f"saved: {out}  {out.stat().st_size // 1024} KB  ({W}x{H})")
