"""Smoke tests for the analyzer and the new conversation pipeline.

These exercise the analyzer's response parser and the pipeline's
DB persistence without requiring a running Ollama server.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image

from guardlens.analyzer import GuardLensAnalyzer
from guardlens.config import OllamaConfig
from guardlens.database import GuardLensDatabase
from guardlens.pipeline import ConversationPipeline, _fuzzy_merge, _score_match
from guardlens.schema import (
    ChatMessage,
    ConversationFragment,
    FrameAnalysis,
    ScreenAnalysis,
    ThreatLevel,
)


def _write_tiny_png(path: Path) -> None:
    Image.new("RGB", (4, 4), "white").save(path)

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
    _write_tiny_png(image)

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


def test_fuzzy_merge_deduplicates() -> None:
    prior = [{"sender": "Alice", "text": "hello"}, {"sender": "Bob", "text": "hi"}]
    new = [{"sender": "Bob", "text": "hi"}, {"sender": "Carol", "text": "hey"}]
    result = _fuzzy_merge(prior, new)
    assert len(result) == 3
    assert result[0]["sender"] == "Alice"
    assert result[2]["sender"] == "Carol"


def test_fuzzy_merge_case_insensitive() -> None:
    prior = [{"sender": "Alice", "text": "Hello"}]
    new = [{"sender": "alice", "text": "hello"}]
    result = _fuzzy_merge(prior, new)
    assert len(result) == 1


def test_fuzzy_merge_ocr_variants() -> None:
    prior = [{"sender": "Kidgamer09", "text": "hey can i come to the movie night?"}]
    new = [
        {"sender": "KidGamer09", "text": "hey can i come to the movie night?"},
        {"sender": "Lyla", "text": "uhh this is invite only"},
    ]
    result = _fuzzy_merge(prior, new)
    assert len(result) == 2


def test_fuzzy_merge_prefix_truncation() -> None:
    prior = [{"sender": "Sammy", "text": "me and jake are doing a science project"}]
    new = [{"sender": "Sammy", "text": "s and jake are doing a science project"}]
    result = _fuzzy_merge(prior, new)
    assert len(result) == 1


def test_fuzzy_merge_keeps_distinct_messages_from_same_sender() -> None:
    prior = [{"sender": "Maxx", "text": "hey"}]
    new = [{"sender": "Maxx", "text": "bye"}]
    result = _fuzzy_merge(prior, new)
    assert len(result) == 2


def test_score_match_merges_on_participant_overlap_with_no_text_overlap() -> None:
    """In-game chat (Minecraft, Roblox) fades older messages out faster
    than the worker resamples. Two consecutive frames may share zero
    message text yet be the same conversation — same platform + same
    named participant should merge.
    """
    fragment = ConversationFragment(
        platform="Minecraft",
        participants=["Steve_2009"],
        messages=[
            ChatMessage(sender="Steve_2009", text="lol"),
            ChatMessage(sender="child", text="ok"),
        ],
    )
    candidate = {
        "id": 42,
        "platform": "Minecraft",
        "participants_json": '["Steve_2009"]',
        "messages_json": '[{"sender":"Steve_2009","text":"hey what server are you on"},'
                         '{"sender":"child","text":"hypixel"}]',
    }
    assert _score_match(fragment, [candidate]) == 42


def test_score_match_does_not_cross_platforms() -> None:
    """Same participant on different platforms must NOT merge."""
    fragment = ConversationFragment(
        platform="Discord",
        participants=["Steve_2009"],
        messages=[ChatMessage(sender="Steve_2009", text="yo")],
    )
    candidate = {
        "id": 1,
        "platform": "Minecraft",
        "participants_json": '["Steve_2009"]',
        "messages_json": '[{"sender":"Steve_2009","text":"hey"}]',
    }
    assert _score_match(fragment, [candidate]) is None


def test_score_match_dm_platform_no_overlap_no_merge() -> None:
    """For DM-style platforms (TikTok, Discord), same platform but different
    participants with no text overlap must NOT merge — different threads."""
    fragment = ConversationFragment(
        platform="TikTok",
        participants=["Alex"],
        messages=[ChatMessage(sender="Alex", text="lol")],
    )
    candidate = {
        "id": 1,
        "platform": "TikTok",
        "participants_json": '["Steve_2009"]',
        "messages_json": '[{"sender":"Steve_2009","text":"hey"}]',
    }
    assert _score_match(fragment, [candidate]) is None


def test_score_match_global_chat_merges_disjoint_participants() -> None:
    """Minecraft / Roblox / etc. show a rolling chat window — different
    speakers per frame is normal. When chat_type='global', a same-platform
    candidate should merge even with zero participant or text overlap."""
    fragment = ConversationFragment(
        platform="Minecraft",
        chat_type="global",
        participants=["Bymonkee"],
        messages=[ChatMessage(sender="Bymonkee", text="check this out")],
    )
    candidate = {
        "id": 7,
        "platform": "Minecraft",
        "participants_json": '["Jake"]',
        "messages_json": '[{"sender":"Jake","text":"omg"}]',
    }
    assert _score_match(fragment, [candidate]) == 7


def test_score_match_global_chat_picks_most_recent_candidate() -> None:
    """When multiple same-platform candidates exist, the matcher should
    pick the most recently updated. The DB query orders DESC by last_seen,
    so the candidate at index 0 is most recent. Verify the matcher honors
    that ordering even when scores tie at zero."""
    fragment = ConversationFragment(
        platform="Minecraft",
        chat_type="global",
        participants=["Liam"],
        messages=[ChatMessage(sender="Liam", text="gg")],
    )
    most_recent = {
        "id": 9,
        "platform": "Minecraft",
        "participants_json": '["Bymonkee"]',
        "messages_json": '[{"sender":"Bymonkee","text":"omg"}]',
    }
    older = {
        "id": 3,
        "platform": "Minecraft",
        "participants_json": '["Jake"]',
        "messages_json": '[{"sender":"Jake","text":"hey"}]',
    }
    # Candidates passed in DB order: most-recent first.
    assert _score_match(fragment, [most_recent, older]) == 9


def test_score_match_chat_type_global_overrides_unknown_platform() -> None:
    """When the model classifies chat_type='global' on an unknown platform
    (one not in the hardcoded fallback list), the matcher should still
    treat it as global chat. The whole point of the new field is to let
    the model decide instead of the hardcoded list."""
    fragment = ConversationFragment(
        platform="SomeNewGame",       # NOT in _GLOBAL_CHAT_PLATFORM_HINTS
        chat_type="global",            # but the model said global
        participants=["Alpha"],
        messages=[ChatMessage(sender="Alpha", text="gg")],
    )
    candidate = {
        "id": 11,
        "platform": "SomeNewGame",
        "participants_json": '["Beta"]',
        "messages_json": '[{"sender":"Beta","text":"hey"}]',
    }
    assert _score_match(fragment, [candidate]) == 11


def test_score_match_chat_type_dm_keeps_strict_gate_even_for_minecraft() -> None:
    """Inverse: if the model labels something Minecraft as a DM (e.g.
    Minecraft Realms private message), the strict gate applies — no
    merge without participant or text overlap."""
    fragment = ConversationFragment(
        platform="Minecraft",
        chat_type="dm",                # model says it's a DM
        participants=["Alex"],
        messages=[ChatMessage(sender="Alex", text="lol")],
    )
    candidate = {
        "id": 1,
        "platform": "Minecraft",
        "participants_json": '["Steve_2009"]',
        "messages_json": '[{"sender":"Steve_2009","text":"hey"}]',
    }
    assert _score_match(fragment, [candidate]) is None


def test_score_match_unknown_participant_does_not_block_merge() -> None:
    """A fragment whose participant is the placeholder 'Unknown' should
    still merge into a real Minecraft conversation via the global-chat
    rule (platform alone)."""
    fragment = ConversationFragment(
        platform="Minecraft",
        chat_type="global",
        participants=["Unknown"],
        messages=[ChatMessage(sender="Unknown", text="lol")],
    )
    candidate = {
        "id": 4,
        "platform": "Minecraft",
        "participants_json": '["Jake"]',
        "messages_json": '[{"sender":"Jake","text":"hey"}]',
    }
    assert _score_match(fragment, [candidate]) == 4


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
        messages_json=json.dumps(
            [
                {"sender": "Alice", "text": "hi"},
                {"sender": "Bob", "text": "hello"},
            ]
        ),
        status_json=json.dumps({"threat_level": "caution", "confidence": 70}),
        status_reasoning="Watching",
        screenshots_json=json.dumps(
            [
                {"path": "/tmp/1.png", "timestamp": now},
                {"path": "/tmp/2.png", "timestamp": now},
            ]
        ),
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
    _write_tiny_png(image)

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
    _write_tiny_png(image)

    empty_response = {"message": {"role": "assistant", "content": "", "tool_calls": []}}

    with patch.object(pipeline._client, "chat", return_value=empty_response):
        result = pipeline.push_screenshot(image, db)

    assert result == []
    assert db.all_conversations() == []
