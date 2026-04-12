"""Tests for the ConversationAnalyzer response parsing.

These test the parsing logic against synthetic Ollama responses without
requiring a running Ollama server.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from guardlens.config import OllamaConfig
from guardlens.conversation_analyzer import ConversationAnalyzer
from guardlens.schema import (
    ChatMessage,
    SessionCertainty,
    ThreatCategory,
    ThreatLevel,
)


def _msg(sender: str, text: str) -> ChatMessage:
    return ChatMessage(sender=sender, text=text)


_SAFE_VERDICT_RESPONSE: dict[str, Any] = {
    "message": {
        "role": "assistant",
        "content": "The conversation looks normal.",
        "tool_calls": [
            {
                "function": {
                    "name": "assess_conversation",
                    "arguments": {
                        "overall_level": "safe",
                        "overall_category": "none",
                        "confidence": 95.0,
                        "certainty": "medium",
                        "narrative": "Normal teen conversation.",
                        "key_indicators": [],
                        "parent_alert_recommended": False,
                    },
                }
            }
        ],
    }
}

_GROOMING_VERDICT_RESPONSE: dict[str, Any] = {
    "message": {
        "role": "assistant",
        "content": "Suspicious pattern detected.",
        "tool_calls": [
            {
                "function": {
                    "name": "assess_conversation",
                    "arguments": {
                        "overall_level": "alert",
                        "overall_category": "grooming",
                        "confidence": 88.0,
                        "certainty": "high",
                        "narrative": "ShadowPro asked age, offered gifts, then suggested Discord.",
                        "key_indicators": ["age inquiry", "gift offer", "platform switch"],
                        "parent_alert_recommended": True,
                    },
                }
            }
        ],
    }
}


def test_analyze_safe_verdict() -> None:
    analyzer = ConversationAnalyzer(OllamaConfig())
    messages = [_msg("Alice", "hey"), _msg("Bob", "hi")]

    with patch.object(analyzer._client, "chat", return_value=_SAFE_VERDICT_RESPONSE):
        verdict = analyzer.analyze(messages)

    assert verdict is not None
    assert verdict.overall_level == ThreatLevel.SAFE
    assert verdict.certainty == SessionCertainty.MEDIUM
    assert verdict.parent_alert_recommended is False
    assert verdict.messages_analyzed == 2


def test_analyze_grooming_verdict() -> None:
    analyzer = ConversationAnalyzer(OllamaConfig())
    messages = [_msg("ShadowPro", "how old are you?"), _msg("child", "14")]

    with patch.object(analyzer._client, "chat", return_value=_GROOMING_VERDICT_RESPONSE):
        verdict = analyzer.analyze(messages)

    assert verdict is not None
    assert verdict.overall_level == ThreatLevel.ALERT
    assert verdict.overall_category == ThreatCategory.GROOMING
    assert verdict.certainty == SessionCertainty.HIGH
    assert verdict.parent_alert_recommended is True
    assert len(verdict.key_indicators) == 3


def test_analyze_empty_messages_returns_none() -> None:
    analyzer = ConversationAnalyzer(OllamaConfig())
    assert analyzer.analyze([]) is None


def test_analyze_no_tool_call_returns_none() -> None:
    """When the model doesn't emit assess_conversation, return None."""
    analyzer = ConversationAnalyzer(OllamaConfig())
    no_tool_response = {"message": {"role": "assistant", "content": "thinking..."}}

    with patch.object(analyzer._client, "chat", return_value=no_tool_response):
        verdict = analyzer.analyze([_msg("Alice", "hey")])

    assert verdict is None


def test_analyze_with_frame_hint() -> None:
    """Frame hints are forwarded to the model prompt."""
    analyzer = ConversationAnalyzer(OllamaConfig())
    messages = [_msg("Alice", "hey")]
    hint = {
        "level": "warning",
        "category": "grooming",
        "confidence": "85",
        "reasoning": "Age inquiry detected.",
    }

    with patch.object(analyzer._client, "chat", return_value=_SAFE_VERDICT_RESPONSE) as mock_chat:
        analyzer.analyze(messages, frame_hint=hint)

    # The user prompt should contain the frame hint.
    call_args = mock_chat.call_args
    user_msg = call_args.kwargs["messages"][1]["content"]
    assert "warning" in user_msg
    assert "grooming" in user_msg
