"""End-to-end style smoke tests that don't require a running Ollama server.

These exercise the analyzer's response parser and the worker's
queue/database side effects against a synthetic Ollama response. If any of
these fail, the live demo will fail too — they are intentionally cheap so
they can run on every commit.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from guardlens.analyzer import GuardLensAnalyzer
from guardlens.config import OllamaConfig
from guardlens.schema import ScreenAnalysis, ThreatLevel
from guardlens.session_tracker import SessionTracker
from guardlens.config import SessionConfig


_FAKE_OLLAMA_RESPONSE: dict[str, Any] = {
    "message": {
        "role": "assistant",
        "content": "I see a Minecraft chat where 'CoolGuy99' is asking the child for their age...",
        "tool_calls": [
            {
                "function": {
                    "name": "classify_threat",
                    "arguments": {
                        "threat_level": "alert",
                        "category": "grooming",
                        "confidence": 89.0,
                        "reasoning": "User asked age, then proposed Discord DM, then offered free skins.",
                        "indicators_found": [
                            "asked age",
                            "proposed Discord DM",
                            "offered free items",
                        ],
                        "platform_detected": "Minecraft",
                    },
                }
            },
            {
                "function": {
                    "name": "identify_grooming_stage",
                    "arguments": {
                        "stage": "trust_building",
                        "evidence": ["asked age", "offered gifts"],
                        "risk_escalation": True,
                    },
                }
            },
            {
                "function": {
                    "name": "generate_parent_alert",
                    "arguments": {
                        "alert_title": "Suspicious contact in Minecraft",
                        "summary": "An unknown user is asking the child personal questions and offering gifts.",
                        "recommended_action": "Pause the session and talk to your child.",
                        "urgency": "high",
                    },
                }
            },
        ],
    }
}


def test_analyzer_parses_full_tool_chain(tmp_path: Path) -> None:
    """The analyzer should turn a happy-path Ollama response into a typed result."""
    image = tmp_path / "fake.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    analyzer = GuardLensAnalyzer(OllamaConfig())

    with patch.object(analyzer._client, "chat", return_value=_FAKE_OLLAMA_RESPONSE):
        result = analyzer.analyze(image)

    assert isinstance(result, ScreenAnalysis)
    assert result.classification.threat_level == ThreatLevel.ALERT
    assert result.classification.platform_detected == "Minecraft"
    assert result.platform == "Minecraft"
    assert result.grooming_stage is not None
    assert result.grooming_stage.risk_escalation is True
    assert result.parent_alert is not None
    assert result.needs_parent_attention is True


def _fake_analysis(level: ThreatLevel) -> ScreenAnalysis:
    return ScreenAnalysis.model_validate(
        {
            "timestamp": datetime.now(),
            "screenshot_path": "/tmp/fake.png",
            "classification": {
                "threat_level": level.value,
                "category": "grooming" if level != ThreatLevel.SAFE else "none",
                "confidence": 90.0,
                "reasoning": "synthetic",
                "indicators_found": [],
            },
            "inference_seconds": 0.1,
        }
    )


def test_session_tracker_detects_escalation() -> None:
    """Two consecutive non-safe analyses should trip the escalation flag."""
    session = SessionTracker(SessionConfig(window_size=5, escalation_threshold=2))
    session.add(_fake_analysis(ThreatLevel.ALERT))
    assert session.has_escalating_pattern() is False
    session.add(_fake_analysis(ThreatLevel.ALERT))
    assert session.has_escalating_pattern() is True


def test_session_tracker_resets_on_safe() -> None:
    """A SAFE verdict in between two ALERTs should reset the streak."""
    session = SessionTracker(SessionConfig(window_size=5, escalation_threshold=2))
    session.add(_fake_analysis(ThreatLevel.ALERT))
    session.add(_fake_analysis(ThreatLevel.SAFE))
    session.add(_fake_analysis(ThreatLevel.ALERT))
    assert session.consecutive_unsafe() == 1
    assert session.has_escalating_pattern() is False
