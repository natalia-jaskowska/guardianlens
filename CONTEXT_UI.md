# GuardianLens — CONTEXT_UI.md
# UI/UX Design Specifications for Claude Code
# Read this alongside CONTEXT.md before building any UI components.

---

## DESIGN PHILOSOPHY

**This is NOT a hackathon prototype. This must look like a real product.**

Judges associate visual polish with product maturity. A micro-animation on a button, a smooth color transition on an alert, consistent spacing — these small details make judges think "this team knows what they're doing" even if the underlying code is simple.

**Design principles:**
1. **Dark theme** — security/monitoring tools are always dark. It conveys seriousness and professionalism.
2. **Status-driven color** — green/yellow/red map to safe/caution/alert instantly. No learning curve.
3. **Information hierarchy** — most important info is largest and highest on screen.
4. **Micro-animations** — pulsing dots, smooth transitions, loading states. Quick to implement, massive visual impact.
5. **One "wow" moment** — when an alert triggers, the entire dashboard atmosphere shifts. This is what judges remember.

---

## COLOR SYSTEM

```css
/* Base */
--bg-primary: #0f1117;        /* Main background */
--bg-secondary: #1a1d27;      /* Cards, panels */
--bg-tertiary: #12141c;       /* Side panels */
--border: rgba(255,255,255,0.08);  /* Subtle borders */

/* Text */
--text-primary: #e2e8f0;      /* Main text */
--text-secondary: #94a3b8;    /* Descriptions, labels */
--text-muted: #64748b;        /* Timestamps, hints */
--text-dim: #475569;          /* Least important text */

/* Status colors — the core visual language */
--safe: #22c55e;              /* Green — everything OK */
--safe-bg: rgba(34,197,94,0.08);
--safe-border: rgba(34,197,94,0.2);

--caution: #eab308;           /* Yellow — watch this */
--caution-bg: rgba(234,179,8,0.08);
--caution-border: rgba(234,179,8,0.2);

--alert: #ef4444;             /* Red — danger detected */
--alert-bg: rgba(239,68,68,0.08);
--alert-border: rgba(239,68,68,0.2);
--alert-text: #fca5a5;        /* Light red for text on dark bg */

--info: #2563eb;              /* Blue — informational, brand */
--info-bg: rgba(37,99,235,0.08);
--info-border: rgba(37,99,235,0.2);
--info-text: #93c5fd;         /* Light blue for text */

/* Accent */
--brand: #2563eb;             /* GuardianLens brand blue */
```

### Color rules:
- Status dots: solid color, 8px diameter, border-radius 50%
- Status badges: colored text on transparent bg with colored border
- Alert cards: colored bg (0.08 opacity) + colored border (0.2 opacity)
- NEVER use bright colors on large surfaces — always low opacity backgrounds
- Text on colored backgrounds: use the light variant (--alert-text not --alert)

---

## TYPOGRAPHY

```css
/* Font stack — use system fonts for speed, monospace for data */
--font-main: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
--font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;

/* Scale */
--text-xs: 10px;    /* Grooming stage labels, least important */
--text-sm: 11px;    /* Timestamps, badges, uppercase labels */
--text-base: 13px;  /* Body text, descriptions */
--text-md: 14px;    /* Timeline entries */
--text-lg: 15px;    /* Section headers, names */
--text-xl: 22px;    /* Metric numbers */
--text-2xl: 28px;   /* Hero stats in video intro */

/* Weights */
--weight-normal: 400;
--weight-medium: 500;  /* Use for headings and emphasis only */
```

### Typography rules:
- Timestamps and data values: ALWAYS monospace font
- Section labels: uppercase, letter-spacing 1-1.5px, text-sm, text-muted color
- Metric numbers: text-xl, weight-medium, status color
- Body descriptions: text-base, text-secondary color
- NEVER use bold (700) — medium (500) is the heaviest weight

---

## LAYOUT

### Dashboard structure (main screen):

```
+------------------------------------------------------+
|  HEADER BAR (48px height)                            |
|  [Logo] GuardianLens    o Monitoring active   14m 32s|
+--------------------------------------+---------------+
|  MAIN AREA (left 65%)                | SIDE PANEL    |
|                                      | (right 35%)   |
|  +------++------++------++------+    |               |
|  |Stats ||Stats ||Stats ||Stats |    | Threat        |
|  |Card  ||Card  ||Card  ||Card  |    | Analysis      |
|  +------++------++------++------+    |               |
|                                      | Grooming      |
|  LIVE TIMELINE                       | Stage Bar     |
|  +----------------------------+      |               |
|  | 14:32  o Safe  Normal...  |      | AI Reasoning  |
|  | 14:17  o Safe  Trading... |      | (monospace    |
|  | 14:02  o Caution Age...   |      |  thinking     |
|  | 13:47  * ALERT Grooming.. |      |  chain)       |
|  | 13:32  o Caution Gifts... |      |               |
|  | 13:17  o Safe  Started... |      | Parent Alert  |
|  +----------------------------+      | Preview       |
|                                      |               |
+--------------------------------------+---------------+
|  FOOTER (optional): Gemma 4 26B via Ollama | Local   |
+------------------------------------------------------+
```

### Spacing system:
```css
--space-xs: 4px;
--space-sm: 8px;
--space-md: 12px;
--space-lg: 16px;
--space-xl: 20px;
--space-2xl: 24px;
```

### Border radius:
```css
--radius-sm: 4px;    /* Badges, small pills */
--radius-md: 8px;    /* Cards, inputs */
--radius-lg: 10px;   /* Panels, modals */
--radius-xl: 16px;   /* Outer container */
```

---

## COMPONENTS

### 1. Header bar
```
Height: 48px
Background: --bg-primary
Border-bottom: 0.5px solid --border
Padding: 0 20px
Layout: flex, space-between, align-center

Left side:
  - Logo icon (28x28px, border-radius 8px, --brand background, white SVG icon inside)
  - "GuardianLens" text (text-lg, weight-medium, text-primary)

Right side:
  - Pulsing green dot (8px) + "Monitoring active" (text-sm, text-secondary)
  - Session duration (text-sm, text-dim, monospace)
  - Model info (text-sm, text-dim): "Gemma 4 26B via Ollama"
```

### 2. Metric cards (top row)
```
Layout: grid, 4 columns, gap 12px
Background: --bg-secondary
Border-radius: --radius-md
Padding: 12px

Each card:
  - Label: text-xs, text-muted, uppercase, letter-spacing 1px
  - Value: text-xl, weight-medium, status color
    - "Screenshots": text-primary color
    - "Safe": --safe color
    - "Caution": --caution color
    - "Alerts": --alert color
```

### 3. Timeline entries
```
Layout: vertical stack, gap 6px
Each entry is a row:
  Background: --bg-secondary
  Border-radius: --radius-md
  Padding: 8px 12px
  Layout: flex, align-center, gap 10px

  Elements:
  - Status dot (8px circle, status color)
  - Timestamp (monospace, text-sm, text-dim, min-width 48px)
  - Description (text-base, text-secondary for safe / status color for warnings)
  - Status label (text-xs, status color, margin-left auto)

ALERT entries are different:
  Background: --alert-bg
  Border: 0.5px solid --alert-border
  Status label: weight-medium, uppercase
```

### 4. Threat analysis panel (right side)
```
Background: --bg-tertiary
Padding: 16px

Contains:
a) Threat card:
   Background: --alert-bg
   Border: 0.5px solid --alert-border
   Border-radius: --radius-lg
   Padding: 14px

   - Header: "GROOMING DETECTED" (text-xs, --alert-text, uppercase, letter-spacing 1.5px)
   - Confidence: "89%" (text-xl, --alert, weight-medium) — aligned right
   - User info: "User: CoolGuy99 targeting Player123" (text-sm, text-secondary)
   - Indicator badges: flex wrap, gap 6px
     Each badge: text-xs, padding 3px 8px, border-radius 4px, --alert-bg, --alert-text

b) Grooming stage progress bar:
   Layout: flex, 5 equal segments, gap 4px
   Each segment: height 4px, border-radius 2px
   Active stages: --alert color
   Current stage: --alert with opacity 0.6
   Inactive stages: #334155
   Labels below: text-xs, text-dim (active label: --alert-text, weight-medium)

c) AI reasoning block:
   Background: --bg-secondary
   Border-radius: --radius-md
   Padding: 12px
   Font: monospace, text-sm, line-height 1.7
   Color: text-secondary

   Prefix "THINKING:" in text-dim
   Evidence lines in text-primary
   Flagged items in --alert-text
   Final "VERDICT:" line in --alert, weight-medium

d) Parent alert preview:
   Background: --info-bg
   Border: 0.5px solid --info-border
   Border-radius: --radius-md
   Padding: 12px

   Label: "PARENT ALERT SENT" (text-xs, --info-text, uppercase)
   Summary text: text-sm, text-primary, line-height 1.5
```

### 5. Status dot animation
```css
@keyframes pulse-safe {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@keyframes pulse-alert {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.4); }
  50% { box-shadow: 0 0 0 6px rgba(239,68,68,0); }
}

/* Safe: gentle opacity pulse */
.dot-safe { animation: pulse-safe 2s infinite; }

/* Alert: expanding ring pulse — draws attention */
.dot-alert { animation: pulse-alert 1.5s infinite; }
```

---

## MICRO-ANIMATIONS (quick to implement, massive visual impact)

### 1. Alert appearance
When a new alert appears in the timeline:
```css
@keyframes slide-in-alert {
  from {
    opacity: 0;
    transform: translateX(-20px);
    background: rgba(239,68,68,0.2);
  }
  to {
    opacity: 1;
    transform: translateX(0);
    background: rgba(239,68,68,0.08);
  }
}
.new-alert { animation: slide-in-alert 0.5s ease-out; }
```

### 2. Confidence counter
When threat analysis appears, the confidence number counts up:
```javascript
// Count from 0 to 89 over 1 second
function animateConfidence(element, target) {
  let current = 0;
  const step = target / 30;
  const interval = setInterval(() => {
    current += step;
    if (current >= target) {
      current = target;
      clearInterval(interval);
    }
    element.textContent = Math.round(current) + '%';
  }, 33);
}
```

### 3. Grooming stage bar fill
Stages fill in one by one with 200ms delay:
```css
.stage-segment {
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.3s ease-out;
}
.stage-segment.active {
  transform: scaleX(1);
}
/* Apply with JS: add 'active' class with 200ms stagger */
```

### 4. Status transition
When status changes from safe to caution to alert:
```css
.timeline-entry {
  transition: background-color 0.3s ease, border-color 0.3s ease;
}
```

### 5. Loading state during analysis
While Gemma 4 is processing a screenshot:
```css
@keyframes analyzing {
  0% { opacity: 0.3; }
  50% { opacity: 1; }
  100% { opacity: 0.3; }
}
.analyzing-indicator {
  animation: analyzing 1.5s infinite;
  color: var(--info-text);
}
/* Show: "Analyzing screenshot..." with this animation */
```

---

## THE "WOW" MOMENT

When an ALERT triggers (not caution — only alert/critical), the entire dashboard shifts atmosphere:

```css
/* Normal state */
.dashboard {
  background: #0f1117;
  transition: all 0.5s ease;
}

/* Alert state — subtle but noticeable */
.dashboard.alert-active {
  background: #110f14;  /* Slightly warmer/redder */
  border: 1px solid rgba(239,68,68,0.1);  /* Faint red border on whole dashboard */
}

/* Header gets a red accent line */
.header.alert-active {
  border-bottom-color: rgba(239,68,68,0.3);
}

/* The alert timeline entry gets a persistent glow */
.alert-entry {
  box-shadow: 0 0 20px rgba(239,68,68,0.1);
}
```

This subtle shift — the whole screen feels slightly "redder" — is subconscious. Judges won't articulate why the demo feels intense at that moment, but they'll feel it.

---

## PARENT PHONE NOTIFICATION DESIGN

For the video, you need to show a parent receiving an alert on their phone. Two options:

### Option A: Real email (recommended — most authentic)
Send yourself an actual email when alert triggers. Film your phone receiving it. Use HTML email template:

```
Subject: GuardianLens Alert: Suspicious contact detected

Body:
- GuardianLens logo
- Red banner: "Safety Alert"
- "Suspicious contact detected during Instagram session"
- Summary (2-3 sentences, no raw chat content)
- Indicator badges
- "Recommended action" section
- Footer: "All analysis performed on-device"
```

### Option B: HTML mockup on phone
Open a local HTML page on your phone that looks like a notification card. Use the design from the phone mockup shown earlier.

**Option A is better for the video** because it's real. Judge sees a real phone with a real notification arriving in real-time. No mockup.

---

## IMPLEMENTATION APPROACH

### DO NOT build a completely custom frontend from scratch.

Use **Gradio with heavy custom CSS** or **Gradio Blocks with HTML components**. Gradio gives you:
- WebSocket updates (live dashboard)
- File upload (screenshots)
- Easy Python integration with Ollama
- `share=True` for public demo link

### Gradio custom theme approach:
```python
import gradio as gr

# Custom dark theme
theme = gr.themes.Base(
    primary_hue=gr.themes.colors.blue,
    neutral_hue=gr.themes.colors.slate,
).set(
    body_background_fill="#0f1117",
    block_background_fill="#1a1d27",
    block_border_color="rgba(255,255,255,0.08)",
    block_label_text_color="#64748b",
    body_text_color="#e2e8f0",
    body_text_color_subdued="#94a3b8",
)

# Use gr.HTML() blocks for custom-designed components
# Use gr.Dataframe() or gr.JSON() for timeline data
# Use gr.Image() for current screenshot display
```

### Alternative: FastAPI + custom HTML
If Gradio is too limiting for the design:
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def dashboard():
    return HTMLResponse(open("templates/dashboard.html").read())

@app.websocket("/ws")
async def websocket_endpoint(websocket):
    # Stream live analysis results to dashboard
    pass
```

This gives you full control over HTML/CSS/JS but requires more work.

### Recommendation:
**Start with Gradio + custom CSS.** If it looks too "Gradio-ish" after week 3, consider switching to FastAPI + custom HTML in week 4. The dashboard design is a week 4 task — don't start with it.

---

## VIDEO-SPECIFIC UI CONSIDERATIONS

### Font sizes for screen recording:
Screen recordings compress quality. Everything must be readable at 1080p YouTube playback.
- Minimum font size on screen: 13px (anything smaller is unreadable in video)
- Status badges: 12px minimum
- Timestamps: 13px monospace
- Metric numbers: 24px+ (visible even on phone playback)

### Contrast for video:
- Dark backgrounds need sufficient contrast — never put #475569 text on #1a1d27 bg in video
- Status colors should be vivid enough to read on compressed video
- Test: take a screenshot of your dashboard, compress it to 720p, can you still read everything?

### Split-screen recording layout:
When recording demo with OBS:
```
+----------------------+------------------+
|                      |                  |
|  Browser window      |  GuardianLens    |
|  (Instagram/TikTok)  |  Dashboard       |
|                      |                  |
|  60% width           |  40% width       |
|                      |                  |
+----------------------+------------------+
```
- Browser window: full height, showing the "child's screen"
- Dashboard: full height, showing live analysis
- No gap between them — seamless split

### Recording resolution:
- Record at 1920x1080 minimum
- Dashboard should fill its portion completely (no wasted space)
- Use OBS "Scene" with two "Window Capture" sources side by side

---

## WHAT NOT TO DO

1. **No default Gradio styling** — judges see 100+ Gradio apps, yours must look different
2. **No white/light theme** — security tools are dark, always
3. **No generic loading spinners** — use the pulsing dot animation specific to GuardianLens
4. **No walls of text** — the AI reasoning panel is the ONLY place for long text, and it's in monospace
5. **No bright colored backgrounds** — only low-opacity colored backgrounds (0.08 alpha)
6. **No random icons or decorations** — every visual element must convey information
7. **No scroll-heavy layouts** — everything critical must be visible without scrolling
8. **No mobile-responsive design needed** — this runs on a desktop monitor, optimize for 1920x1080
