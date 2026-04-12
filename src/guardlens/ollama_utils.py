"""Shared helpers for parsing Ollama chat responses.

Both :class:`GuardLensAnalyzer` (vision) and :class:`ConversationAnalyzer`
(text-only) need to pluck tool calls out of an Ollama response. The SDK
may return either attribute-style objects (newer SDK) or plain dicts, so
we normalize early and let callers work with plain ``dict`` s.
"""

from __future__ import annotations

from typing import Any


def get_message(response: Any) -> dict[str, Any]:
    """Extract the assistant message from an Ollama response as a plain dict.

    Handles both attribute-style (``response.message``) and dict-style
    (``response["message"]``) responses.  Returns an empty dict when
    the response structure is unrecognized.
    """
    if response is None:
        return {}
    if hasattr(response, "message"):
        message = response.message
    elif isinstance(response, dict) and "message" in response:
        message = response["message"]
    else:
        return {}

    if hasattr(message, "model_dump"):
        return message.model_dump()
    if isinstance(message, dict):
        return message
    return {}


def get_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize tool calls into ``[{"name": ..., "arguments": ...}]``.

    Handles nested ``{"function": {"name": ..., "arguments": ...}}``
    format used by Ollama's function-calling responses.
    """
    raw_calls = message.get("tool_calls") or []
    normalized: list[dict[str, Any]] = []
    for call in raw_calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            continue
        normalized.append(
            {
                "name": function.get("name", ""),
                "arguments": function.get("arguments") or {},
            }
        )
    return normalized


def find_call(tool_calls: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Find the arguments dict for the first tool call matching ``name``."""
    for call in tool_calls:
        if call["name"] == name:
            args = call["arguments"]
            return args if isinstance(args, dict) else None
    return None


def extract_thinking(message: dict[str, Any]) -> str | None:
    """Best-effort extraction of the model's thinking trace or content."""
    thinking = message.get("thinking")
    if isinstance(thinking, str) and thinking.strip():
        return thinking
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None
