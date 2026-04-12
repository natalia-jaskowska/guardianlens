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

from pydantic import ValidationError

from guardlens.config import OllamaConfig
from guardlens.ollama_utils import find_call, get_message, get_tool_calls
from guardlens.prompts import (
    CONVERSATION_SYSTEM_PROMPT,
    CONVERSATION_USER_PROMPT_TEMPLATE,
    CONVERSATION_USER_PROMPT_WITH_FRAME_HINT,
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
        frame_hint: dict[str, str] | None = None,
    ) -> SessionVerdict | None:
        """Run a session-level analysis.

        Parameters
        ----------
        messages:
            The conversation window to analyze.
        frame_hint:
            Optional dict with keys ``level``, ``category``,
            ``confidence``, ``reasoning`` from the latest per-frame
            scan. When provided, the prompt tells the model what the
            real-time scanner flagged so it can specifically address
            whether that concern is justified in context.

        Returns ``None`` if the conversation is empty or the model fails
        to emit the ``assess_conversation`` tool call.
        """
        if not messages:
            logger.info("ConversationAnalyzer: skip (empty conversation)")
            return None

        transcript = _format_transcript(messages)
        if frame_hint:
            user_prompt = CONVERSATION_USER_PROMPT_WITH_FRAME_HINT.format(
                n=len(messages),
                transcript=transcript,
                frame_level=frame_hint.get("level", "unknown"),
                frame_category=frame_hint.get("category", "unknown"),
                frame_confidence=frame_hint.get("confidence", "?"),
                frame_reasoning=frame_hint.get("reasoning", ""),
            )
        else:
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
        except (ollama.RequestError, ollama.ResponseError) as exc:
            logger.error("ConversationAnalyzer: Ollama request failed: %s", exc)
            return None
        except (TimeoutError, ConnectionError) as exc:
            logger.error("ConversationAnalyzer: network error: %s", exc)
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
    """Pull a :class:`SessionVerdict` out of an Ollama response."""
    message = get_message(response)
    if not message:
        return None
    tool_calls = get_tool_calls(message)
    args = find_call(tool_calls, "assess_conversation")
    if args is None:
        return None
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
    except (ValueError, TypeError, ValidationError) as exc:
        logger.warning("ConversationAnalyzer: malformed tool args: %s", exc)
        return None


__all__ = ["ConversationAnalyzer"]
