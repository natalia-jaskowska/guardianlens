"""Tests for the JSON serializers consumed by the FastAPI front-end."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.serializers import (
    GROOMING_STAGE_ORDER,
    _clean_indicator,
    _dedup_indicators,
    build_alert_history,
    empty_summary,
    format_session_duration,
    serialize_analysis,
    serialize_stage,
    session_totals,
)

from guardlens.schema import (
    AlertUrgency,
    GroomingStage,
    GroomingStageResult,
    ParentAlert,
    ScreenAnalysis,
    ThreatCategory,
    ThreatClassification,
    ThreatLevel,
)


def _analysis(level: ThreatLevel = ThreatLevel.SAFE) -> ScreenAnalysis:
    return ScreenAnalysis(
        timestamp=datetime(2026, 4, 8, 14, 32, 17),
        screenshot_path=Path("/tmp/outputs/screenshots/capture_1234567890.png"),
        platform="Minecraft",
        classification=ThreatClassification(
            threat_level=level,
            category=ThreatCategory.GROOMING if level != ThreatLevel.SAFE else ThreatCategory.NONE,
            confidence=88.5,
            reasoning="User asked age, then proposed Discord DM, then offered free skins.",
            indicators_found=["asked age", "proposed Discord DM", "offered free items"],
            platform_detected="Minecraft",
        ),
        grooming_stage=GroomingStageResult(
            stage=GroomingStage.ISOLATION,
            evidence=["wanna add me on discord"],
            risk_escalation=True,
        )
        if level != ThreatLevel.SAFE
        else None,
        parent_alert=ParentAlert(
            alert_title="Suspicious contact",
            summary="A user attempted to move the conversation off-platform.",
            recommended_action="Pause the session and talk to your child.",
            urgency=AlertUrgency.HIGH,
        )
        if level != ThreatLevel.SAFE
        else None,
        inference_seconds=11.27,
    )


def test_serialize_analysis_safe() -> None:
    payload = serialize_analysis(_analysis(ThreatLevel.SAFE))
    assert payload["threat_level"] == "safe"
    assert payload["category"] == "none"
    assert payload["confidence"] == 88  # rounded (banker's rounding: 88.5 -> 88)
    assert payload["platform"] == "Minecraft"
    assert payload["screenshot_url"] == "/screenshots/capture_1234567890.png"
    assert payload["time_label"] == "14:32:17"
    assert payload["is_alert"] is False
    assert payload["grooming_stage"] is None
    assert payload["parent_alert"] is None
    assert payload["indicators"] == ["Age Inquiry", "Platform Switch", "Gift Offer"]


def test_serialize_analysis_alert_with_stage_and_parent_alert() -> None:
    payload = serialize_analysis(_analysis(ThreatLevel.ALERT))
    assert payload["threat_level"] == "alert"
    assert payload["category"] == "grooming"
    assert payload["category_label"] == "GROOMING"
    assert payload["is_alert"] is True
    # Stage payload
    stage = payload["grooming_stage"]
    assert stage is not None
    assert stage["current"] == "isolation"
    assert stage["current_index"] == 2
    assert len(stage["segments"]) == 5
    assert stage["segments"][0]["state"] == "active"  # targeting
    assert stage["segments"][1]["state"] == "active"  # trust_building
    assert stage["segments"][2]["state"] == "current"  # isolation
    assert stage["segments"][3]["state"] == "inactive"  # desensitization
    # Parent alert
    pa = payload["parent_alert"]
    assert pa is not None
    assert pa["urgency"] == "high"
    assert pa["title"] == "Suspicious contact"


def test_serialize_stage_none() -> None:
    stage = serialize_stage(GroomingStage.NONE)
    assert stage["current_index"] == -1
    assert all(seg["state"] == "inactive" for seg in stage["segments"])


def test_serialize_stage_first_and_last() -> None:
    first = serialize_stage(GroomingStage.TARGETING)
    assert first["current_index"] == 0
    assert first["segments"][0]["state"] == "current"
    assert all(seg["state"] == "inactive" for seg in first["segments"][1:])

    last = serialize_stage(GroomingStage.MAINTAINING_CONTROL)
    assert last["current_index"] == len(GROOMING_STAGE_ORDER) - 1
    assert all(seg["state"] == "active" for seg in last["segments"][:-1])
    assert last["segments"][-1]["state"] == "current"



def test_session_totals_aggregates_caution_and_alert() -> None:
    summary = {"safe": 12, "caution": 1, "warning": 2, "alert": 1, "critical": 1}
    totals = session_totals(summary)
    assert totals["screenshots"] == 17
    assert totals["safe"] == 12
    assert totals["caution"] == 3  # caution + warning
    assert totals["alerts"] == 2  # alert + critical


def test_empty_summary_has_all_levels() -> None:
    summary = empty_summary()
    assert set(summary) == {"safe", "caution", "warning", "alert", "critical"}
    assert all(v == 0 for v in summary.values())


def test_format_session_duration() -> None:
    assert format_session_duration(0) == "0m 00s"
    assert format_session_duration(45) == "0m 45s"
    assert format_session_duration(872) == "14m 32s"
    assert format_session_duration(3661) == "1h 01m 01s"


def test_build_alert_history_grooming_stage_index() -> None:
    """Alert history cards include the real grooming_stage_index."""
    alert_analysis = _analysis(ThreatLevel.ALERT)
    rows = [(1, 1, alert_analysis)]
    history = build_alert_history(rows)
    assert len(history) == 1
    card = history[0]
    # Isolation is index 2 in the 0-based order → 1-based = 3
    assert card["grooming_stage_index"] == 3
    assert card["threat_type"] == "grooming"
    assert card["analysis_id"] == 1


def test_build_alert_history_no_grooming_stage_index() -> None:
    """Alert history cards with no grooming stage default to 0."""
    safe = _analysis(ThreatLevel.SAFE)
    # Force it to look like an alert for the history builder
    alert_no_grooming = safe.model_copy(
        update={
            "classification": ThreatClassification(
                threat_level=ThreatLevel.ALERT,
                category=ThreatCategory.BULLYING,
                confidence=92.0,
                reasoning="Repeated insults.",
                indicators_found=["name-calling"],
            ),
        }
    )
    rows = [(2, 1, alert_no_grooming)]
    history = build_alert_history(rows)
    assert len(history) == 1
    assert history[0]["grooming_stage_index"] == 0


# --- _clean_indicator ---------------------------------------------------------


def test_clean_indicator_maps_known_keywords_to_title_case_tags() -> None:
    # "Asking about" matches first → Personal Info
    assert _clean_indicator("Asking about location") == "Personal Info"
    # "age" word-boundary matches
    assert _clean_indicator("Age confirmation") == "False Age"
    assert _clean_indicator("Suggesting moving to Discord") == "Platform Switch"
    assert _clean_indicator("Request for secrecy") == "Secrecy"
    assert _clean_indicator("False age claim") == "False Age"
    assert _clean_indicator("Excessive compliments") == "Flattery"
    assert _clean_indicator("Offering free skins") == "Gift Offer"


def test_clean_indicator_strips_quotes_and_parentheticals() -> None:
    assert _clean_indicator('Name-calling ("ur so cringe")') == "Name-Calling"
    # Keywords are checked against the whole text including parenthetical,
    # so "isolat" in "Isolation attempt" matches before the paren is stripped
    assert _clean_indicator("Isolation attempt") == "Isolation"


def test_clean_indicator_word_boundary_avoids_false_matches() -> None:
    # "age" should not match "image" or "messages"
    assert _clean_indicator("Image request") == "Image Request"
    assert _clean_indicator("Threatening messages") == "Threats"


def test_clean_indicator_fallback_produces_title_case() -> None:
    """Unknown indicators get first 3 words in Title Case, no ellipsis."""
    result = _clean_indicator("Some completely unknown behavior pattern")
    assert result == "Some Completely Unknown"
    assert "…" not in result
    assert "..." not in result


def test_clean_indicator_empty_returns_none() -> None:
    assert _clean_indicator("") is None
    assert _clean_indicator("   ") is None


# --- _dedup_indicators --------------------------------------------------------


def test_dedup_indicators_removes_duplicate_tags() -> None:
    """Multiple raw indicators that map to the same tag only appear once."""
    raw = [
        "Excessive compliments",
        "Excessive flattery",
        "Compliments used to build rapport",
    ]
    result = _dedup_indicators(raw)
    # Flattery appears exactly once even though three raw strings map to it
    assert result.count("Flattery") == 1
    assert len(result) == 1


def test_dedup_indicators_preserves_order() -> None:
    """Tags appear in the order their first raw indicator appears."""
    raw = ["Flattery compliments", "Isolation to Discord", "Secrecy request"]
    result = _dedup_indicators(raw)
    assert result == ["Flattery", "Platform Switch", "Secrecy"]


def test_dedup_indicators_filters_empty() -> None:
    """Empty or unmappable-to-nothing indicators get dropped."""
    raw = ["", "Flattery", "   ", "Isolation"]
    result = _dedup_indicators(raw)
    assert result == ["Flattery", "Isolation"]


