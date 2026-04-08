"""Sanity tests for the Pydantic schema models.

These are not exhaustive — they exist so that a quick `pytest` confirms the
type system + validation rules still work after a refactor.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

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


def _make_classification(level: ThreatLevel = ThreatLevel.SAFE) -> ThreatClassification:
    return ThreatClassification(
        threat_level=level,
        category=ThreatCategory.NONE,
        confidence=42.0,
        reasoning="ok",
        indicators_found=[],
    )


def test_confidence_must_be_in_range() -> None:
    with pytest.raises(ValidationError):
        ThreatClassification(
            threat_level=ThreatLevel.SAFE,
            category=ThreatCategory.NONE,
            confidence=200.0,
            reasoning="bad",
        )


def test_screen_analysis_safe_helpers() -> None:
    analysis = ScreenAnalysis(
        timestamp=datetime.now(),
        screenshot_path=Path("/tmp/x.png"),
        classification=_make_classification(ThreatLevel.SAFE),
        inference_seconds=0.1,
    )
    assert analysis.is_safe is True
    assert analysis.needs_parent_attention is False


def test_screen_analysis_alert_helpers() -> None:
    analysis = ScreenAnalysis(
        timestamp=datetime.now(),
        screenshot_path=Path("/tmp/x.png"),
        classification=_make_classification(ThreatLevel.ALERT),
        grooming_stage=GroomingStageResult(stage=GroomingStage.TRUST_BUILDING),
        parent_alert=ParentAlert(
            alert_title="Suspicious contact",
            summary="Pattern detected.",
            recommended_action="Talk to your child.",
            urgency=AlertUrgency.HIGH,
        ),
        inference_seconds=0.5,
    )
    assert analysis.is_safe is False
    assert analysis.needs_parent_attention is True
