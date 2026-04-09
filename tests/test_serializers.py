"""Tests for the JSON serializers consumed by the FastAPI front-end."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.serializers import (
    GROOMING_STAGE_ORDER,
    empty_summary,
    format_session_duration,
    serialize_analysis,
    serialize_stage,
    serialize_timeline,
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
    assert payload["indicators"] == ["asked age", "proposed Discord DM", "offered free items"]


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


def test_serialize_timeline_orders_newest_first() -> None:
    a = _analysis(ThreatLevel.SAFE)
    b = _analysis(ThreatLevel.ALERT)
    payload = serialize_timeline([a, b])
    assert len(payload) == 2
    # b was added second, so it should appear first after reversal.
    assert payload[0]["threat_level"] == "alert"
    assert payload[1]["threat_level"] == "safe"


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
