# GuardianLens — FINAL Dashboard Design (v4)
# Authoritative mockups:
#   - guardlens_final_no_duplication.html          (overall layout, zero duplication)
#   - guardlens_three_right_panel_states.html      (the three right-panel states)
# This doc supersedes earlier dashboard notes.

## Principle: ZERO DUPLICATION — each panel has one job

### Left panel = WHAT is happening (the specifics)
- Live capture + status bar
- Stats row: scans / conversations / environments / alerts
- Activity list sorted by danger (red → yellow → green)
  - Circle avatar = PERSON (tracked conversation)
  - Square icon = PLACE (tracked environment)
- This is the operational view — "who, where, how dangerous"

### Right panel = HOW is the session going (the big picture) — three states

**State 1: Session overview (default, nothing clicked)**
- "Currently safe ✓" checkmark header (green) or "Alerts active" (red)
- Session stats: duration, conversations count, environments count, alerts count
- **Session narrative** — the killer feature — written by Gemma 4 in plain language:
  > "Your child spent 1 hour 12 minutes across 4 platforms. Two concerning
  > contacts were detected: lily_summer on Instagram displayed grooming
  > behavior. CoolGuy99 in Minecraft targeted your child. ShadowPro on
  > Discord engaged in bullying."
- Safe activities listed below the concerning ones
- **"What to do"** — CONSOLIDATED recommended actions that reference
  ALL threats in the session, not per-alert. Single action list.
- Telegram summary: one line — "Telegram delivered: 2 alerts at 14:22 and 14:37"
- Hint text: "Select any activity on the left to view full analysis"

**State 2: Conversation detail (click a circle/person)**
- Back button: "← Session overview"
- User header: avatar + username + platform + confidence% + message count + duration
- Threat summary card: category + confidence + grooming stage bar
- **Conversation arc** — message-by-message timeline with colored dots:
  - Green dot = safe message
  - Yellow dot = concerning (indicator label shown)
  - Red dot = dangerous (indicator label shown)
  - Visual escalation: green → yellow → red over time
- AI reasoning chain (monospace)
- Recommended actions (purple, numbered)
- Telegram delivery status

**State 3: Environment detail (click a square/platform)**
- Back button: "← Session overview"
- Platform header: square icon + platform name + user count + duration
- Threat summary card
- **User list** — everyone in this space:
  - Promoted/dangerous users highlighted red with "promoted" badge
  - Everyone else green and safe
- AI reasoning explaining what happened in the space
- Recommended actions
- Telegram status

## Navigation
```
Nothing clicked       → State 1 (session overview)
Click circle (person) → State 2 (conversation arc)
Click square (place)  → State 3 (environment users)
Click "← Session overview" → State 1
New alert fires       → auto-show State 2 for that person
```

Three states, one back button, zero confusion.

## Why this wins the hackathon

1. **Session narrative** is something ONLY an AI-powered tool can generate.
   No competitor has a system that watches a child's online session and
   writes a plain-language parent-report at the end. This is Gemma 4's
   moment.

2. **Consolidated "What to do"** references BOTH lily_summer AND CoolGuy99
   in the same action list — it's a session-level recommendation, not
   per-alert. This is more useful for a real parent.

3. **State 2 vs State 3 different content types** — conversation detail
   shows the ARC (message-by-message), environment detail shows the USER
   LIST (who's in the space). One size does not fit both.

## Video demo flow

1. Calm green dashboard, narrative: "Your child spent 48m, all safe"
2. Grooming starts → activity list gets red card → narrative updates in
   real-time to include the new threat
3. Click lily_summer → right panel switches to conversation arc
   (green dots escalating to red dots)
4. Click "← Session overview" → narrative now tells the full story
