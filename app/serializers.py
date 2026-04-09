"""Convert :class:`ScreenAnalysis` objects into JSON-friendly dicts.

The FastAPI server returns these dicts to the browser. The browser-side
JavaScript renders the DOM from the dict — no HTML rendering happens on
the server side any more (we used to render HTML strings in
``app.components`` for the Gradio version).

Keeping the serialization logic in its own module means:

- Easy to unit-test without spinning up FastAPI.
- One source of truth for the wire format.
- Adding a new field flows from :mod:`guardlens.schema` -> here -> the JS
  render functions in ``app/static/dashboard.js``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from guardlens.schema import (
    GroomingStage,
    ScreenAnalysis,
    ThreatCategory,
    ThreatLevel,
)

# Order matters — left-to-right on the stage progress bar
GROOMING_STAGE_ORDER: tuple[GroomingStage, ...] = (
    GroomingStage.TARGETING,
    GroomingStage.TRUST_BUILDING,
    GroomingStage.ISOLATION,
    GroomingStage.DESENSITIZATION,
    GroomingStage.MAINTAINING_CONTROL,
)
GROOMING_STAGE_LABELS: dict[str, str] = {
    GroomingStage.TARGETING.value: "Target",
    GroomingStage.TRUST_BUILDING.value: "Trust",
    GroomingStage.ISOLATION.value: "Isolate",
    GroomingStage.DESENSITIZATION.value: "Desens.",
    GroomingStage.MAINTAINING_CONTROL.value: "Control",
}

ALERT_LEVELS: frozenset[ThreatLevel] = frozenset({ThreatLevel.ALERT, ThreatLevel.CRITICAL})


# ----------------------------------------------------------------------- analysis


def serialize_analysis(
    analysis: ScreenAnalysis,
    history: list[ScreenAnalysis] | None = None,
) -> dict[str, Any]:
    """Convert one :class:`ScreenAnalysis` into a flat JSON dict.

    The optional ``history`` is used by the reasoning-chain generator to
    cite previous escalation events ("22:03 flagged CAUTION → 22:04
    escalated"). When omitted, the chain just skips the cross-reference
    step.
    """
    cls = analysis.classification
    history_list = history or []
    payload: dict[str, Any] = {
        "timestamp": analysis.timestamp.isoformat(),
        "time_label": analysis.timestamp.strftime("%H:%M:%S"),
        "screenshot_url": _screenshot_url(analysis),
        "platform": analysis.platform or "Unknown",
        "platform_key": _platform_key(analysis.platform),
        "inference_seconds": round(analysis.inference_seconds, 2),
        "threat_level": cls.threat_level.value,
        "category": cls.category.value,
        "category_label": cls.category.value.upper().replace("_", " "),
        "confidence": round(cls.confidence, 0),
        "reasoning": cls.reasoning,
        "indicators": list(cls.indicators_found),
        "is_alert": cls.threat_level in ALERT_LEVELS,
        "chat_messages": [
            {"sender": m.sender, "text": m.text, "flag": m.flag}
            for m in (analysis.chat_messages or [])
        ],
        "conversation": _conversation_meta(analysis),
        "threat_breakdown": _threat_breakdown(analysis),
        "reasoning_chain": generate_reasoning_chain(analysis, history_list),
        "why_this_matters": generate_why_this_matters(analysis),
        "recommended_action": generate_recommended_action(analysis),
        "indicator_pills": _indicator_pills(analysis),
        "stage_segments": _stage_segments(analysis),
        # Stat boxes belong to the analysis itself so the threat
        # breakdown card stays coherent when the dashboard is showing
        # the most recent ALERT instead of the most recent scan.
        "stat_boxes_inline": stat_boxes(analysis, history_list),
    }

    if analysis.grooming_stage is not None:
        payload["grooming_stage"] = serialize_stage(analysis.grooming_stage.stage)
        payload["grooming_evidence"] = list(analysis.grooming_stage.evidence)
        payload["grooming_escalating"] = analysis.grooming_stage.risk_escalation
    else:
        payload["grooming_stage"] = None
        payload["grooming_evidence"] = []
        payload["grooming_escalating"] = False

    if analysis.parent_alert is not None:
        payload["parent_alert"] = {
            "title": analysis.parent_alert.alert_title,
            "summary": analysis.parent_alert.summary,
            "recommended_action": analysis.parent_alert.recommended_action,
            "urgency": analysis.parent_alert.urgency.value,
        }
    else:
        payload["parent_alert"] = None

    return payload


def serialize_stage(stage: GroomingStage) -> dict[str, Any]:
    """Render the grooming stage as a 5-segment progress bar payload."""
    if stage == GroomingStage.NONE:
        current_idx = -1
    else:
        try:
            current_idx = GROOMING_STAGE_ORDER.index(stage)
        except ValueError:
            current_idx = -1

    segments = []
    for idx, candidate in enumerate(GROOMING_STAGE_ORDER):
        if idx < current_idx:
            state = "active"
        elif idx == current_idx:
            state = "current"
        else:
            state = "inactive"
        segments.append(
            {
                "label": GROOMING_STAGE_LABELS[candidate.value],
                "state": state,
                "value": candidate.value,
            }
        )
    return {
        "current": stage.value,
        "current_index": current_idx,
        "segments": segments,
    }


def serialize_timeline(analyses: Iterable[ScreenAnalysis]) -> list[dict[str, Any]]:
    """Serialize a list of analyses, newest first."""
    return [serialize_analysis(a) for a in reversed(list(analyses))]


# ----------------------------------------------------------------------- helpers


def empty_summary() -> dict[str, int]:
    """Per-threat-level zero counts (used as the metric-cards baseline)."""
    return {level.value: 0 for level in ThreatLevel}


def session_totals(summary: dict[str, int]) -> dict[str, int]:
    """Collapse the 5 threat levels into the 4 metric cards.

    The dashboard shows: Screenshots / Safe / Caution / Alerts.
    Caution column aggregates ``caution`` + ``warning``.
    Alerts column aggregates ``alert`` + ``critical``.
    """
    return {
        "screenshots": sum(summary.values()),
        "safe": summary.get("safe", 0),
        "caution": summary.get("caution", 0) + summary.get("warning", 0),
        "alerts": summary.get("alert", 0) + summary.get("critical", 0),
    }


def metric_sublabels(totals: dict[str, int]) -> dict[str, str]:
    """One-line context strings shown under each metric card value."""
    screenshots = totals["screenshots"]
    if screenshots == 0:
        return {
            "screenshots": "warming up",
            "safe": "0% of scans",
            "caution": "0% of scans",
            "alerts": "no active threats",
        }
    safe_pct = round(100 * totals["safe"] / screenshots)
    caution_pct = round(100 * totals["caution"] / screenshots)
    alerts = totals["alerts"]
    return {
        "screenshots": "live · 8s interval",
        "safe": f"{safe_pct}% of scans",
        "caution": f"{caution_pct}% of scans",
        "alerts": "no active threats" if alerts == 0 else (
            "1 active threat" if alerts == 1 else f"{alerts} active threats"
        ),
    }


def stat_boxes(
    analysis: ScreenAnalysis | None,
    history: list[ScreenAnalysis],
) -> list[dict[str, str]]:
    """Three dense info boxes shown under the grooming stage bar.

    Returns a list of ``{"label": "...", "value": "..."}`` dicts so the
    front-end can render them without per-box conditionals.
    """
    if analysis is None:
        return [
            {"label": "Indicators", "value": "—"},
            {"label": "Escalation", "value": "—"},
            {"label": "Stage", "value": "0/5"},
        ]

    indicator_count = len(analysis.classification.indicators_found)

    # Stage index out of 5
    stage_idx = 0
    if analysis.grooming_stage is not None:
        stage_value = analysis.grooming_stage.stage
        if stage_value != GroomingStage.NONE:
            try:
                stage_idx = GROOMING_STAGE_ORDER.index(stage_value) + 1
            except ValueError:
                stage_idx = 0

    # Escalation time = seconds between first non-safe analysis in the
    # current window and now.
    escalation_label = "—"
    first_unsafe_ts: datetime | None = None
    for past in history:
        if past.classification.threat_level != ThreatLevel.SAFE:
            first_unsafe_ts = past.timestamp
            break
    if first_unsafe_ts is not None and analysis.timestamp >= first_unsafe_ts:
        delta = analysis.timestamp - first_unsafe_ts
        delta_seconds = max(0, int(delta.total_seconds()))
        if delta_seconds < 60:
            escalation_label = f"{delta_seconds}s"
        else:
            escalation_label = f"{delta_seconds // 60}m {delta_seconds % 60:02d}s"

    return [
        {"label": "Indicators", "value": str(indicator_count)},
        {"label": "Escalation", "value": escalation_label},
        {"label": "Stage", "value": f"{stage_idx}/5"},
    ]


def compute_safe_streak(history: list[ScreenAnalysis]) -> int:
    """How many consecutive safe analyses from the latest backwards.

    Used by the header streak badge. Walks the session window from
    newest to oldest, counting safe scans until it hits a non-safe one
    or runs out of history.
    """
    count = 0
    for analysis in reversed(history):
        if analysis.classification.threat_level == ThreatLevel.SAFE:
            count += 1
        else:
            break
    return count


def build_session_health(
    *,
    totals: dict[str, int],
    session_duration: str,
    model_name: str,
    platform_counts: dict[str, int],
    avg_inference_seconds: float | None,
    monitoring: bool,
    last_alert: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the Session Health payload shown when no alert is active.

    Fills the right panel's dead space with positive signal: total scan
    count, streak context, platform distribution, model health, and a
    dimmed "last alert N ago" reference so the parent knows the system
    has caught things in the past even when the current scan is clean.
    """
    clean = totals.get("caution", 0) == 0 and totals.get("alerts", 0) == 0
    # Top 4 platforms by count (truncate longer labels for the UI).
    platforms: list[dict[str, Any]] = [
        {"name": (name or "Unknown")[:32], "count": count}
        for name, count in sorted(
            platform_counts.items(), key=lambda item: (-item[1], item[0])
        )[:4]
    ]
    avg_label = (
        f"{avg_inference_seconds:.1f}s avg" if avg_inference_seconds is not None else "— avg"
    )

    last_alert_payload: dict[str, Any] | None = None
    if last_alert is not None:
        ts_raw = last_alert.get("timestamp")
        elapsed_label = "just now"
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw)
                elapsed = (datetime.now() - ts).total_seconds()
                elapsed_label = _format_elapsed(elapsed)
            except (TypeError, ValueError):
                elapsed_label = "earlier"
        platform_name = last_alert.get("platform") or "Unknown"
        category = (last_alert.get("category") or "threat").replace("_", " ")
        last_alert_payload = {
            "ago": elapsed_label,
            "description": f"{platform_name} {category}",
        }

    return {
        "clean": clean,
        "monitoring": monitoring,
        "headline": "ALL CLEAR" if clean else "MINOR ALERTS",
        "scans": totals.get("screenshots", 0),
        "safe": totals.get("safe", 0),
        "caution": totals.get("caution", 0),
        "alerts": totals.get("alerts", 0),
        "session_duration": session_duration,
        "platforms": platforms,
        "platform_count": len(platform_counts),
        "model_name": model_name,
        "avg_inference_label": avg_label,
        "last_alert": last_alert_payload,
    }


def _format_elapsed(seconds: float) -> str:
    """'4m 12s ago' / '1h 3m ago' / '2d ago'."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s ago"
    if s < 86400:
        hours, rem = divmod(s, 3600)
        return f"{hours}h {rem // 60}m ago"
    return f"{s // 86400}d ago"


def build_alert_history(
    rows: list[tuple[int, ScreenAnalysis]],
) -> list[dict[str, Any]]:
    """Convert a list of (id, ScreenAnalysis) tuples into card payloads.

    Each card is a small summary dict the front-end uses to render an
    item in the "Alert history" list. The full analysis (reasoning
    chain, why this matters, recommended action, telegram, etc.) is
    NOT included here — the JS fetches that on-demand from
    ``/api/analysis/{id}`` when the user clicks a card.
    """
    out: list[dict[str, Any]] = []
    now = datetime.now()
    for analysis_id, analysis in rows:
        cls = analysis.classification
        level = cls.threat_level.value
        severity = "alert" if level in ("alert", "critical") else "caution"
        # Pick the first non-self sender as "user", fall back per platform
        user = "unknown"
        for msg in analysis.chat_messages or []:
            sender = (msg.sender or "").strip()
            if sender and sender.lower() not in _GENERIC_SENDERS:
                user = sender.lstrip("@<").rstrip(">")
                break
        if user == "unknown":
            key = _platform_key(analysis.platform)
            user = _DEFAULT_USERNAMES.get(key, "unknown")

        # One-line summary: a couple of indicator phrases + grooming stage if any
        indicator_words = [s.split("(")[0].strip() for s in (cls.indicators_found or [])[:3]]
        summary_bits: list[str] = []
        if indicator_words:
            summary_bits.append(", ".join(indicator_words[:2]))
        if analysis.grooming_stage and analysis.grooming_stage.stage != GroomingStage.NONE:
            try:
                stage_idx = GROOMING_STAGE_ORDER.index(analysis.grooming_stage.stage) + 1
                summary_bits.append(f"Stage {stage_idx}/5")
            except ValueError:
                pass
        if not summary_bits:
            summary_bits.append(cls.category.value.replace("_", " "))
        summary = " — ".join(summary_bits)[:96]

        elapsed_label = _format_elapsed((now - analysis.timestamp).total_seconds())

        out.append(
            {
                "analysis_id": analysis_id,
                "time_label": analysis.timestamp.strftime("%H:%M:%S"),
                "time_ago": elapsed_label,
                "platform": analysis.platform or "Unknown",
                "platform_key": _platform_key(analysis.platform),
                "threat_type": cls.category.value,
                "threat_label": cls.category.value.replace("_", " ").title(),
                "severity": severity,
                "confidence": round(cls.confidence),
                "user": user,
                "summary": summary,
                "indicators": [s[:24] for s in (cls.indicators_found or [])[:3]],
                "telegram_sent": analysis.parent_alert is not None,
            }
        )
    return out


def serialize_scan_history(levels: list[str]) -> list[dict[str, str]]:
    """Convert raw threat levels into sparkline payload entries.

    Each entry is ``{"level": "...", "tone": "safe|caution|alert"}`` so the
    JS only has to map ``tone`` to a CSS class.
    """
    out: list[dict[str, str]] = []
    for level in levels:
        if level in ("alert", "critical"):
            tone = "alert"
        elif level in ("caution", "warning"):
            tone = "caution"
        else:
            tone = "safe"
        out.append({"level": level, "tone": tone})
    return out


def format_session_duration(seconds: float) -> str:
    """Render seconds as ``MMm SSs`` for the header."""
    seconds_int = max(0, int(seconds))
    minutes, secs = divmod(seconds_int, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _screenshot_url(analysis: ScreenAnalysis) -> str | None:
    """Translate a local file path into a URL the browser can fetch.

    The FastAPI server mounts ``outputs/screenshots`` at ``/screenshots/``.
    We pass the bare filename so the front-end can build the full URL.
    """
    path = analysis.screenshot_path
    if path is None:
        return None
    return f"/screenshots/{path.name}"


def _platform_key(platform: str | None) -> str:
    """Reduce a possibly messy platform string to a stable key for the JS template picker."""
    if not platform:
        return "unknown"
    lower = platform.lower()
    if "instagram" in lower:
        return "instagram"
    if "tiktok" in lower:
        return "tiktok"
    if "discord" in lower:
        return "discord"
    if "minecraft" in lower or "roblox" in lower:
        return "minecraft"
    return "unknown"


def _threat_breakdown(analysis: ScreenAnalysis) -> list[dict[str, str]]:
    """Build the numbered indicator list for the breakdown card.

    Each entry has ``{title, quote, explanation}``. The quote is pulled
    from the matching :class:`ChatMessage` when available, falling back
    to the indicator string itself.
    """
    indicators = list(analysis.classification.indicators_found)
    if not indicators:
        return []

    chat_messages = analysis.chat_messages or []
    flag_to_text: dict[str, str] = {}
    for msg in chat_messages:
        if msg.flag and msg.flag not in flag_to_text:
            flag_to_text[msg.flag] = msg.text

    out: list[dict[str, str]] = []
    for indicator in indicators[:5]:
        title = indicator.strip()
        # Try to find a quote: look for a chat message whose flag matches
        # this indicator (case-insensitive substring), otherwise leave blank.
        quote = ""
        norm = title.lower()
        for flag, text in flag_to_text.items():
            if flag.lower() in norm or norm in flag.lower():
                quote = text
                break
        out.append(
            {
                "title": title,
                "quote": quote,
                "explanation": _indicator_explanation(title),
            }
        )
    return out


_EXPLANATIONS: dict[str, str] = {
    # More specific phrases come FIRST so they match before generic words.
    "false age": "predator pretending to be a teen",
    "isolation": "moving to an unmonitored channel",
    "discord": "moving to an unmonitored channel",
    "snap": "moving to an unmonitored channel",
    "secret": "creating a hidden channel of communication",
    "secrecy": "creating a hidden channel of communication",
    "image request": "requesting personal images",
    "image": "requesting personal images",
    "photo": "requesting personal images",
    "gift": "building obligation through small gifts",
    "skin": "building obligation through small gifts",
    "compliment": "trust-building flattery",
    "flatter": "trust-building flattery",
    "self-harm": "encouraging self-harm",
    "exclusion": "social isolation pattern",
    "mock": "personal humiliation",
    "humiliat": "personal humiliation",
    "personal info": "gathering personal info to assess vulnerability",
    "personal attack": "personal humiliation",
    "age inquiry": "gathering personal info to assess vulnerability",
    "age": "gathering personal info to assess vulnerability",
}


def _indicator_explanation(indicator: str) -> str:
    """Cheap heuristic — map indicator keywords to a one-line explanation."""
    norm = indicator.lower()
    for key, explanation in _EXPLANATIONS.items():
        if key in norm:
            return explanation
    return "behavior pattern flagged by safety classifier"


_PLATFORM_URLS: dict[str, str] = {
    "instagram": "instagram.com/direct/t/lily_summer",
    "tiktok": "tiktok.com/@xx_proud/comments",
    "discord": "discord.com/channels/482113/general-chat",
    "minecraft": "play.minecraft.net/server/eu-survival",
    "unknown": "—",
}

# Default display names per platform when the chat lines use generic
# "them"/"me" roles instead of real usernames.
_DEFAULT_USERNAMES: dict[str, str] = {
    "instagram": "lily.summer",
    "tiktok": "xx_proud",
    "discord": "ShadowPro",
    "minecraft": "CoolGuy99",
    "unknown": "unknown user",
}

_GENERIC_SENDERS: frozenset[str] = frozenset(
    {"me", "self", "child", "them", "other", "user"}
)


def _conversation_meta(analysis: ScreenAnalysis) -> dict[str, Any]:
    """Identify the 'other party' username + status for the fake browser header.

    Picks the first non-self sender from the chat messages so the
    Instagram/Discord/TikTok header always has a real label to show.
    Falls back to a per-platform default when the scenario only uses
    generic "them"/"me" labels.
    """
    chat_messages = analysis.chat_messages or []
    key = _platform_key(analysis.platform)

    other_username: str | None = None
    for msg in chat_messages:
        sender = msg.sender or ""
        if sender.lower() in _GENERIC_SENDERS:
            continue
        other_username = sender
        break

    display = (other_username or _DEFAULT_USERNAMES.get(key, "unknown user")).lstrip("@<").rstrip(">")
    return {
        "username": display,
        "url": _PLATFORM_URLS.get(key, _PLATFORM_URLS["unknown"]),
        "active_status": "Active now",
        "platform_key": key,
    }


# ----------------------------------------------------------------------- threat breakdown helpers


def _indicator_pills(analysis: ScreenAnalysis) -> list[dict[str, str]]:
    """Per-indicator pills for the threat breakdown card.

    Each pill is ``{label, tone}``. Tone is ``alert`` by default; the
    "false age" indicator gets ``caution`` so it visually distinguishes
    itself in the row of red pills.
    """
    out: list[dict[str, str]] = []
    for indicator in (analysis.classification.indicators_found or [])[:6]:
        norm = indicator.lower()
        tone = "caution" if "false age" in norm else "alert"
        out.append({"label": indicator, "tone": tone})
    return out


def _stage_segments(analysis: ScreenAnalysis) -> dict[str, Any]:
    """Five-segment stage bar payload for the threat breakdown card."""
    if analysis.grooming_stage is None or analysis.grooming_stage.stage == GroomingStage.NONE:
        current_idx = -1
    else:
        try:
            current_idx = GROOMING_STAGE_ORDER.index(analysis.grooming_stage.stage)
        except ValueError:
            current_idx = -1

    segments = []
    for idx, stage in enumerate(GROOMING_STAGE_ORDER):
        if idx < current_idx:
            state = "active"
        elif idx == current_idx:
            state = "current"
        else:
            state = "inactive"
        segments.append(
            {
                "state": state,
                "label": GROOMING_STAGE_LABELS[stage.value],
            }
        )
    return {
        "segments": segments,
        "current_index": current_idx,
    }


# ----------------------------------------------------------------------- right panel generators


def generate_reasoning_chain(
    analysis: ScreenAnalysis,
    history: list[ScreenAnalysis],
) -> list[dict[str, str]]:
    """Build the step-by-step reasoning chain for the right panel.

    Each step is ``{label, text, type}`` where type is one of:
    ``info`` (default text), ``flag`` (highlighted as a flagged finding),
    ``verdict`` (final line in red).
    """
    steps: list[dict[str, str]] = []

    platform = analysis.platform or "Unknown"
    steps.append({"label": "STEP 1", "text": f"Platform: {platform}", "type": "info"})

    chat_messages = analysis.chat_messages or []
    if chat_messages:
        senders: list[str] = []
        seen: set[str] = set()
        has_child = False
        for msg in chat_messages:
            sender_low = (msg.sender or "").lower()
            if sender_low in {"me", "self", "child"}:
                has_child = True
                continue
            if sender_low and sender_low not in seen:
                seen.add(sender_low)
                senders.append(msg.sender)
        participants = senders[:3]
        if has_child:
            participants.append("child")
        if participants:
            steps.append(
                {
                    "label": "STEP 2",
                    "text": "Participants: " + ", ".join(participants),
                    "type": "info",
                }
            )

    flagged = [m for m in chat_messages if m.flag]
    if flagged:
        steps.append({"label": "STEP 3", "text": "Threat scan results:", "type": "info"})
        for msg in flagged[:5]:
            quote = msg.text if len(msg.text) <= 42 else msg.text[:39] + "..."
            steps.append(
                {
                    "label": "",
                    "text": f'→ "{quote}" [{msg.flag}]',
                    "type": "flag",
                }
            )
    elif analysis.classification.indicators_found:
        steps.append({"label": "STEP 3", "text": "Threat scan results:", "type": "info"})
        for indicator in analysis.classification.indicators_found[:4]:
            steps.append(
                {
                    "label": "",
                    "text": f"→ [{indicator}]",
                    "type": "flag",
                }
            )

    if history:
        first_unsafe = next(
            (h for h in history if h.classification.threat_level != ThreatLevel.SAFE),
            None,
        )
        if (
            first_unsafe is not None
            and first_unsafe.timestamp < analysis.timestamp
        ):
            steps.append(
                {"label": "STEP 4", "text": "Cross-reference previous scans:", "type": "info"}
            )
            steps.append(
                {
                    "label": "",
                    "text": (
                        f"→ {first_unsafe.timestamp.strftime('%H:%M')} flagged "
                        f"{first_unsafe.classification.threat_level.value.upper()} → "
                        f"{analysis.timestamp.strftime('%H:%M')} escalated"
                    ),
                    "type": "info",
                }
            )

    stage_str = ""
    if analysis.grooming_stage is not None and analysis.grooming_stage.stage != GroomingStage.NONE:
        try:
            stage_idx = GROOMING_STAGE_ORDER.index(analysis.grooming_stage.stage) + 1
            stage_str = f" {stage_idx}/5"
        except ValueError:
            stage_str = ""
    verdict_text = (
        f"{analysis.classification.threat_level.value.upper()} — "
        f"{analysis.classification.category.value}{stage_str} — "
        f"{round(analysis.classification.confidence)}%"
    )
    steps.append({"label": "VERDICT", "text": verdict_text, "type": "verdict"})

    return steps


def generate_why_this_matters(analysis: ScreenAnalysis) -> str:
    """One-paragraph explanation rendered with a red left-border accent."""
    cls = analysis.classification
    if cls.threat_level == ThreatLevel.SAFE:
        return ""

    indicator_count = len(cls.indicators_found)

    if cls.category == ThreatCategory.GROOMING:
        stage_label = ""
        if (
            analysis.grooming_stage is not None
            and analysis.grooming_stage.stage != GroomingStage.NONE
        ):
            try:
                stage_idx = GROOMING_STAGE_ORDER.index(analysis.grooming_stage.stage) + 1
                stage_label = (
                    f" This matches stage {stage_idx} of the recognized "
                    f"grooming progression."
                )
            except ValueError:
                stage_label = ""
        return (
            f"The user employed {indicator_count} grooming techniques in a single "
            f"conversation: flattery, lying about age, attempting isolation to an "
            f"unmonitored platform, and offering material incentives.{stage_label}"
        )

    if cls.category == ThreatCategory.BULLYING:
        return (
            f"Repeated targeted harassment with {indicator_count} indicators in a "
            f"single conversation. Patterns include exclusion, personal attacks, and "
            f"public humiliation — all hallmarks of sustained cyberbullying."
        )

    if cls.category == ThreatCategory.INAPPROPRIATE_CONTENT:
        return (
            f"Content unsuitable for the child's age was detected. {indicator_count} "
            f"explicit indicators were flagged in this capture."
        )

    if cls.category == ThreatCategory.PERSONAL_INFO_SHARING:
        return (
            f"The child appears to be sharing personal information that could be used "
            f"to identify them offline ({indicator_count} indicators)."
        )

    return (
        f"{indicator_count} risk indicators were flagged in this conversation. "
        f"Review the breakdown for details."
    )


def generate_recommended_action(
    analysis: ScreenAnalysis,
) -> dict[str, Any] | None:
    """Three-step action plan + privacy note shown in the purple card."""
    cls = analysis.classification
    if cls.threat_level == ThreatLevel.SAFE:
        return None

    other_user = "this user"
    if analysis.chat_messages:
        for msg in analysis.chat_messages:
            sender_low = (msg.sender or "").lower()
            if sender_low and sender_low not in _GENERIC_SENDERS:
                other_user = f'"{msg.sender}"'
                break

    privacy_note = (
        "No chat content was shared with you. Only AI-generated analysis is shown. "
        "Your child's privacy is preserved."
    )

    if cls.category == ThreatCategory.GROOMING:
        steps = [
            "Have a calm conversation with your child about this interaction.",
            f"Ask who {other_user} is — they may or may not know this person.",
            "Block and report this user together with your child.",
        ]
    elif cls.category == ThreatCategory.BULLYING:
        steps = [
            "Check in with your child gently — ask how their day was.",
            "Don't ask leading questions; let them volunteer the conversation.",
            "If they confirm bullying, help them block and document the offenders.",
        ]
    elif cls.category == ThreatCategory.PERSONAL_INFO_SHARING:
        steps = [
            "Talk to your child about why personal info should stay private.",
            "Review their privacy settings together on this platform.",
            "Make a habit of checking in weekly without judgment.",
        ]
    else:
        steps = [
            "Review the threat breakdown above carefully.",
            "Check whether the pattern repeats in the next few minutes.",
            "Take action only if the behavior continues.",
        ]

    return {"steps": steps, "privacy_note": privacy_note}
