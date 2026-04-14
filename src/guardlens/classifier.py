"""Route each per-frame :class:`ScreenAnalysis` to a CONVERSATION or ENVIRONMENT path.

The per-frame vision model is encouraged (via prompt + tool schema fields
``is_direct_message`` / ``is_group_chat`` / ``is_passive_feed``) to mark
what kind of UI it is looking at. When those flags are present, they win.

When they are not — which will happen for older prompts / fine-tuned
models that pre-date the routing fields — we fall back to a small
platform-name heuristic. The heuristic is intentionally conservative:
unknown / ambiguous platforms default to ENVIRONMENT because
environments are the safer pool (a person mis-tracked as a space loses
per-participant continuity; a space mis-tracked as a person creates a
bogus "conversation" for every visible username).
"""

from __future__ import annotations

import logging

from guardlens.schema import ContentType, ScreenAnalysis

logger = logging.getLogger(__name__)


# Platform-name fragments → default routing.
# Kept lowercase; we match on ``platform_detected or platform`` via ``in``.
_DM_HINTS: tuple[str, ...] = (
    "_dm",
    " dm",
    "direct message",
    "whatsapp",
    "imessage",
    "messenger",
    "telegram_dm",
    "snapchat_chat",
)
_FEED_HINTS: tuple[str, ...] = (
    "tiktok",
    "youtube",
    "instagram_feed",
    "instagram feed",
    "facebook_feed",
    "reels",
    "shorts",
    "_feed",
)
_GROUP_HINTS: tuple[str, ...] = (
    "minecraft",
    "roblox",
    "fortnite",
    "_channel",
    "#",
    "server",
    "discord_channel",
    "group_chat",
)


class ContentClassifier:
    """First step after frame analysis: CONVERSATION or ENVIRONMENT?

    Stateless. Callers pass a :class:`ScreenAnalysis` and receive a
    :class:`ContentType`. The classifier also sets
    ``analysis.content_type`` as a side effect so downstream code (store,
    serializers) can read it off the object directly.
    """

    def classify(self, analysis: ScreenAnalysis) -> ContentType:
        """Return the routing decision and stamp it onto the analysis."""
        ct = self._decide(analysis)
        analysis.content_type = ct
        logger.info(
            "ContentClassifier: platform=%r → %s (hints: dm=%s group=%s feed=%s)",
            analysis.platform or analysis.classification.platform_detected,
            ct.value,
            analysis.classification.is_direct_message,
            analysis.classification.is_group_chat,
            analysis.classification.is_passive_feed,
        )
        return ct

    # ------------------------------------------------------------------ internal

    def _decide(self, analysis: ScreenAnalysis) -> ContentType:
        cls = analysis.classification

        # 1) Explicit hints from the vision model win.
        if cls.is_direct_message:
            return ContentType.CONVERSATION
        if cls.is_group_chat or cls.is_passive_feed:
            return ContentType.ENVIRONMENT

        # 2) Platform-name heuristic.
        haystack = (
            f"{analysis.platform or ''} {cls.platform_detected or ''}"
        ).lower()
        if any(h in haystack for h in _DM_HINTS):
            return ContentType.CONVERSATION
        if any(h in haystack for h in _FEED_HINTS):
            return ContentType.ENVIRONMENT
        if any(h in haystack for h in _GROUP_HINTS):
            return ContentType.ENVIRONMENT

        # 3) Last-resort heuristic: if we see exactly one non-child sender
        #    across the visible messages, treat it as a conversation; more
        #    than one means a shared space.
        senders = {
            m.sender.strip().lower()
            for m in cls.visible_messages
            if m.sender and m.sender.strip().lower() not in {"you", "me", "child"}
        }
        if len(senders) == 1:
            return ContentType.CONVERSATION

        # 4) Default: ENVIRONMENT (safer pool — see module docstring).
        return ContentType.ENVIRONMENT
