"""Ollama-backed analyzer for one screenshot.

The :class:`GuardLensAnalyzer` is the only place in the codebase that talks
to Ollama. Everything else consumes typed :class:`ScreenAnalysis` objects.

Design notes
------------
- Image goes BEFORE text in the prompt — Gemma 4 multimodal requirement.
- We pass the three function-calling tools defined in :mod:`guardlens.tools`
  and parse the resulting tool calls into Pydantic models. If the model
  forgets to call ``classify_threat`` we synthesize a "safe / low confidence"
  fallback rather than crash, so the live demo never blanks out.
- Inference latency is recorded so the dashboard can show a "tokens / sec"
  badge — useful for the Ollama prize narrative.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama

from guardlens.config import OllamaConfig
from guardlens.prompts import ANALYSIS_PROMPT, SYSTEM_PROMPT
from guardlens.schema import (
    GroomingStageResult,
    ParentAlert,
    ScreenAnalysis,
    ThreatCategory,
    ThreatClassification,
    ThreatLevel,
)
from guardlens.tools import GUARDLENS_TOOLS

logger = logging.getLogger(__name__)


class GuardLensAnalyzer:
    """Send screenshots to Gemma 4 via Ollama and parse the response."""

    def __init__(self, config: OllamaConfig) -> None:
        self.config = config
        self._client = ollama.Client(host=config.host, timeout=config.timeout_seconds)

    # ------------------------------------------------------------------ public

    def analyze(self, image_path: Path, *, use_finetuned: bool = False) -> ScreenAnalysis:
        """Run one analysis against ``image_path`` and return a typed result."""
        model = self.config.finetuned_model if use_finetuned else self.config.inference_model
        image_b64 = _encode_image(image_path)

        start = time.perf_counter()
        response = self._client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": ANALYSIS_PROMPT,
                    "images": [image_b64],
                },
            ],
            tools=GUARDLENS_TOOLS,
            options={
                "temperature": self.config.temperature,
                "num_ctx": self.config.num_ctx,
            },
        )
        elapsed = time.perf_counter() - start

        return self._parse_response(response, image_path, elapsed)

    # ------------------------------------------------------------------ parsing

    def _parse_response(
        self,
        response: Any,
        image_path: Path,
        elapsed: float,
    ) -> ScreenAnalysis:
        """Convert a raw Ollama response into a :class:`ScreenAnalysis`."""
        message = _get_message(response)
        tool_calls = _get_tool_calls(message)

        classification = _extract_classification(tool_calls)
        grooming_stage = _extract_grooming_stage(tool_calls)
        parent_alert = _extract_parent_alert(tool_calls)
        raw_thinking = _extract_thinking(message)
        # Prefer the model's own platform identification (from classify_threat).
        # Fall back to a heuristic over the raw thinking text only if missing.
        platform = classification.platform_detected or _extract_platform(raw_thinking)

        return ScreenAnalysis(
            timestamp=datetime.now(),
            screenshot_path=image_path,
            platform=platform,
            raw_thinking=raw_thinking,
            classification=classification,
            grooming_stage=grooming_stage,
            parent_alert=parent_alert,
            inference_seconds=elapsed,
        )


# ---------------------------------------------------------------- module-level helpers


def _encode_image(image_path: Path) -> str:
    """Read a PNG and return its base64 representation."""
    with image_path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_message(response: Any) -> dict[str, Any]:
    """Pluck the assistant message out of an Ollama response.

    Ollama may return either an attribute-style object or a plain dict
    depending on SDK version, so we handle both.
    """
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


def _get_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the list of tool-call dicts from an assistant message."""
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


def _find_call(tool_calls: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for call in tool_calls:
        if call["name"] == name:
            return call["arguments"] if isinstance(call["arguments"], dict) else None
    return None


def _extract_classification(tool_calls: list[dict[str, Any]]) -> ThreatClassification:
    """Pull a :class:`ThreatClassification` from the tool calls.

    If the model forgot to call ``classify_threat`` we fall back to a
    safe / low-confidence verdict so downstream code never has to deal with
    ``None``. The fallback is logged so we can spot prompt regressions.
    """
    args = _find_call(tool_calls, "classify_threat")
    if args is None:
        logger.warning("Model did not emit classify_threat — falling back to SAFE.")
        return ThreatClassification(
            threat_level=ThreatLevel.SAFE,
            category=ThreatCategory.NONE,
            confidence=0.0,
            reasoning="Model did not return a structured classification.",
            indicators_found=[],
        )
    return ThreatClassification.model_validate(args)


def _extract_grooming_stage(tool_calls: list[dict[str, Any]]) -> GroomingStageResult | None:
    args = _find_call(tool_calls, "identify_grooming_stage")
    if args is None:
        return None
    return GroomingStageResult.model_validate(args)


def _extract_parent_alert(tool_calls: list[dict[str, Any]]) -> ParentAlert | None:
    args = _find_call(tool_calls, "generate_parent_alert")
    if args is None:
        return None
    return ParentAlert.model_validate(args)


def _extract_thinking(message: dict[str, Any]) -> str | None:
    """Best-effort extraction of the model's thinking trace."""
    thinking = message.get("thinking")
    if isinstance(thinking, str) and thinking.strip():
        return thinking
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None


def _extract_platform(thinking: str | None) -> str | None:
    """Cheap heuristic for the platform name based on the model's reasoning.

    We use this only as a UI hint on the dashboard. If the heuristic misses
    the platform we just show "Unknown" — no logic depends on the value.
    """
    if not thinking:
        return None
    lowered = thinking.lower()
    candidates = (
        "minecraft",
        "roblox",
        "fortnite",
        "discord",
        "instagram",
        "snapchat",
        "tiktok",
        "youtube",
        "whatsapp",
        "browser",
    )
    for name in candidates:
        if name in lowered:
            return name.capitalize()
    return None
