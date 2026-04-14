"""Track public / multi-user spaces and promote targeting users.

An *environment* is a place the child is visiting rather than a person the
child is talking to: a Minecraft server, a Discord public channel, a
TikTok feed, a YouTube video. Unlike a conversation, it has no single
interlocutor — so we track the space's overall safety instead of one
person's behavior.

The monitor has two jobs:

1. Keep one :class:`EnvironmentContext` per (platform, context) pair and
   update its ``overall_safety``, ``user_count``, ``duration_minutes``,
   and ``indicators`` from each frame.
2. Watch for TARGETING inside a public space — a message whose intent is
   clearly "this message is for the child". When targeting fires, the
   offending user is PROMOTED: a :class:`ConversationContext` is opened
   for them with ``source="promoted_from_<platform>"`` so the
   conversation-level analyzer starts following them across frames.

The targeting heuristic is intentionally simple: the vision model's
indicators already flag things like "age inquiry", "request to move
private", "personal info request" — if any of those appear in a group
chat / environment frame, the sender of that message becomes a promotion
candidate. More sophisticated signals (sentiment, cross-frame escalation)
live in :mod:`guardlens.escalation`.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Iterable

from guardlens.conversation_store import ParticipantTracker
from guardlens.schema import (
    ChatMessage,
    EnvironmentContext,
    ScreenAnalysis,
    ThreatLevel,
)

logger = logging.getLogger(__name__)

# Indicator fragments (case-insensitive substring match) that signal one
# user is specifically targeting the child within a public space.
_TARGETING_INDICATORS: tuple[str, ...] = (
    "age inquiry",
    "age_inquiry",
    "asking age",
    "personal info",
    "personal_info",
    "request to move",
    "move private",
    "add me",
    "dm me",
    "private platform",
    "exchange platform",
    "location request",
    "school request",
    "isolation",
)


class EnvironmentMonitor:
    """Per-space state + targeting-based promotion to per-participant tracking."""

    def __init__(self, tracker: ParticipantTracker | None = None) -> None:
        # The participant tracker is required for promotion. Optional at
        # construction so unit tests can exercise EnvironmentMonitor alone.
        self._tracker = tracker
        self._contexts: dict[tuple[str, str], EnvironmentContext] = {}
        # Seen-users set per environment, kept off the Pydantic model
        # because BaseModel does not allow arbitrary instance attrs.
        self._seen_users: dict[tuple[str, str], set[str]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ update

    def observe(self, analysis: ScreenAnalysis) -> EnvironmentContext:
        """Record one frame against the environment it belongs to.

        Returns the updated :class:`EnvironmentContext`. Caller can
        serialize it directly for the dashboard.
        """
        key = self._env_key(analysis)
        with self._lock:
            ctx = self._contexts.get(key)
            if ctx is None:
                ctx = EnvironmentContext(
                    platform=key[0],
                    context=key[1],
                    content_type_label=self._content_label(analysis),
                )
                self._contexts[key] = ctx
                logger.info(
                    "EnvironmentMonitor: new environment %s/%s (%s)",
                    key[0],
                    key[1],
                    ctx.content_type_label,
                )

            ctx.last_seen = datetime.now()

            # User count — union of users seen so far.
            seen_users = self._seen_users.setdefault(key, set())
            for u in analysis.classification.extracted_users:
                if u:
                    seen_users.add(u.strip())
            # Also fold in senders visible in the frame's chat messages.
            for m in analysis.classification.visible_messages:
                s = (m.sender or "").strip()
                if s and s.lower() not in {"you", "me", "child"}:
                    seen_users.add(s)
            ctx.user_count = len(seen_users)

            # Accumulate indicator labels.
            for ind in analysis.classification.indicators_found:
                if ind and ind not in ctx.indicators:
                    ctx.indicators.append(ind)

            # Overall safety: monotonic high-water — the worst thing we
            # have ever seen in this space is what the parent cares
            # about, not the most recent frame.
            ctx.overall_safety = self._merge_level(
                ctx.overall_safety, analysis.classification.threat_level
            )
            ctx.content_summary = (
                analysis.classification.reasoning[:240]
                if analysis.classification.reasoning
                else ctx.content_summary
            )

        logger.debug(
            "EnvironmentMonitor[%s/%s]: users=%d level=%s indicators=%d",
            key[0],
            key[1],
            ctx.user_count,
            ctx.overall_safety.value,
            len(ctx.indicators),
        )
        return ctx

    def detect_and_promote(self, analysis: ScreenAnalysis) -> list[str]:
        """Check whether any user in this frame is targeting the child.

        Returns the list of usernames that got promoted. No-op when the
        monitor has no :class:`ParticipantTracker` wired in.
        """
        if self._tracker is None:
            return []

        key = self._env_key(analysis)
        indicators_lower = [
            ind.lower() for ind in analysis.classification.indicators_found if ind
        ]
        has_targeting = any(
            any(sig in ind for sig in _TARGETING_INDICATORS)
            for ind in indicators_lower
        )
        if not has_targeting:
            return []

        # Attribute the targeting to whoever is sending the visible
        # concerning messages. If flags are present on specific messages,
        # those senders are the candidates. Otherwise every non-child
        # sender visible in the frame is a candidate.
        candidates = self._targeting_candidates(analysis.classification.visible_messages)
        if not candidates:
            return []

        promoted_here: list[str] = []
        ctx = self._contexts.get(key)
        for sender in candidates:
            # Promote onto the SAME platform as the originating space so
            # a user we already see in the public chat (or a user the
            # child DMs later) ends up as a single conversation card on
            # the dashboard. The ``source="promoted_from_X"`` field
            # still tells us how they entered tracking.
            target_platform = key[0]
            self._tracker.promote(target_platform, sender, source_environment=key[0])
            if ctx is not None and sender not in ctx.promoted_users:
                ctx.promoted_users.append(sender)
            promoted_here.append(sender)

        if promoted_here:
            logger.info(
                "EnvironmentMonitor: promoted %d user(s) from %s/%s → conversations: %s",
                len(promoted_here),
                key[0],
                key[1],
                promoted_here,
            )
        return promoted_here

    # ------------------------------------------------------------------ read

    def environments(self) -> list[EnvironmentContext]:
        """Every tracked :class:`EnvironmentContext`, oldest first."""
        with self._lock:
            return list(self._contexts.values())

    def environment_for(
        self, platform: str, context: str
    ) -> EnvironmentContext | None:
        with self._lock:
            return self._contexts.get((platform.lower().strip(), context))

    def reset(self) -> None:
        with self._lock:
            self._contexts.clear()
            self._seen_users.clear()
        logger.info("EnvironmentMonitor: reset")

    # ------------------------------------------------------------------ internal

    @staticmethod
    def _env_key(analysis: ScreenAnalysis) -> tuple[str, str]:
        platform = (
            analysis.platform
            or analysis.classification.platform_detected
            or "unknown"
        ).strip().lower()
        # Context sub-identifier: for now, coarse — the platform itself.
        # Future: use window title / room name from OCR.
        return (platform, platform)

    @staticmethod
    def _content_label(analysis: ScreenAnalysis) -> str:
        cls = analysis.classification
        if cls.is_passive_feed:
            return "video_feed" if "tiktok" in (analysis.platform or "").lower() else "social_feed"
        if cls.is_group_chat:
            return "in_game_chat"
        return "website"

    @staticmethod
    def _targeting_candidates(messages: Iterable[ChatMessage]) -> list[str]:
        """Return senders of messages that look targeting.

        Prefers messages with a non-null ``flag`` (explicit indicator).
        Falls back to every non-child sender in the frame.
        """
        flagged: list[str] = []
        all_senders: list[str] = []
        for m in messages:
            sender = (m.sender or "").strip()
            if not sender or sender.lower() in {"you", "me", "child"}:
                continue
            if sender not in all_senders:
                all_senders.append(sender)
            if m.flag and sender not in flagged:
                flagged.append(sender)
        return flagged or all_senders

    @staticmethod
    def _merge_level(current: ThreatLevel, incoming: ThreatLevel) -> ThreatLevel:
        order = [
            ThreatLevel.SAFE,
            ThreatLevel.CAUTION,
            ThreatLevel.WARNING,
            ThreatLevel.ALERT,
            ThreatLevel.CRITICAL,
        ]
        return incoming if order.index(incoming) > order.index(current) else current


