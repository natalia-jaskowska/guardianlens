"""Smoke tests for the analyzer and the new conversation pipeline.

These exercise the analyzer's response parser and the pipeline's
DB persistence without requiring a running Ollama server.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from guardlens.analyzer import GuardLensAnalyzer
from guardlens.config import GuardLensConfig, OllamaConfig
from guardlens.database import GuardLensDatabase
from guardlens.pipeline import ConversationPipeline, _naive_merge
from guardlens.schema import (
    FrameAnalysis,
    ScreenAnalysis,
    ThreatLevel,
)


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



# ---------------------------------------------------------------------------
# Pipeline unit tests
# ---------------------------------------------------------------------------


def test_naive_merge_deduplicates() -> None:
    prior = [{"sender": "Alice", "text": "hello"}, {"sender": "Bob", "text": "hi"}]
    new = [{"sender": "Bob", "text": "hi"}, {"sender": "Carol", "text": "hey"}]
    result = _naive_merge(prior, new)
    assert len(result) == 3
    assert result[0]["sender"] == "Alice"
    assert result[2]["sender"] == "Carol"


def test_naive_merge_case_insensitive() -> None:
    prior = [{"sender": "Alice", "text": "Hello"}]
    new = [{"sender": "alice", "text": "hello"}]
    result = _naive_merge(prior, new)
    assert len(result) == 1


def test_db_conversation_crud(tmp_path: Path) -> None:
    """Test create/read/update cycle for the conversations table."""
    db = GuardLensDatabase(tmp_path / "test.db")

    now = datetime.now().isoformat()
    conv_id = db.create_conversation(
        platform="discord",
        participants=["Alice", "Bob"],
        first_seen=now,
        messages=[{"sender": "Alice", "text": "hi"}],
        screenshots=[{"path": "/tmp/1.png", "timestamp": now}],
        status={"threat_level": "safe", "category": "none", "confidence": 90},
        status_reasoning="All clear",
    )
    assert conv_id > 0

    row = db.get_conversation(conv_id)
    assert row is not None
    assert row["platform"] == "discord"

    import json
    assert json.loads(row["participants_json"]) == ["Alice", "Bob"]

    db.update_conversation(
        conv_id,
        messages_json=json.dumps([
            {"sender": "Alice", "text": "hi"},
            {"sender": "Bob", "text": "hello"},
        ]),
        status_json=json.dumps({"threat_level": "caution", "confidence": 70}),
        status_reasoning="Watching",
        screenshots_json=json.dumps([
            {"path": "/tmp/1.png", "timestamp": now},
            {"path": "/tmp/2.png", "timestamp": now},
        ]),
        last_seen=now,
    )

    updated = db.get_conversation(conv_id)
    assert json.loads(updated["status_json"])["threat_level"] == "caution"
    assert len(json.loads(updated["messages_json"])) == 2

    active = db.get_active_conversations(stale_minutes=9999)
    assert len(active) >= 1

    all_convs = db.all_conversations()
    assert len(all_convs) >= 1

    frag_id = db.insert_fragment(
        conversation_id=conv_id,
        timestamp="2026-01-01T00:00:00",
        screenshot_path="/tmp/1.png",
        raw_analysis_json='{"test": true}',
    )
    assert frag_id > 0


def test_pipeline_frame_analysis_fallback(tmp_path: Path) -> None:
    """When the model doesn't call extract_conversations, pipeline returns empty."""
    pipeline = ConversationPipeline(OllamaConfig())
    image = tmp_path / "fake.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    empty_response = {"message": {"role": "assistant", "content": "no tools", "tool_calls": []}}

    with patch.object(pipeline._client, "chat", return_value=empty_response):
        frame = pipeline._analyze_frame(image)

    assert isinstance(frame, FrameAnalysis)
    assert frame.conversations == []


def test_pipeline_push_screenshot_empty_frame(tmp_path: Path) -> None:
    """push_screenshot with no conversations detected returns empty list."""
    pipeline = ConversationPipeline(OllamaConfig())
    db = GuardLensDatabase(tmp_path / "test.db")
    db.start_session()
    image = tmp_path / "fake.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    empty_response = {"message": {"role": "assistant", "content": "", "tool_calls": []}}

    with patch.object(pipeline._client, "chat", return_value=empty_response):
        result = pipeline.push_screenshot(image, db)

    assert result == []
    assert db.all_conversations() == []
