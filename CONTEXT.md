# GuardianLens — CONTEXT.md (v3 FINAL)

> Context file for Claude Code. Read everything before starting any work.
> This is the single source of truth for the project. Last updated: 2026-04-08.
>
> **Then read [docs/progress.md](docs/progress.md)** — append-only changelog
> with dated entries describing what was built in each session and what
> state the repo is in. Always read the most recent two entries before
> making changes, and append a new entry when you finish a session.

---

## COMPETITION RULES

**Competition:** Gemma 4 Good Hackathon (Kaggle x Google DeepMind)
**Total Prize Pool:** $200,000
**Deadline:** May 18, 2026
**Submission:** Working demo + public code repo + Kaggle writeup + video demo (max 2 min)

### Evaluation Criteria

| Criteria                    | Points | What judges look for                                                          |
|-----------------------------|--------|-------------------------------------------------------------------------------|
| Impact & Vision             | 40     | Real-world problem, inspiring vision, tangible potential for positive change  |
| Video Pitch & Storytelling  | 30     | Exciting, engaging, well-produced video that tells a powerful story           |
| Technical Depth & Execution | 30     | Real, functional, well-engineered code — verified via repo and writeup        |

### Critical rule from judges

> "All projects must be backed by real, functional technology. The accompanying writeup and code repository will be used by our judges to verify that your product is not just a concept but a working proof-of-concept built on Gemma 4."

**This means: build a REAL working system, not a demo mockup. Judges will read your code.**

### Prize Targets (all stackable)

**Main Track:**

- **Safety & Trust ($10,000):** "Pioneer frameworks for transparency and reliability, ensuring AI remains grounded and explainable."

**Special Technology Tracks ($50,000 total):**

| Prize        | Amount  | Requirement                                                                 |
|--------------|---------|-----------------------------------------------------------------------------|
| **Ollama**   | $10,000 | Best project utilizing Gemma 4 running locally via Ollama                   |
| **Unsloth**  | $10,000 | Best fine-tuned Gemma 4 using Unsloth, optimized for specific impactful task |
| **llama.cpp**| $10,000 | Best innovative implementation on resource-constrained hardware             |
| **LiteRT**   | $10,000 | Most compelling use case using Google AI Edge's LiteRT                      |
| **Cactus**   | $10,000 | Best local-first mobile/wearable app routing tasks between models           |

**Our targets: Safety & Trust ($10K) + Ollama ($10K) + Unsloth ($10K) = $30K max exposure**

---

## PROJECT: GuardianLens

### One-line pitch

*"Family Link counts minutes. GuardianLens understands what's happening."*

### What it is

A REAL, WORKING, continuously-running AI child safety monitor. Gemma 4 vision captures and analyzes a child's screen every 15 seconds, detects grooming, cyberbullying, and inappropriate content through contextual reasoning, and alerts the parent. Runs entirely on-device via Ollama — children's private conversations never leave the computer.

### What it is NOT

- Not a single-screenshot analyzer where you manually upload an image
- Not a chatbot wrapper
- Not a prompt-only UI
- Not a concept video with mocked results
- Everything shown in the demo must actually work in the code

---

## WHAT MAKES THIS A "REAL APPLICATION" (not a demo)

Based on recent Google hackathon standards, judges expect working systems, not concepts. GuardianLens must demonstrate:

### 1. Continuous monitoring loop (not one-shot)

The system runs continuously. Every ~15 seconds it captures the screen, analyzes it, and updates the dashboard. The demo video shows it running in real-time over several minutes, not a single manually-triggered analysis.

### 2. Context tracking across time (not stateless)

The system maintains a sliding window of the last N analyses. It detects PATTERNS across time:

- "User asked about age 2 minutes ago -> now offering gifts -> escalation detected"
- "Bullying intensity increasing over last 5 screenshots"

This is what separates it from "just calling an LLM on each screenshot independently."

### 3. Function calling that actually executes (not suggested)

When Gemma 4 calls `classify_threat()` or `generate_parent_alert()`, those functions ACTUALLY RUN:

- Threat classification is stored in a local SQLite database
- Parent alert is actually sent (email or webhook)
- Session report is actually generated as a file

### 4. Live dashboard (not static upload page)

Gradio dashboard shows:

- Current monitoring status (active/paused)
- Live feed of screenshots with analysis overlays
- Alert timeline with clickable entries
- Click an alert -> full thinking chain from Gemma 4
- Session summary statistics

### 5. Fine-tuned model with measurable improvement

Not just "I ran Unsloth" — show side-by-side:

- Base Gemma 4 misses this grooming pattern -> fine-tuned catches it
- Accuracy numbers on a test set (baseline vs fine-tuned)

---

## HARDWARE

**Development & demo: Server with RTX 30GB VRAM**

- Ollama + Gemma 4 26B-A4B (18GB in 4-bit) — main inference, best quality
- Ollama + Gemma 4 E4B fine-tuned — Unsloth prize demonstration
- Full pipeline runs here
- Gradio dashboard served from here (use `share=True` for remote access)

**Laptop (24GB RAM):**

- Code editing, SSH to server
- Run game/Discord for demo capture (if server is headless)
- Can run E4B for quick testing

**If server is headless (no GUI):**

```
Option A: Run game on laptop -> screenshots sent to server via HTTP -> analysis on server -> results on Gradio
Option B: Use pre-recorded screen recordings -> server processes frames -> results on dashboard
Option C: Install lightweight desktop on server (xfce4 + VNC) -> run everything there
```

**For demo video recording:**

- Best: everything on one machine (server with GUI) -> OBS records both game + dashboard
- Alternative: record laptop screen (game) + server dashboard (browser) and edit together

> **Note:** Ollama will eventually run via Docker, but for now we use a local install. Don't add Docker config yet.

---

## TECH STACK

### Models

| Purpose                       | Model               | Where             | Why                                   |
|-------------------------------|---------------------|-------------------|---------------------------------------|
| Demo inference (best quality) | Gemma 4 26B-A4B-IT  | Server via Ollama | Best reasoning for impressive demo    |
| Fine-tuning (Unsloth prize)   | Gemma 4 E4B-IT      | Kaggle T4 (free)  | Fits in 16GB VRAM for QLoRA           |
| Edge deployment demo          | Fine-tuned E4B GGUF | Server via Ollama | Shows on-device deployment story      |

### Core Libraries

```
ollama          # Ollama Python SDK — inference + function calling
mss             # Screen capture — lightweight, cross-platform, one-liner
gradio          # Live dashboard UI
Pillow          # Image processing
sqlite3         # Local threat database (built-in Python)
smtplib         # Email alerts (built-in Python)
```

### Fine-tuning (Kaggle notebook)

```
unsloth         # QLoRA fine-tuning (1.5x faster, 60% less VRAM)
transformers    # Model loading
datasets        # Dataset handling
trl             # SFTTrainer
```

---

## ARCHITECTURE

```
+---------------------------------------------------------+
|                    MONITORING LOOP                       |
|                                                          |
|  +----------+    +--------------+    +---------------+   |
|  |  Screen  |--->|  Gemma 4     |--->|  Context      |   |
|  |  Capture |    |  Vision      |    |  Tracker      |   |
|  |  (mss)   |    |  (Ollama)    |    |  (sliding     |   |
|  |  every   |    |              |    |   window)     |   |
|  |  15 sec  |    |  OCR + scene |    |               |   |
|  +----------+    |  analysis    |    |  Detects      |   |
|                  +------+-------+    |  patterns     |   |
|                         |            |  across time  |   |
|                         v            +-------+-------+   |
|               +-----------------+            |           |
|               | Function Calling|            |           |
|               |                 |<-----------+           |
|               | classify_threat |                        |
|               | grooming_stage  |                        |
|               | parent_alert    |                        |
|               +--------+--------+                        |
|                        |                                 |
|                        v                                 |
|        +-------------------------------+                 |
|        |         OUTPUT LAYER          |                 |
|        |                               |                 |
|        |  +---------+ +------------+   |                 |
|        |  | SQLite  | | Parent     |   |                 |
|        |  | threat  | | alert      |   |                 |
|        |  | database| | (email)    |   |                 |
|        |  +---------+ +------------+   |                 |
|        |  +-------------------------+  |                 |
|        |  | Gradio Live Dashboard   |  |                 |
|        |  | - status, timeline,     |  |                 |
|        |  |   alerts, thinking      |  |                 |
|        |  |   chain, session stats  |  |                 |
|        |  +-------------------------+  |                 |
|        +-------------------------------+                 |
+---------------------------------------------------------+

All inference runs locally via Ollama. Zero cloud dependency.
```

---

## FUNCTION CALLING

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "classify_threat",
            "description": "Classify the safety threat level of the current screen content",
            "parameters": {
                "type": "object",
                "properties": {
                    "threat_level": {
                        "type": "string",
                        "enum": ["safe", "caution", "warning", "alert", "critical"]
                    },
                    "category": {
                        "type": "string",
                        "enum": ["none", "grooming", "bullying", "inappropriate_content", "personal_info_sharing", "scam"]
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence percentage 0-100"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Step-by-step explanation of why this classification was made"
                    },
                    "indicators_found": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of specific indicators detected"
                    },
                    "platform_detected": {
                        "type": "string",
                        "description": "What app/platform is visible on screen"
                    }
                },
                "required": ["threat_level", "category", "confidence", "reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "identify_grooming_stage",
            "description": "If grooming behavior detected, identify which stage of the grooming process is occurring",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "enum": ["none", "targeting", "trust_building", "isolation", "desensitization", "maintaining_control"]
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "risk_escalation": {
                        "type": "boolean",
                        "description": "Whether the risk is escalating compared to previous analysis"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_parent_alert",
            "description": "Generate a concise, privacy-respecting alert for the parent. Do NOT include raw chat text — summarize the concern without exposing the child's private conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alert_title": {
                        "type": "string",
                        "description": "Short title for the alert"
                    },
                    "summary": {
                        "type": "string",
                        "description": "2-3 sentence summary of the concern"
                    },
                    "recommended_action": {
                        "type": "string",
                        "description": "What the parent should do"
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "immediate"]
                    }
                },
                "required": ["alert_title", "summary", "recommended_action", "urgency"]
            }
        }
    }
]
```

---

## SYSTEM PROMPT

```
You are GuardianLens, an AI child safety monitor analyzing screenshots of a child's screen in real-time.

CAPABILITIES:
1. READ all visible text on screen (chat messages, usernames, URLs, notifications)
2. IDENTIFY the platform/application (Minecraft, Discord, Instagram, browser, etc.)
3. DETECT grooming patterns, cyberbullying, inappropriate content, personal info sharing
4. REASON about context using conversation history from previous screenshots
5. CLASSIFY threat level with confidence score using provided tools
6. EXPLAIN every decision transparently — show your reasoning step by step

GROOMING INDICATORS (escalating severity):
- Stage 1 - Targeting: Asking about age, gender, location
- Stage 2 - Trust building: Excessive compliments, "you're so mature", shared interests
- Stage 3 - Isolation: "Let's talk on Discord/Snap instead", "don't tell your parents"
- Stage 4 - Desensitization: Age-inappropriate topics, "it's normal", sending/requesting images
- Stage 5 - Maintaining control: Threats, guilt, emotional manipulation

BULLYING INDICATORS:
- Repeated negative messages targeting one person
- Name-calling, insults, threats of violence
- Social exclusion ("nobody likes you", "you should leave")
- Mocking appearance, abilities, or personal details
- Sharing embarrassing content

RULES:
- Always use the classify_threat tool for structured output
- If grooming detected, also use identify_grooming_stage tool
- If threat_level is "warning" or higher, use generate_parent_alert tool
- MINIMIZE false positives — normal gaming trash talk is NOT bullying
- Be specific: quote the exact concerning text you found
- Explain WHY something is concerning, not just THAT it is
- If screen shows normal, safe activity — say so clearly and briefly
```

---

## CONTEXT TRACKING (session_tracker.py)

This is what makes GuardianLens more than "call LLM on each screenshot":

```python
class SessionTracker:
    """
    Maintains sliding window of last N analyses.
    Detects patterns that only emerge over time:
    - Grooming escalation (innocent -> suspicious over multiple screenshots)
    - Repeated bullying from same user
    - Gradual exposure to inappropriate content
    """

    def __init__(self, window_size: int = 10):
        self.history = []  # List of analysis results
        self.window_size = window_size
        self.flagged_users = {}  # Track suspicious usernames across time
        self.session_start = None
        self.alert_count = 0

    def add_analysis(self, analysis: dict) -> dict:
        """Add new analysis, check for cross-time patterns, return enriched result."""
        self.history.append(analysis)
        if len(self.history) > self.window_size:
            self.history.pop(0)

        # Check for escalation patterns
        enriched = self._check_escalation(analysis)
        return enriched

    def _check_escalation(self, current: dict) -> dict:
        """Compare current analysis with history to detect escalation."""
        # Implementation: compare grooming stages, track user mentions,
        # detect increasing threat levels over time
        pass

    def get_session_summary(self) -> dict:
        """Generate summary of entire monitoring session."""
        pass
```

The key insight for judges: **a single screenshot might look innocent. But the PATTERN across 5-10 screenshots reveals grooming.** This is what keyword filters and simple classifiers cannot do.

---

## FINE-TUNING PLAN (Unsloth Prize)

### Model: Gemma 4 E4B-IT

### Method: Unsloth QLoRA on Kaggle T4 (free, 16GB VRAM)

### Dataset

| Source                          | Type                  | Volume      | How to get                                                            |
|---------------------------------|-----------------------|-------------|-----------------------------------------------------------------------|
| PAN12 (Perverted Justice)       | Grooming conversations| ~28K convos | pan.webis.de — public dataset                                         |
| Synthetic safe gaming           | Normal game chats     | 300+        | Write yourself: "gg wp", "nice build", "who has diamonds?"            |
| Synthetic bullying              | Bullying patterns     | 100+        | Write yourself: subtle and overt bullying                             |
| Screenshot + analysis pairs     | Multimodal training   | 50+         | Screenshot games/Discord + write ideal GuardianLens response          |

### Training format (JSONL)

```jsonl
{"messages": [
  {"role": "system", "content": "You are GuardianLens..."},
  {"role": "user", "content": [
    {"type": "image", "path": "minecraft_safe_01.png"},
    {"type": "text", "text": "Analyze this screen for child safety threats."}
  ]},
  {"role": "assistant", "content": "PLATFORM: Minecraft multiplayer\n\nI can see a chat window with 3 participants discussing building strategies. Messages include 'anyone want to help build the castle?' and 'I found iron near spawn.'\n\nAll conversation topics are game-related and age-appropriate. No personal information shared. No concerning patterns.\n\n[classify_threat: safe, none, 96%]"}
]}
```

### Config

```python
lora_r = 16
lora_alpha = 16
learning_rate = 2e-4
num_epochs = 3
per_device_train_batch_size = 2
gradient_accumulation_steps = 4
max_seq_length = 2048
```

### Export pipeline

```
Gemma 4 E4B-IT -> Unsloth QLoRA -> merge adapter -> GGUF (q4_k_m) -> Ollama Modelfile -> `ollama create guardlens`
```

### What to show in writeup

- Baseline accuracy on test set (base E4B)
- Fine-tuned accuracy on same test set
- Side-by-side examples: "base model missed this -> fine-tuned caught it"
- Training loss curve
- Confusion matrix (safe/grooming/bullying/inappropriate)

---

## VIDEO SCRIPT (MAX 2 MINUTES — THIS IS 70% OF YOUR SCORE)

```
0:00-0:08  HOOK (black screen, white text, dramatic)
           "669 harmful interactions."
           "50 hours."
           "Children ages 12 to 15."
           Beat.
           "Their parental controls were on the entire time."

0:08-0:25  THE PROBLEM (split screen, visual contrast)
           Left side: Family Link dashboard — "Screen time: 2h 14m"
           Right side: what's actually happening in the game chat
           Voiceover: "Parental controls tell you how long your child was online.
           They cannot tell you what happened."

0:25-1:05  THE DEMO (real, live, working — NOT mocked)
           Full screen: game with visible chat + GuardianLens dashboard side by side.

           Phase 1 (10 sec): Normal gameplay, normal chat
           Dashboard: "Safe... Safe... Safe..."

           Phase 2 (15 sec): Grooming patterns appear in chat
           Dashboard animates: "CAUTION -> ALERT"
           Click alert -> full thinking chain appears:
           "User 'CoolGuy99' asked about age [indicator 1],
            proposed moving to private channel [indicator 2],
            offered free items [indicator 3].
            Grooming stage: trust_building -> isolation.
            Confidence: 89%"

           Phase 3 (5 sec): Parent notification arrives
           Phone notification or email: "GuardianLens Alert:
           Suspicious contact detected during Minecraft session"

1:05-1:25  WHY THIS IS DIFFERENT (technical credibility)
           Quick cuts:
           - Same engine analyzing Discord screenshot -> catches bullying
           - "One engine. Any screen. Any platform."
           - Terminal: `ollama run guardlens` — "Runs entirely local"
           - Airplane mode toggle -> system keeps working
           - Chart: "Base Gemma 4: 64% -> Fine-tuned with Unsloth: 91%"

1:25-1:45  CONTEXT TRACKING (the "wow" technical moment)
           Show the timeline view:
           "Screenshot 1: user asks 'how old are you' — flagged as caution"
           "Screenshot 4: same user says 'add me on discord' — escalation detected"
           "Screenshot 7: 'I can send you a gift card' — ALERT: grooming stage 3"
           Voiceover: "GuardianLens doesn't analyze screenshots in isolation.
           It tracks patterns across time — just like a real predator operates."

1:45-2:00  CLOSING (emotional, memorable)
           "Every child deserves a guardian that sees what they see,
            understands what's happening,
            and never needs to sleep."
           "GuardianLens."
           Logo. GitHub link. "Built with Gemma 4 + Ollama + Unsloth"
```

**VIDEO PRODUCTION NOTES:**

- Use background music (royalty-free, subtle, builds tension)
- Text overlays for statistics (not just voiceover)
- Smooth transitions, not jump cuts
- The demo section MUST be real screen recording of the actual working system
- Record at 1080p minimum
- Total length: 1:50-2:00 (use every second, but don't exceed 2:00)

---

## PROJECT STRUCTURE

```
guardlens/
├── src/
│   └── guardlens/
│       ├── __init__.py
│       ├── monitor.py              # Screen capture loop (mss, configurable interval)
│       ├── analyzer.py             # Send screenshot to Ollama, parse response
│       ├── session_tracker.py      # Cross-screenshot context tracking + escalation detection
│       ├── tools.py                # Function calling tool definitions + execution
│       ├── alerts.py               # Parent notification (email/webhook)
│       ├── database.py             # SQLite storage for threats, sessions, alerts
│       ├── prompts.py              # Versioned system + analysis prompts
│       ├── schema.py               # Pydantic models for analysis results
│       ├── utils.py                # seed_everything, logging
│       └── config.py               # Configuration (model, interval, thresholds, email settings)
│
├── app/
│   └── dashboard.py                # Gradio live monitoring dashboard
│
├── notebooks/
│   ├── 01_prepare_data.ipynb       # Kaggle — prepare PAN12 + synthetic data
│   ├── 02_finetune.ipynb           # Kaggle — Unsloth QLoRA fine-tuning + export GGUF
│   └── 03_evaluate.ipynb           # Kaggle — baseline vs fine-tuned accuracy comparison
│
├── data/
│   ├── training/                   # Training JSONL + images
│   ├── test/                       # Test set for accuracy benchmarks
│   └── demo_scenarios/             # Pre-built scenarios for demo recording
│
├── models/
│   └── Modelfile                   # Ollama deployment config for fine-tuned model
│
├── tests/
│   └── test_pipeline.py            # Basic tests: capture works, Ollama responds, tools execute
│
├── CONTEXT.md                      # This file
├── README.md                       # Kaggle writeup content (problem, solution, architecture, results)
├── requirements.txt                # pip dependencies
└── run.py                          # Single entry point: `python run.py` starts monitoring + dashboard
```

### Entry point (run.py)

```python
"""
GuardianLens — AI Child Safety Monitor
Usage: python run.py [--model gemma4:26b] [--interval 15] [--dashboard-port 7860]
"""
# Starts the monitoring loop + Gradio dashboard in parallel
# One command to launch everything
```

---

## WEEKLY PLAN

### WEEK 1 (Apr 8-14): VALIDATE + DATA

**Critical question: Can Gemma 4 read chat text from a game screenshot?**

Day 1-2:

- [ ] Install Ollama on server: `curl -fsSL https://ollama.com/install.sh | sh`
- [ ] Pull models: `ollama pull gemma4` (E4B) + `ollama pull gemma4:26b` (26B)
- [ ] Take Minecraft/Discord screenshot with visible chat
- [ ] Test with 26B model: "What text is visible in the chat area of this screenshot?"
- [ ] Test with visual token budget 1120 for small text OCR
- [ ] **IF WORKS -> project is GO**
- [ ] **IF FAILS -> test different games, adjust prompting, consider alternatives**

Day 3-5:

- [ ] Download PAN12 dataset (pan.webis.de)
- [ ] Write 300+ safe gaming conversations (varied, realistic)
- [ ] Write 100+ bullying conversations (subtle + overt)
- [ ] Take 50+ screenshots from games/Discord with different scenarios
- [ ] Format all data as training JSONL

Day 6-7:

- [ ] Test base Gemma 4 on 50 grooming + 50 safe + 20 bullying conversations
- [ ] Record baseline accuracy numbers
- [ ] Test on 20 screenshots — does model correctly identify safe vs threat?
- [ ] Write initial system prompt, iterate based on results

### WEEK 2 (Apr 15-21): FINE-TUNE + CORE PIPELINE

Day 1-3:

- [ ] Setup Unsloth on Kaggle T4 notebook
- [ ] Fine-tune E4B QLoRA on safety dataset
- [ ] Measure accuracy improvement vs baseline
- [ ] Export to GGUF, create Ollama Modelfile, deploy as `guardlens`

Day 4-7:

- [ ] Build monitor.py — screen capture loop with mss
- [ ] Build analyzer.py — send screenshot to Ollama, parse structured response
- [ ] Build tools.py — function definitions + actual execution logic
- [ ] Build database.py — SQLite storage for all analyses and alerts
- [ ] Test: start monitor -> capture 10 screenshots -> verify analysis pipeline works

### WEEK 3 (Apr 22-28): CONTEXT TRACKING + DASHBOARD

- [ ] Build session_tracker.py — sliding window, cross-screenshot pattern detection
- [ ] Build escalation detection: grooming stage progression, repeated bullying
- [ ] Build alerts.py — email/webhook notification to parent
- [ ] Build Gradio dashboard: live status, alert timeline, thinking chain viewer
- [ ] Build run.py — single entry point that starts everything
- [ ] End-to-end test: monitor runs for 10+ minutes, detects planted threats, sends alerts

### WEEK 4 (Apr 29 - May 5): POLISH + DEMO SCENARIOS

- [ ] Create 3 demo scenarios with pre-planned chat scripts:
  1. Safe gaming session (2-3 min normal Minecraft gameplay)
  2. Grooming pattern (normal -> suspicious -> alert over 2-3 min)
  3. Cyberbullying on Discord (screenshot sequence)
- [ ] Test each scenario end-to-end with live monitoring
- [ ] Fix edge cases, improve prompt quality based on failures
- [ ] Polish dashboard UI: make it visually clear and demo-ready
- [ ] Verify: fine-tuned model (guardlens) vs base model side-by-side

### WEEK 5 (May 6-12): VIDEO + WRITEUP — HIGHEST PRIORITY

- [ ] **Record all demo footage** — real system, real monitoring, real detections
- [ ] **Edit video** following the script above (music, text overlays, pacing)
- [ ] **Keep under 2 minutes** — make first 10 seconds count
- [ ] Write Kaggle writeup:
  - Problem statement with statistics
  - Architecture diagram
  - How Gemma 4 features are used (vision, function calling, thinking, local deployment)
  - Fine-tuning methodology and accuracy results
  - Privacy argument (on-device, no cloud)
  - Screenshots from dashboard
- [ ] Clean GitHub repo, write comprehensive README

### WEEK 6 (May 13-18): FINAL REVIEW + SUBMIT

- [ ] Watch video 10 times — is it compelling in the first 10 seconds?
- [ ] Have someone else watch it and give feedback
- [ ] Verify: code repo is public, all files present, README is clear
- [ ] Verify: Kaggle writeup mentions Ollama and Unsloth prominently
- [ ] Submit to Safety & Trust track
- [ ] **SUBMIT BEFORE May 18**

---

## PRIORITY ORDER (if running out of time)

Cut from the bottom. Never cut from the top.

1. **VIDEO DEMO** — this is 70% of scoring. Spend maximum time here.
2. **Working continuous monitoring loop** — must be real for technical verification
3. **Context tracking across screenshots** — this is the "wow" technical differentiator
4. **Ollama local deployment + function calling** — Ollama prize
5. **Fine-tuned model via Unsloth** — Unsloth prize
6. **Gradio live dashboard** — can be basic/ugly, just needs to show data
7. **Email parent alerts** — can be simulated in demo if needed
8. **Session summary reports** — nice to have

---

## CODING RULES FOR CLAUDE CODE

1. Python 3.10+, type hints everywhere
2. Ollama API via `ollama` package (`pip install ollama`)
3. Screen capture via `mss` (`pip install mss`) — NOT pyautogui
4. UI via Gradio (`pip install gradio`)
5. Fine-tuning via Unsloth on Kaggle — NOT locally
6. Gemma 4 uses standard chat roles: system, user, assistant
7. Multimodal prompts: image BEFORE text (Gemma 4 requirement)
8. Function calling via Ollama's `tools` parameter in chat()
9. Keep code clean and readable — judges WILL read it
10. Every module has clear docstrings explaining purpose
11. `python run.py` should start the entire system
12. No complex dependencies — keep requirements.txt minimal
13. Handle Ollama connection errors gracefully
14. Log everything — analysis results, alerts, errors — to both console and file
15. Don't add Docker yet — Ollama runs via local install for now
