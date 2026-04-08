"""Round-trip tests for the SQLite analysis store."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from guardlens.database import GuardLensDatabase
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
        timestamp=datetime.now(),
        screenshot_path=Path("/tmp/x.png"),
        platform="Minecraft",
        classification=ThreatClassification(
            threat_level=level,
            category=ThreatCategory.NONE if level == ThreatLevel.SAFE else ThreatCategory.GROOMING,
            confidence=88.0,
            reasoning="ok",
            indicators_found=["age question", "private DM proposal"],
            platform_detected="Minecraft",
        ),
        grooming_stage=GroomingStageResult(
            stage=GroomingStage.TRUST_BUILDING,
            evidence=["asked for age", "offered free items"],
            risk_escalation=True,
        )
        if level != ThreatLevel.SAFE
        else None,
        parent_alert=ParentAlert(
            alert_title="Suspicious contact",
            summary="A user is attempting to build trust and isolate the child.",
            recommended_action="Pause the session and talk to your child.",
            urgency=AlertUrgency.HIGH,
        )
        if level != ThreatLevel.SAFE
        else None,
        inference_seconds=0.42,
    )


def test_analysis_round_trip(tmp_path: Path) -> None:
    db = GuardLensDatabase(tmp_path / "test.db")
    db.start_session(notes="unit test")
    safe_id = db.record_analysis(_analysis(ThreatLevel.SAFE))
    alert = _analysis(ThreatLevel.ALERT)
    alert_analysis_id = db.record_analysis(alert)
    db.record_alert(alert_analysis_id, alert, delivered=True)

    rows = db.recent_analyses(limit=10)
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {safe_id, alert_analysis_id}

    alerts = db.recent_alerts(limit=10)
    assert len(alerts) == 1
    assert alerts[0]["urgency"] == "high"
    assert alerts[0]["delivered"] == 1

    summary = db.session_summary()
    assert summary["safe"] == 1
    assert summary["alert"] == 1

    db.end_session()
    db.close()
