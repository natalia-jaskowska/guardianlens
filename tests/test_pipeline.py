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
from unittest.mock import MagicMock, patch

from guardlens.analyzer import GuardLensAnalyzer
from guardlens.config import GuardLensConfig, OllamaConfig, SessionConfig
from guardlens.conversation_store import ConversationStore
from guardlens.schema import (
    ChatMessage,
    ScreenAnalysis,
    SessionCertainty,
    SessionVerdict,
    ThreatCategory,
    ThreatLevel,
)
from guardlens.session_tracker import SessionTracker


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


# ---------------------------------------------------------------------------
# Conversation analyzer trigger tests
# ---------------------------------------------------------------------------


def _make_worker(tmp_path: Path) -> Any:
    """Build a MonitorWorker with mocked Ollama for trigger testing."""
    from app.state import MonitorWorker

    cfg = GuardLensConfig()
    cfg.database.path = tmp_path / "test.db"
    cfg.monitor.screenshots_dir = tmp_path / "screenshots"
    cfg.monitor.screenshots_dir.mkdir()

    from guardlens.alerts import AlertSender
    from guardlens.analyzer import GuardLensAnalyzer
    from guardlens.conversation_analyzer import ConversationAnalyzer
    from guardlens.database import GuardLensDatabase

    analyzer = GuardLensAnalyzer(cfg.ollama)
    session = SessionTracker(cfg.session)
    alerts = AlertSender(cfg.alerts)
    database = GuardLensDatabase(cfg.database.path)
    database.start_session()
    store = ConversationStore()
    conv_analyzer = ConversationAnalyzer(cfg.ollama)

    worker = MonitorWorker(
        config=cfg,
        analyzer=analyzer,
        session=session,
        alerts=alerts,
        database=database,
        conversation_store=store,
        conversation_analyzer=conv_analyzer,
    )
    return worker


def _fake_analysis_with_messages(
    level: ThreatLevel,
    messages: list[tuple[str, str]] | None = None,
) -> ScreenAnalysis:
    msgs = messages or [("Alice", "hello")]
    return ScreenAnalysis(
        timestamp=datetime.now(),
        screenshot_path=Path("/tmp/fake.png"),
        classification={
            "threat_level": level.value,
            "category": "grooming" if level != ThreatLevel.SAFE else "none",
            "confidence": 90.0,
            "reasoning": "synthetic",
            "indicators_found": [],
            "visible_messages": [
                {"sender": s, "text": t} for s, t in msgs
            ],
        },
        inference_seconds=0.1,
    )


def test_safe_frame_triggers_reanalysis_when_verdict_is_stale(tmp_path: Path) -> None:
    """A safe frame should re-trigger the conversation analyzer when the
    current verdict is non-safe, so the verdict can downgrade."""
    worker = _make_worker(tmp_path)

    # Simulate a stale non-safe verdict.
    worker._latest_session_verdict = SessionVerdict(
        overall_level=ThreatLevel.WARNING,
        overall_category=ThreatCategory.GROOMING,
        confidence=85.0,
        certainty=SessionCertainty.MEDIUM,
        narrative="stale",
        messages_analyzed=5,
        parent_alert_recommended=False,
    )

    # Queue a safe frame with unique messages.
    safe = _fake_analysis_with_messages(
        ThreatLevel.SAFE,
        [("Bob", "nice weather"), ("Carol", "yeah!")],
    )
    worker._queue.put(safe)

    # Mock the conversation analyzer to track if it's called.
    with patch.object(worker._conversation_analyzer, "analyze", return_value=None) as mock_analyze:
        worker.drain()

    mock_analyze.assert_called_once()
    # Frame hint should include the safe frame's context.
    call_kwargs = mock_analyze.call_args
    hint = call_kwargs.kwargs.get("frame_hint") or call_kwargs[1].get("frame_hint")
    assert hint is not None
    assert hint["level"] == "safe"


def test_nonsafe_frame_always_triggers_reanalysis(tmp_path: Path) -> None:
    """A non-safe frame should always re-trigger the conversation analyzer,
    regardless of the current verdict level."""
    worker = _make_worker(tmp_path)

    # Simulate an existing non-safe verdict (previously this blocked re-analysis).
    worker._latest_session_verdict = SessionVerdict(
        overall_level=ThreatLevel.ALERT,
        overall_category=ThreatCategory.GROOMING,
        confidence=90.0,
        certainty=SessionCertainty.HIGH,
        narrative="existing",
        messages_analyzed=10,
        parent_alert_recommended=True,
    )

    alert = _fake_analysis_with_messages(
        ThreatLevel.ALERT,
        [("Stranger", "how old are you?")],
    )
    worker._queue.put(alert)

    with patch.object(worker._conversation_analyzer, "analyze", return_value=None) as mock_analyze:
        worker.drain()

    mock_analyze.assert_called_once()
    # Frame hint should carry the alert context.
    call_kwargs = mock_analyze.call_args
    hint = call_kwargs.kwargs.get("frame_hint") or call_kwargs[1].get("frame_hint")
    assert hint is not None
    assert hint["level"] == "alert"


def test_safe_frame_does_not_trigger_when_verdict_already_safe(tmp_path: Path) -> None:
    """When both the frame and the verdict are safe, no re-analysis needed
    (unless enough new messages accumulated via threshold A)."""
    worker = _make_worker(tmp_path)

    worker._latest_session_verdict = SessionVerdict(
        overall_level=ThreatLevel.SAFE,
        overall_category=ThreatCategory.NONE,
        confidence=95.0,
        certainty=SessionCertainty.HIGH,
        narrative="all clear",
        messages_analyzed=10,
        parent_alert_recommended=False,
    )

    # Queue a safe frame with duplicate messages (won't hit threshold A).
    safe = _fake_analysis_with_messages(ThreatLevel.SAFE, [("Alice", "hello")])
    worker._queue.put(safe)

    with patch.object(worker._conversation_analyzer, "analyze", return_value=None) as mock_analyze:
        worker.drain()

    mock_analyze.assert_not_called()
