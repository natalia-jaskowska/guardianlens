"""Round-trip tests for the SQLite analysis store."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

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


def test_total_alert_count_counts_alert_table_rows(tmp_path: Path) -> None:
    """total_alert_count counts rows in the alerts table, not analyses."""
    db = GuardLensDatabase(tmp_path / "test.db")
    db.start_session(notes="unit test")

    # Record analyses without recording alerts — count should be 0.
    db.record_analysis(_analysis(ThreatLevel.ALERT))
    db.record_analysis(_analysis(ThreatLevel.ALERT))
    assert db.total_alert_count() == 0

    # Now actually record alerts.
    alert = _analysis(ThreatLevel.ALERT)
    aid = db.record_analysis(alert)
    db.record_alert(aid, alert, delivered=True)
    assert db.total_alert_count() == 1

    alert2 = _analysis(ThreatLevel.CRITICAL)
    aid2 = db.record_analysis(alert2)
    db.record_alert(aid2, alert2, delivered=False)
    assert db.total_alert_count() == 2

    db.close()


def test_analysis_by_id_returns_none_for_missing(tmp_path: Path) -> None:
    db = GuardLensDatabase(tmp_path / "test.db")
    db.start_session()
    assert db.analysis_by_id(999) is None
    db.close()


def test_analysis_by_id_returns_reconstructed(tmp_path: Path) -> None:
    db = GuardLensDatabase(tmp_path / "test.db")
    db.start_session()
    alert = _analysis(ThreatLevel.ALERT)
    row_id = db.record_analysis(alert)
    restored = db.analysis_by_id(row_id)
    assert restored is not None
    assert restored.classification.threat_level == ThreatLevel.ALERT
    assert restored.classification.category == ThreatCategory.GROOMING
    db.close()


def test_corrupt_json_does_not_crash(tmp_path: Path) -> None:
    """Rows with malformed JSON are skipped, not raised."""
    db = GuardLensDatabase(tmp_path / "test.db")
    db.start_session()

    # Insert a valid analysis first so the DB has a session.
    db.record_analysis(_analysis(ThreatLevel.SAFE))

    # Directly insert a corrupt row.
    with db._lock:
        db._conn.execute(
            """INSERT INTO analyses (
                session_id, timestamp, screenshot_path, platform,
                threat_level, category, confidence, reasoning,
                indicators_found, grooming_stage, inference_seconds, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                db._session_id,
                datetime.now().isoformat(),
                "/tmp/corrupt.png",
                "Test",
                "safe",
                "none",
                50.0,
                "corrupt",
                "[]",
                None,
                0.1,
                '{"invalid": "missing required fields"}',
            ),
        )

    # These should not raise — just skip the corrupt row.
    models = db.recent_analyses_models(limit=10)
    assert len(models) == 1  # only the valid one
    assert db.analysis_by_id(2) is None  # corrupt row returns None
    db.close()


def test_session_id_auto_starts_session(tmp_path: Path) -> None:
    """Accessing session_id before start_session creates one automatically."""
    db = GuardLensDatabase(tmp_path / "test.db")
    assert db._session_id is None
    sid = db.session_id
    assert sid >= 1
    assert db._session_id == sid
    db.close()


def test_record_analysis_without_explicit_start_session(tmp_path: Path) -> None:
    """record_analysis should not deadlock when session_id is unset."""
    db = GuardLensDatabase(tmp_path / "test.db")
    # Don't call start_session — record_analysis must handle it.
    row_id = db.record_analysis(_analysis(ThreatLevel.SAFE))
    assert row_id >= 1
    assert db._session_id is not None
    db.close()


def test_recent_threat_levels_oldest_first(tmp_path: Path) -> None:
    """recent_threat_levels returns oldest first for sparkline rendering."""
    db = GuardLensDatabase(tmp_path / "test.db")
    db.start_session()
    db.record_analysis(_analysis(ThreatLevel.SAFE))
    db.record_analysis(_analysis(ThreatLevel.ALERT))
    db.record_analysis(_analysis(ThreatLevel.CAUTION))

    levels = db.recent_threat_levels(limit=10)
    # Oldest first: SAFE was recorded first.
    assert levels == ["safe", "alert", "caution"]
    db.close()
