# GuardianLens — CONTEXT v4 (FINAL)
# This file supersedes ALL previous versions: CONTEXT.md, CONTEXT_v2, CONTEXT_v3, 
# BACKEND_ARCHITECTURE.md, DUAL_MODE_ARCHITECTURE.md, UI_FIXES.md, CONTEXT_UI.md
# Read this ENTIRE file before starting any work.

---

## COMPETITION

**Gemma 4 Good Hackathon** — Kaggle × Google DeepMind
- Prize pool: $200,000. Deadline: May 18, 2026
- Targets: Safety & Trust ($10K) + Ollama ($10K) + Unsloth ($10K) = $30K max

**Evaluation:**
- Impact & Vision: 40pts — "Does it address a real problem? Is the vision inspiring?"
- Video Storytelling: 30pts — "Is the video exciting and well-produced?"
- Technical Depth: 30pts — "Is the technology real, functional, verified via code?"
- Video is "the star of the show." Judges verify code but score the STORY.

---

## PROJECT

**GuardianLens** — On-device AI child safety monitor.
Gemma 4 vision captures screenshots every 5-15 seconds, understands what's on the child's screen, detects grooming/bullying/inappropriate content with explainable reasoning, alerts parent via Telegram. Runs 100% locally via Ollama. Zero cloud dependency. Children's private conversations never leave the computer.

**Pitch:** "Family Link counts minutes. GuardianLens understands what's happening."

---

## CORE ARCHITECTURE DECISION: CONVERSATION-CENTRIC (not frame-centric)

### What changed from current version:

**CURRENT (frame-centric):** Every 5 seconds → screenshot → Gemma 4 vision → per-frame result → timeline shows 120 individual "Discord — SAFE" / "Discord — CAUTION" entries. Parent scrolls through hundreds of frame-level results.

**NEW (conversation-centric):** Frames are INVISIBLE data collection. The parent sees CONVERSATIONS grouped by participant and ENVIRONMENTS grouped by platform. The timeline of raw frames is hidden — it's just the input pipeline.

### Why this is better:
- Grooming is a CONVERSATION across 20+ messages, not a single frame
- A parent needs to see "lily_summer talked to your child for 8 minutes and it escalated" — not 96 individual frame analyses
- If child leaves a conversation and comes back, the context RESUMES
- No competitor does conversation-level analysis — they all do per-message keyword matching

---

## TWO DETECTION MODES

### Mode 1: CONVERSATIONS (tracked by participant)
**Circle avatar in UI = a PERSON talking to the child**

Triggered by: Instagram DM, Discord DM, Snapchat chat, WhatsApp — any 1-to-1 or small group direct messaging.

Tracks: one specific user's behavior across all frames where they appear. Accumulates messages, detects escalation, tracks grooming stage progression. If child leaves and comes back to same person, context resumes.

Data model:
```python
class ConversationContext:
    participant: str          # "lily_summer"
    platform: str             # "instagram_dm"
    source: str               # "direct" or "promoted_from_minecraft"
    messages: list            # accumulated across ALL frames
    first_seen: datetime
    last_seen: datetime
    threat_level: str         # evolves: safe → caution → warning → alert
    category: str             # grooming / bullying / scam / none
    grooming_stage: int       # 1-5, progresses across messages
    indicators: list          # accumulates: ["age inquiry", "isolation", "secrecy"]
    confidence: float         # 0-100
    alert_sent: bool
    telegram_delivered: bool
    telegram_read: bool
```

### Mode 2: ENVIRONMENTS (monitored by content)
**Square icon in UI = a PLACE the child is visiting**

Triggered by: Minecraft server chat, TikTok feed, YouTube video, Discord #general channel, Instagram feed, any website — multi-user or passive spaces with no single interlocutor.

Tracks: overall content safety of the environment. Not one person, but the SPACE.

Data model:
```python
class EnvironmentContext:
    platform: str             # "minecraft"
    context: str              # "survival_server" or "tiktok_feed"
    content_type: str         # "in_game_chat" | "video_feed" | "social_feed" | "website"
    first_seen: datetime
    last_seen: datetime
    duration_minutes: int
    user_count: int           # visible users in chat environments
    overall_safety: str       # safe / caution / warning / alert
    content_summary: str      # AI narrative of what's happening
    promoted_users: list      # users promoted to conversation tracking
    indicators: list
```

### PROMOTION mechanism (environment → conversation):
When someone in a public environment (e.g., Minecraft server chat) specifically targets the child — asking age, offering to move to private platform, requesting personal info — the system PROMOTES that user from an environment observation to a tracked conversation.

Example: CoolGuy99 says "how old r u? add me on discord" in Minecraft public chat → system detects targeting → creates a ConversationContext for CoolGuy99 with source="promoted_from_minecraft". The environment card shows "1 user promoted to tracking."

### Content classifier:
```python
class ContentClassifier:
    """First step after frame analysis: CONVERSATION or ENVIRONMENT?"""
    
    def classify(self, frame_analysis) -> ContentType:
        if frame_analysis.is_direct_message:  # Instagram DM, Discord DM
            return ContentType.CONVERSATION
        elif frame_analysis.is_group_chat:     # Discord #channel, Minecraft chat
            return ContentType.ENVIRONMENT     # but users can be promoted
        elif frame_analysis.is_passive_feed:   # TikTok, YouTube, Instagram feed
            return ContentType.ENVIRONMENT
        else:
            return ContentType.ENVIRONMENT     # default: monitor the space
```

---

## PIPELINE (per-frame, every 5 seconds)

```
FRAME CAPTURE (invisible to parent)
    │
    ▼
STAGE 1: PER-FRAME VISION (Gemma 4 via Ollama)
    Input: screenshot image
    Output: ScreenAnalysis
      - platform, content_type (DM vs public chat vs feed)
      - extracted_messages: [{sender, text, timestamp}]
      - extracted_users: list of visible usernames
      - threat_level, category, confidence
      - indicators_found
      - grooming_stage (if applicable)
      - inference_seconds
    ⚡ Privacy: screenshot DELETED immediately after analysis
    │
    ▼
STAGE 2: CONTENT ROUTING
    ContentClassifier determines: CONVERSATION or ENVIRONMENT?
    │
    ├─► CONVERSATION path:
    │   ConversationStore groups messages by (platform, participant)
    │   Deduplicates by (sender, text.lower())
    │   Accumulates across frames — conversation grows over time
    │   When new messages: trigger ConversationAnalyzer (text-only Gemma 4)
    │     Input: full accumulated conversation for this participant
    │     Output: SessionVerdict (overall_level, narrative, key_indicators, grooming_stage)
    │
    └─► ENVIRONMENT path:
        EnvironmentMonitor tracks (platform, context) as a space
        Updates overall_safety based on content
        Checks for TARGETING — is someone specifically addressing the child?
        If targeting detected → PROMOTE user to ConversationStore
    │
    ▼
STAGE 3: ESCALATION + ALERTS
    EscalationTracker: cross-frame pattern detection
      - Same user, increasing severity, indicator accumulation
      - Measures escalation_speed
    
    AlertGate: monotonic high-water dedup per category
      - Only strict escalations fire alerts
      - Prevents spam from noisy single frames
    
    ⚡ Privacy: PrivacyGuard.sanitize_for_parent()
      - Strips raw chat text
      - Strips child identity  
      - Keeps only: threat type, confidence, indicators, recommended action
    
    If alert fires → TelegramAlert.send_alert(sanitized_alert)
    │
    ▼
STAGE 4: STORAGE + DASHBOARD
    SQLite: stores sanitized analysis metadata (never raw text, never screenshots)
    SSE: pushes live updates to dashboard
    Dashboard: shows conversations + environments (never raw frames)
```

---

## PRIVACY BY DESIGN (6 decisions — document in writeup)

| # | Decision | Implementation | Why |
|---|----------|---------------|-----|
| 1 | Screenshots deleted after analysis | `PrivacyGuard.delete_screenshot(path)` immediately after Stage 1 | No visual history accumulates on disk |
| 2 | Raw chat text never stored | SQLite contains indicator LABELS only ("age inquiry", "isolation") not verbatim messages | Parent cannot read child's conversations |
| 3 | Parent alerts = AI summary only | Telegram says "grooming detected, 4 indicators, stage 4/5" — never "user said: how old are you" | Child's conversational privacy preserved |
| 4 | Zero cloud dependency | Ollama runs locally, NetworkGuard verifies on startup | Data physically cannot leave device |
| 5 | No user accounts or cloud sync | No login, no server, no data sharing | Eliminates data breach risk |
| 6 | Child identity anonymized | DB stores "child" not actual username | If DB accessed, child unidentifiable |

```python
# privacy.py — this module is implemented FIRST (not last)

class PrivacyGuard:
    @staticmethod
    def sanitize_for_parent(analysis) -> ParentAlert:
        """AI summary only. Never raw chat text. Never child's username."""
        return ParentAlert(
            threat_type=analysis.category,
            confidence=analysis.confidence,
            platform=analysis.platform,
            indicator_summary=analysis.indicators,  # labels, not quotes
            recommended_action=generate_action(analysis),
            # NEVER: raw_text, child_username, screenshot_path
        )
    
    @staticmethod
    def sanitize_for_storage(analysis) -> dict:
        """Metadata only for dashboard display."""
        return {
            "timestamp": analysis.timestamp,
            "platform": analysis.platform,
            "threat_level": analysis.threat_level,
            "category": analysis.category,
            "confidence": analysis.confidence,
            "indicators": analysis.indicators,  # labels only
            "grooming_stage": analysis.grooming_stage,
            # NO screenshot_path, NO raw_text
        }
    
    @staticmethod
    def delete_screenshot(path: str):
        """Delete immediately after analysis. Never accumulate."""
        os.remove(path)

class NetworkGuard:
    @staticmethod
    def verify_no_egress() -> dict:
        """Confirms Ollama local, zero external connections. Shown in UI."""
        return {"ollama_local": True, "bytes_to_cloud": 0}
```

---

## UI DESIGN

### Layout: two columns
- Left (65%): live capture + stats + conversation/environment cards
- Right (35%): detail panel (changes based on selection)

### Left panel (top to bottom):

1. **Live capture** — large screenshot with status bar BELOW (not beside)
   - Green border + "All clear" when safe
   - Red border + "Grooming detected — 98%" when alert
   - Status bar shows: icon + status text + description + timestamp
   
2. **Stats row** — 4 boxes: scans, conversations, environments, alerts

3. **Conversations section** — "tracked by participant"
   - Each card: circle avatar + username + platform icon + confidence% + one-line AI summary + indicator pills + message count + duration
   - Red border-left = alert, yellow = flagged, green = safe
   - "Promoted from environment" label on promoted users
   - Safe conversations collapsed into "3 safe conversations" row
   - Click any card → right panel shows conversation detail

4. **Environments section** — "monitored by content"  
   - Each card: square platform icon + environment name + safety + duration + user count
   - Same color coding: red/yellow/green border-left
   - Click → right panel shows environment detail

5. **Privacy badge** at bottom — lock icon + "Fully local" + "Private" pill

### Right panel — 3 states:

**State 1: All conversations (default)**
- Header: "All conversations" with filter pills (2 alerts, 1 flagged, 3 safe)
- Grouped by severity: Alerts → Flagged → Safe
- Each card shows: avatar, username, platform, AI narrative, indicator pills, grooming stage bar, Telegram delivery status
- Click any card → State 2

**State 2: Conversation detail (after clicking a conversation)**
- "← All conversations" back button
- User header: avatar + name + platform + message count + duration
- Threat summary card: category + confidence + grooming stage bar
- **Conversation arc** — timeline showing each message with colored dots:
  - Green dot: safe message
  - Yellow dot: concerning message (with indicator label)
  - Red dot: dangerous message (with indicator label)
  - Shows escalation visually: green → yellow → red over time
- Recommended action: purple card, numbered steps 1-2-3
- Telegram delivery status: compact blue card
- Privacy badge

**State 3: Environment detail (after clicking an environment)**
- Similar to conversation detail but shows:
  - Environment summary (platform, user count, duration)
  - Content safety assessment
  - Promoted users list (if any)
  - Indicators found in the environment

### Navigation:
```
Left panel card click → Right panel shows detail
Right panel "← All conversations" → back to list
New alert detected → auto-show conversation detail
New safe scan after alert → back to list
```

### Visual distinction:
- Circle avatar = PERSON (conversation)
- Square icon = PLACE (environment)
- Parent instantly sees the difference

### Color system:
- Safe: #22c55e (green), rgba tint backgrounds
- Caution: #eab308 (yellow)
- Warning: #ef4444 (red, lower intensity)
- Alert: #ef4444 (red, full intensity)
- Purple: #8b5cf6 (recommended actions)
- Blue: #2563eb (Telegram, brand)
- Background: #0c0e14, panels: #0a0c12, cards: #141720

---

## TELEGRAM ALERTS

Real push notifications to parent's phone. Must work for video demo.

```python
class TelegramAlert:
    """Privacy-safe alerts. NEVER raw chat text."""
    
    async def send_alert(self, alert: ParentAlert):
        text = (
            f"🔴 *GuardianLens Alert*\n\n"
            f"*{alert.threat_type}* detected on {alert.platform}\n"
            f"Confidence: {alert.confidence}%\n"
            f"Indicators: {', '.join(alert.indicators)}\n\n"
            f"*Recommended:*\n{alert.recommended_action}\n\n"
            f"_No chat content shared. AI analysis only._"
        )
        await self._send(text)
```

Setup: @BotFather → create bot → get token → set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.

---

## DEMO SCENARIO MODE

For reproducible video recording. Pre-prepared screenshots fed at controlled intervals.

```python
class DemoScenario:
    """Feeds pre-prepared screenshots instead of live capture."""
    
    def __init__(self, scenario_dir: str):
        self.screenshots = sorted(Path(scenario_dir).glob("*.png"))
    
    async def next_frame(self) -> str:
        # Return next screenshot path, used instead of mss capture
```

Scenarios directory:
```
scenarios/
  grooming_instagram/
    01_instagram_feed.png        # safe
    02_instagram_feed_2.png      # safe
    03_instagram_dm_hello.png    # safe — new conversation starts
    04_instagram_dm_age.png      # caution — asks age
    05_instagram_dm_school.png   # warning — asks school
    06_instagram_dm_photo.png    # alert — requests photo + secrecy
  
  minecraft_grooming/
    01_minecraft_gameplay.png    # safe — environment
    02_minecraft_chat_safe.png   # safe — normal game chat
    03_minecraft_chat_target.png # caution — CoolGuy99 asks "how old"
    04_minecraft_chat_isolate.png # alert — "add me on discord, private"
```

Create screenshots by: opening real platform in browser → editing text with DevTools → screenshot. NOT fake mockups — use real platform UI.

Run: `python run.py --demo scenarios/grooming_instagram/`

---

## FILE STRUCTURE

```
guardlens/
├── src/
│   ├── capture.py              # mss screen capture + DemoScenario
│   ├── analyzer.py             # Stage 1: per-frame Gemma 4 vision call
│   ├── classifier.py           # ContentClassifier: conversation vs environment
│   ├── conversation.py         # ConversationStore + ConversationAnalyzer
│   ├── environment.py          # EnvironmentMonitor + targeting detection
│   ├── escalation.py           # EscalationTracker — cross-frame patterns
│   ├── alerts.py               # AlertGate + TelegramAlert
│   ├── privacy.py              # PrivacyGuard + NetworkGuard
│   ├── database.py             # SQLite schema + queries
│   ├── pipeline.py             # Orchestrates everything: capture → analyze → route → alert
│   └── models.py               # Pydantic: ScreenAnalysis, ConversationContext, 
│                                #   EnvironmentContext, SessionVerdict, ParentAlert
│
├── app/
│   ├── main.py                 # FastAPI app + SSE endpoint
│   ├── static/
│   │   ├── dashboard.js
│   │   └── styles.css
│   └── templates/
│       └── dashboard.html
│
├── scenarios/                  # Pre-prepared demo screenshots
│   ├── grooming_instagram/
│   └── minecraft_grooming/
│
├── notebooks/
│   ├── 01_prepare_data.ipynb   # Kaggle — PAN12 + synthetic data
│   ├── 02_finetune.ipynb       # Kaggle — Unsloth QLoRA
│   └── 03_evaluate.ipynb       # Kaggle — baseline vs fine-tuned
│
├── models/
│   └── Modelfile               # Ollama deployment config
│
├── run.py                      # python run.py [--demo scenarios/grooming/]
├── CONTEXT.md                  # This file
├── README.md
└── requirements.txt
```

---

## REFACTORING FROM CURRENT VERSION

### What to KEEP from current codebase:
- Gemma 4 inference via Ollama — working, keep it
- Screen capture via mss — working, keep it  
- SQLite database — keep the schema, extend it
- FastAPI + SSE — keep, it works
- Custom HTML/CSS/JS dashboard — keep the tech, redesign the layout
- Per-frame analysis logic — keep as Stage 1, but don't display raw frames

### What to ADD:
1. `classifier.py` — route each frame to conversation or environment path
2. `conversation.py` — ConversationStore that accumulates messages by participant + ConversationAnalyzer that runs text-only Gemma 4 on full conversations
3. `environment.py` — EnvironmentMonitor + targeting detection + promotion
4. `escalation.py` — EscalationTracker for cross-frame pattern detection
5. `privacy.py` — PrivacyGuard + NetworkGuard as enforced modules (not footer text)
6. `alerts.py` — real Telegram bot integration
7. `capture.py` — add DemoScenario mode alongside live mss capture
8. Dashboard: redesign from frame-list to conversation-list + environment-list

### What to CHANGE:
- Timeline: from individual frame entries to conversation cards + environment cards
- Right panel: from "conversation verdict per frame" to "conversation detail with arc timeline"
- Stats: from "scans/safe/caution/alerts" to "scans/conversations/environments/alerts"
- Alert system: from in-dashboard-only to real Telegram push notifications
- Storage: add conversation-level and environment-level tables alongside frame-level

### What to REMOVE:
- Per-frame timeline entries visible to parent (hide these, they're internal pipeline data)
- "CONVERSATION VERDICT" showing per-frame analysis (replace with conversation-level analysis)
- Raw screenshot display in alert detail (show AI summary instead)

---

## IMPLEMENTATION ORDER

1. **models.py** — define all Pydantic models first
2. **privacy.py** — PrivacyGuard + NetworkGuard (privacy is foundational)
3. **classifier.py** — ContentClassifier routing logic
4. **conversation.py** — ConversationStore + ConversationAnalyzer
5. **environment.py** — EnvironmentMonitor + targeting + promotion
6. **escalation.py** — EscalationTracker
7. **alerts.py** — AlertGate + TelegramAlert
8. **pipeline.py** — orchestrate capture → analyze → route → escalate → alert → store
9. **capture.py** — add DemoScenario mode
10. **database.py** — extend schema for conversations + environments
11. **Dashboard redesign** — conversation cards + environment cards + detail views
12. **Create demo scenarios** — Instagram grooming + Minecraft grooming screenshots
13. **Fine-tune** — Unsloth QLoRA on Kaggle T4
14. **Record video** — using demo mode for reproducible footage

---

## VIDEO SCRIPT ALIGNMENT

The 2-minute video (see VIDEO_SCRIPT.md) requires these specific moments from the app:

| Video moment | What app must show |
|---|---|
| 0:35-0:42 safe browsing | Conversation list empty or all green. Environments: "Minecraft — safe" |
| 0:42-0:48 new DM opens | New conversation card appears: lily_summer, Instagram DM, SAFE |
| 0:48-0:55 escalation | lily_summer card changes: SAFE → CAUTION → WARNING. Indicators accumulate |
| 0:55-1:05 alert fires | lily_summer card turns red: ALERT 98%. Right panel shows conversation arc with escalation |
| 1:05-1:12 phone buzzes | Real Telegram notification arrives on real phone |
| 1:12-1:20 click through | Right panel: conversation arc + recommended action + Telegram status |
| 1:25-1:30 airplane mode | Toggle wifi off. System keeps working. NetworkGuard still passes |

The conversation-centric UI makes the video demo MUCH clearer — judge sees "lily_summer: 15 messages, grooming stage 4/5, alert sent" instead of scrolling through 96 frame entries.
