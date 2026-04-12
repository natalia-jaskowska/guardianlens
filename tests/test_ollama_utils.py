"""Tests for the shared Ollama response parsing utilities."""

from __future__ import annotations

from guardlens.ollama_utils import extract_thinking, find_call, get_message, get_tool_calls


class _FakeMessage:
    """Simulate the attribute-style SDK response."""

    def __init__(self, content: str, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self) -> dict:
        return {"content": self.content, "tool_calls": self.tool_calls}


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


def test_get_message_from_dict() -> None:
    resp = {"message": {"content": "hello", "tool_calls": []}}
    msg = get_message(resp)
    assert msg["content"] == "hello"


def test_get_message_from_attribute_style() -> None:
    fake_msg = _FakeMessage("hello")
    resp = _FakeResponse(fake_msg)
    msg = get_message(resp)
    assert msg["content"] == "hello"


def test_get_message_returns_empty_for_none() -> None:
    assert get_message(None) == {}


def test_get_message_returns_empty_for_unrecognized() -> None:
    assert get_message(42) == {}


def test_get_tool_calls_normalizes() -> None:
    message = {
        "tool_calls": [
            {
                "function": {
                    "name": "classify_threat",
                    "arguments": {"threat_level": "safe"},
                }
            },
            # Malformed call — should be skipped.
            {"not_a_function": True},
        ]
    }
    calls = get_tool_calls(message)
    assert len(calls) == 1
    assert calls[0]["name"] == "classify_threat"
    assert calls[0]["arguments"]["threat_level"] == "safe"


def test_get_tool_calls_empty_when_missing() -> None:
    assert get_tool_calls({}) == []
    assert get_tool_calls({"tool_calls": None}) == []


def test_find_call_returns_arguments() -> None:
    calls = [
        {"name": "classify_threat", "arguments": {"threat_level": "alert"}},
        {"name": "identify_grooming_stage", "arguments": {"stage": "targeting"}},
    ]
    args = find_call(calls, "classify_threat")
    assert args is not None
    assert args["threat_level"] == "alert"


def test_find_call_returns_none_when_missing() -> None:
    calls = [{"name": "classify_threat", "arguments": {}}]
    assert find_call(calls, "nonexistent") is None


def test_find_call_returns_none_for_non_dict_arguments() -> None:
    calls = [{"name": "classify_threat", "arguments": "not a dict"}]
    assert find_call(calls, "classify_threat") is None


def test_extract_thinking_prefers_thinking_field() -> None:
    msg = {"thinking": "I see a chat window...", "content": "irrelevant"}
    assert extract_thinking(msg) == "I see a chat window..."


def test_extract_thinking_falls_back_to_content() -> None:
    msg = {"content": "I see a chat window..."}
    assert extract_thinking(msg) == "I see a chat window..."


def test_extract_thinking_returns_none_for_empty() -> None:
    assert extract_thinking({}) is None
    assert extract_thinking({"thinking": "", "content": "  "}) is None
