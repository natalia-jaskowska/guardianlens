# GuardianLens: On-Device Child Safety Monitor Powered by Gemma 4

**Real-time grooming and cyberbullying detection that runs entirely on your home machine — no cloud, no subscriptions, no data leaving the device.**

Track: Safety & Trust

---

## The Problem

Every parent knows the fear. Their child is online — on Discord, Instagram, Roblox, TikTok — for hours every day. Modern parenting apps report screen time and app categories. None of them understand what is actually being said.

A child can spend hours inside a "safe" app while a grooming conversation unfolds in plain sight. The predator knows this. The parent does not.

The barrier to detecting real harm is not data — it is intelligence. A parent cannot monitor every conversation in real time. A local vision-language model can.

---

## The Solution

GuardianLens runs a Gemma 4 vision model on the parent's home machine. Every 15 seconds it captures the child's screen, reads every visible chat conversation, and reasons about whether a threat is developing. If it detects grooming, cyberbullying, or explicit content, it sends the parent an instant alert — without ever transmitting the child's messages to a cloud server.

Privacy is not a feature. It is the architecture.

---

## How Gemma 4 Powers GuardianLens

Three of Gemma 4's unique capabilities are essential to this system:

### 1. Multimodal Vision

GuardianLens never uses OCR or platform-specific APIs. It passes raw base64-encoded screenshots directly to Gemma 4 as vision input. The model reads chat text exactly as a human would — regardless of platform, font, or UI layout. This means the system works on Discord, Instagram, Roblox, Minecraft, TikTok, and any future platform without a single line of platform-specific code.

### 2. Native Function Calling

Rather than asking the model to produce free-form text and parsing it, GuardianLens uses Gemma 4's native tool-calling interface (via Ollama) to extract structured outputs at every step. This eliminates hallucination in the output schema and makes every response machine-parseable:

- **`extract_conversations`** — returns a typed list of all visible chat conversations, participants, and verbatim messages from the screenshot
- **`update_conversation_status`** — returns a full threat classification: level, category, confidence percentage, grooming stage, specific behavioral indicators, and a parent-facing narrative

Every field is validated by Pydantic. The pipeline gracefully handles missing tool calls (safe fallback) and normalizes model quirks such as returning confidence as a fraction instead of a percentage.

### 3. Extended Reasoning — Transparent AI

GuardianLens extracts Gemma 4's internal reasoning chain from each analysis and surfaces it in the parent dashboard. Parents do not just see "ALERT" — they see exactly why the model flagged a conversation: which messages triggered concern, what grooming stage was identified, and the model's confidence level. This is the Safety & Trust track's core requirement made real: AI that is explainable.

---

## Architecture

```
Child's device (client)          Parent's machine (server)
─────────────────────────        ─────────────────────────────
guardlens-client                 FastAPI + Ollama (Gemma 4)
  mss screen capture  ──PNG──▶    ConversationPipeline
  httpx sender                    SQLite database
                                  SSE live dashboard :7860
```

### Analysis Pipeline (per frame)

Each screenshot triggers a 4-step pipeline inside `ConversationPipeline.push_screenshot()`:

**Step 1 — Extract.** Gemma 4 vision call with `extract_conversations` tool. Returns all visible chat fragments: platform, participants, and verbatim messages copied exactly from the screen.

**Step 2 — Match & Merge.** Deterministic (no LLM). Each extracted fragment is fuzzy-matched to an existing conversation in SQLite. New messages are deduplicated against stored history using OCR-tolerant string matching.

**Step 3 — Assess.** Gemma 4 reasoning call with `update_conversation_status` tool. The model receives the **full conversation history** — not just the latest screenshot — and reassesses threat level, confidence, grooming stage, and behavioral indicators. Alerts are only generated when `certainty` is `medium` or `high` and `threat_level` is `warning` or above, requiring 3–5+ corroborating messages before flagging.

**Step 4 — Alert.** If `parent_alert_recommended=true`, a parent-facing summary is dispatched via Telegram, email, or webhook.

All state is committed to SQLite after each step. A crash mid-pipeline loses at most one frame.

### Deployment

The server ships as a two-container Docker Compose stack: Ollama (Gemma 4 on port 11434) and the GuardianLens FastAPI dashboard (port 7860). The lightweight client is a standalone Python package that runs silently on the child's device. Both the 12B and 26B Gemma 4 variants are supported.

---

## Technical Challenges

### Cross-frame conversation continuity

A single screenshot captures only a window into an ongoing conversation. The real threat signal emerges over time — a series of individually innocuous messages that together constitute grooming. GuardianLens solves this by accumulating full conversation history in SQLite and passing it back to Gemma 4 on every new frame. The model always reasons about the full arc of the conversation.

### False positive rate

An alert system that cries wolf is worse than no system. The system prompt encodes an explicit 5-stage grooming escalation model (targeting → trust building → isolation → desensitization → maintaining control) with concrete non-grooming counter-examples the model must not flag. Alerts require both medium/high certainty and a warning-or-above threat level.

### Latency on consumer hardware

Gemma 4's vision model takes 8–15 seconds per analysis on a consumer GPU — acceptable for a 15-second capture interval but requiring careful pipeline design. The MonitorWorker runs as a daemon thread independent of FastAPI's event loop, keeping the dashboard fully responsive during inference. A single-worker model keeps GPU load predictable and eliminates SQLite write contention.

---

## Design Decisions

| Choice | Rationale |
|---|---|
| Gemma 4 via Ollama | The child's chat data never leaves the home network. Critical for trust and GDPR compliance. |
| Native tool calling over prompt parsing | Every output field is typed and Pydantic-validated. No regex. No fragile parsing. |
| SQLite over in-memory state | Survives crashes and reboots. Full alert history available for review. |
| SSE over WebSockets | Stateless, works through proxies and firewalls, zero client-side configuration. |
| Separate client/server architecture | Parents monitor from a different machine, keeping the process invisible to the child. |
| Single-worker inference | Predictable GPU utilisation and zero write conflicts — safety over throughput. |

---

## Impact

GuardianLens is deployable today on any household with a GPU capable of running Gemma 4. The Docker Compose stack is live in under 5 minutes. The client runs silently on any Windows, macOS, or Linux machine.

More importantly, it is the first parental monitoring tool that **explains its reasoning**. Every alert includes the model's full thinking chain: the specific messages that triggered the flag, the grooming stage assessment, and the confidence level. Parents make informed decisions rather than reacting to opaque risk scores.

Other apps count minutes. GuardianLens understands what's happening.
