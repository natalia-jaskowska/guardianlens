"""Text-only Gemma 4 pass over the full accumulated conversation.

Unlike :class:`guardlens.analyzer.GuardLensAnalyzer` which feeds one
screenshot at a time to the vision model, this analyzer feeds the
*entire* accumulated text transcript — every unique chat message seen
across every frame in the current session — as a single short message.

Why a separate analyzer:

- **Text-only is fast.** No base64 image encoding, no vision OCR pass.
  Typical latency 1-3 s vs 5-10 s for the vision call.
- **Aggregation matters.** Three frames each saying "65% scam" look
  like three shrugs when analysed independently but are near-certain
  when seen in one conversation.
- **Certainty is a first-class output.** The model returns a separate
  ``certainty`` field (low/medium/high) that lets the alert policy
  distinguish "100% sure about one message" from "100% sure about the
  full pattern across 10 messages".

Usage::

    ca = ConversationAnalyzer(config.ollama)
    verdict = ca.analyze(conversation_store.all_messages)
    if verdict is not None and verdict.parent_alert_recommended:
        fire_alert(verdict)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Sequence

import ollama

from guardlens.config import OllamaConfig
from guardlens.prompts import (
    CONVERSATION_SYSTEM_PROMPT,
    CONVERSATION_USER_PROMPT_TEMPLATE,
    PROMPT_VERSION,
)
from guardlens.schema import (
    ChatMessage,
    SessionCertainty,
    SessionVerdict,
    ThreatCategory,
    ThreatLevel,
)
from guardlens.tools import ASSESS_CONVERSATION_TOOL

logger = logging.getLogger(__name__)


class ConversationAnalyzer:
    """Call Gemma 4 with the full accumulated conversation as plain text."""

    def __init__(self, config: OllamaConfig) -> None:
        self.config = config
        self._client = ollama.Client(host=config.host, timeout=config.timeout_seconds)

    # ------------------------------------------------------------------ public

    def analyze(
        self,
        messages: Sequence[ChatMessage],
    ) -> SessionVerdict | None:
        """Run a session-level analysis.

        Returns ``None`` if the conversation is empty (nothing to assess)
        or if the model fails to emit the ``assess_conversation`` tool
        call. The caller's :class:`guardlens.schema.SessionVerdict`
        consumer should treat ``None`` as "no session verdict yet — keep
        using per-frame signals".
        """
        if not messages:
            logger.info("ConversationAnalyzer: skip (empty conversation)")
            return None

        transcript = _format_transcript(messages)
        user_prompt = CONVERSATION_USER_PROMPT_TEMPLATE.format(
            n=len(messages), transcript=transcript
        )

        logger.info(
            "ConversationAnalyzer: analyzing %d messages (prompt_version=%s)",
            len(messages),
            PROMPT_VERSION,
        )
        logger.debug("ConversationAnalyzer transcript:\n%s", transcript)

        start = time.perf_counter()
        try:
            response = self._client.chat(
                model=self.config.inference_model,
                messages=[
                    {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                tools=[ASSESS_CONVERSATION_TOOL],
                options={
                    "temperature": 0.1,
                    "num_ctx": self.config.num_ctx,
                },
            )
        except Exception:
            logger.exception("ConversationAnalyzer: Ollama call failed")
            return None
        elapsed = time.perf_counter() - start

        verdict = _parse_response(response, len(messages))
        if verdict is None:
            logger.warning(
                "ConversationAnalyzer: no assess_conversation tool call emitted (%.2fs)",
                elapsed,
            )
            return None

        logger.info(
            "ConversationAnalyzer verdict: %s / %s / %.0f%% / certainty=%s / alert=%s / %.2fs",
            verdict.overall_level.value,
            verdict.overall_category.value,
            verdict.confidence,
            verdict.certainty.value,
            verdict.parent_alert_recommended,
            elapsed,
        )
        logger.debug("ConversationAnalyzer narrative: %s", verdict.narrative)
        return verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_transcript(messages: Sequence[ChatMessage]) -> str:
    """Format the deduplicated message list for the model prompt.

    One message per line, ``<sender>: <text>``. Keeps the transcript
    compact so the context window stays small.
    """
    return "\n".join(f"{m.sender}: {m.text}".strip() for m in messages)


def _parse_response(response: Any, message_count: int) -> SessionVerdict | None:
    """Pull an :class:`SessionVerdict` out of an Ollama response."""
    message = _message_from(response)
    if message is None:
        return None
    tool_calls = _tool_calls_from(message)
    for call in tool_calls:
        name = _call_name(call)
        if name != "assess_conversation":
            continue
        args = _call_arguments(call)
        try:
            return SessionVerdict(
                overall_level=ThreatLevel(args.get("overall_level", "safe")),
                overall_category=ThreatCategory(args.get("overall_category", "none")),
                confidence=float(args.get("confidence", 0.0)),
                certainty=SessionCertainty(args.get("certainty", "low")),
                narrative=str(args.get("narrative", "")).strip(),
                key_indicators=list(args.get("key_indicators", []) or []),
                messages_analyzed=message_count,
                parent_alert_recommended=bool(args.get("parent_alert_recommended", False)),
            )
        except (ValueError, TypeError) as exc:
            logger.warning("ConversationAnalyzer: malformed tool args: %s", exc)
            return None
    return None


def _message_from(response: Any) -> Any | None:
    """Pluck the assistant message out of an Ollama response.

    Ollama may return either an attribute-style object (newer SDK) or a
    plain dict. Handle both.
    """
    if response is None:
        return None
    message = getattr(response, "message", None)
    if message is not None:
        return message
    if isinstance(response, dict):
        return response.get("message")
    return None


def _tool_calls_from(message: Any) -> list[Any]:
    calls = getattr(message, "tool_calls", None)
    if calls is not None:
        return list(calls)
    if isinstance(message, dict):
        return list(message.get("tool_calls", []) or [])
    return []


def _call_name(call: Any) -> str | None:
    function = getattr(call, "function", None)
    if function is not None:
        return getattr(function, "name", None)
    if isinstance(call, dict):
        fn = call.get("function", {})
        return fn.get("name") if isinstance(fn, dict) else None
    return None


def _call_arguments(call: Any) -> dict[str, Any]:
    function = getattr(call, "function", None)
    if function is not None:
        args = getattr(function, "arguments", None)
        if isinstance(args, dict):
            return args
    if isinstance(call, dict):
        fn = call.get("function", {})
        if isinstance(fn, dict):
            args = fn.get("arguments")
            if isinstance(args, dict):
                return args
    return {}


__all__ = ["ConversationAnalyzer"]
