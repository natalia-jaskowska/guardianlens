"""Accumulates chat messages across frames into a deduplicated conversation.

Each analysed frame emits a set of visible chat lines (via the model's
``classify_threat`` tool call, field ``visible_messages``). The same line
appears in many frames — once a message is on screen it typically stays
there as the chat scrolls. This store keeps a running, deduplicated,
order-preserving list of every unique message the system has seen in the
current session.

It is the bridge between per-frame visual analysis and conversation-level
reasoning:

    frame --> classify_threat --> visible_messages
                                      │
                                      ▼
                            ConversationStore.add()
                                      │
                                      ▼
                            all_messages  -->  ConversationAnalyzer

Keyed on ``(sender, normalised_text)`` where normalised_text is the
message stripped and lowercased. Case/whitespace differences don't count
as distinct messages — the same chat line rendered at different moments
is collapsed to one store entry.

This module deliberately does NO model calls. It is a pure data
structure so it is fast, thread-safe under the caller's lock, and easy
to unit test.
"""

from __future__ import annotations

import logging
import threading
from typing import Iterable

from guardlens.schema import ChatMessage

logger = logging.getLogger(__name__)


class ConversationStore:
    """In-memory, deduplicated, order-preserving message store."""

    def __init__(self) -> None:
        self._messages: list[ChatMessage] = []
        self._seen: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        self._unacknowledged_new: int = 0

    # ------------------------------------------------------------------ mutate

    def add(self, messages: Iterable[ChatMessage]) -> list[ChatMessage]:
        """Add messages from a frame and return only the ones that were new.

        Uses ``(sender, text.strip().lower())`` as the dedup key. Messages
        already in the store are silently dropped.

        Returns the list of *new* messages (in first-seen order) so
        callers can decide whether enough has changed to trigger a
        conversation-level re-analysis.
        """
        new_items: list[ChatMessage] = []
        with self._lock:
            for msg in messages:
                key = self._key(msg)
                if not key[0] and not key[1]:
                    # Skip empty messages — the renderer sometimes emits
                    # attachment-only messages with empty text.
                    continue
                if key in self._seen:
                    continue
                self._seen.add(key)
                self._messages.append(msg)
                new_items.append(msg)
                self._unacknowledged_new += 1
            if new_items:
                logger.info(
                    "ConversationStore: +%d new (%d total, %d unacknowledged)",
                    len(new_items),
                    len(self._messages),
                    self._unacknowledged_new,
                )
                for m in new_items:
                    logger.debug(
                        "  + %s: %s",
                        m.sender,
                        m.text[:80] + ("..." if len(m.text) > 80 else ""),
                    )
        return new_items

    def acknowledge(self, count: int | None = None) -> None:
        """Reset (or decrement) the 'unacknowledged new' counter.

        Called by the conversation analyzer after it has consumed the
        store for a session-level pass, so the next trigger can fire
        when ``count`` more messages arrive.
        """
        with self._lock:
            if count is None:
                self._unacknowledged_new = 0
            else:
                self._unacknowledged_new = max(0, self._unacknowledged_new - count)

    def reset(self) -> None:
        """Drop everything — call on session end."""
        with self._lock:
            self._messages.clear()
            self._seen.clear()
            self._unacknowledged_new = 0
        logger.info("ConversationStore: reset")

    # ------------------------------------------------------------------ read

    @property
    def all_messages(self) -> list[ChatMessage]:
        """Snapshot of every unique message, oldest first."""
        with self._lock:
            return list(self._messages)

    def recent_messages(self, n: int) -> list[ChatMessage]:
        """Return the last *n* unique messages (oldest-first within the window)."""
        with self._lock:
            return list(self._messages[-n:]) if n < len(self._messages) else list(self._messages)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._messages)

    @property
    def unacknowledged_new(self) -> int:
        with self._lock:
            return self._unacknowledged_new

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _key(msg: ChatMessage) -> tuple[str, str]:
        return (msg.sender.strip(), msg.text.strip().lower())


class ParticipantTracker:
    """Per-participant message accumulator + :class:`ConversationContext` index.

    Whereas the plain :class:`ConversationStore` keeps one global list of
    every unique message in a session, ``ParticipantTracker`` maintains
    one store **per (platform, participant) pair** plus a matching
    :class:`ConversationContext` for each participant. This is what the
    conversation-centric dashboard reads from to render circle-avatar
    cards.

    The tracker is thread-safe — all mutation acquires a single lock, and
    each participant's underlying :class:`ConversationStore` has its own
    internal lock for its own list. That means ``messages_for(...)`` on
    participant A cannot block ``add_for_participant(...)`` on
    participant B.
    """

    def __init__(self) -> None:
        self._stores: dict[tuple[str, str], ConversationStore] = {}
        # ConversationContext lives here too — lazy import avoids a
        # circular ``schema → conversation_store → schema`` chain during
        # module load.
        from guardlens.schema import ConversationContext  # noqa: WPS433
        self._ctx_cls = ConversationContext
        self._contexts: dict[tuple[str, str], ConversationContext] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ mutate

    def add_for_participant(
        self,
        platform: str,
        participant: str,
        messages: Iterable[ChatMessage],
    ) -> list[ChatMessage]:
        """Accumulate messages under one participant.

        Returns only the messages that were *new* for that specific
        (platform, participant) pair — callers use the returned count to
        decide whether to re-run the per-participant conversation
        analyzer.
        """
        key = self._normalize_key(platform, participant)
        store = self._get_or_create_store(key)
        new_items = store.add(messages)
        if new_items:
            # Pass the ORIGINAL-cased display name so the context (and
            # therefore the dashboard) shows "KidGamer09" even though
            # the lookup key is "kidgamer09".
            ctx = self._get_or_create_context(
                key, display_name=participant.strip(), display_platform=platform.strip()
            )
            with self._lock:
                ctx.message_count = store.size
                from datetime import datetime as _dt  # noqa: WPS433

                ctx.last_seen = _dt.now()
            logger.info(
                "ParticipantTracker[%s/%s]: +%d new (%d total across session)",
                key[0],
                key[1],
                len(new_items),
                store.size,
            )
        return new_items

    def promote(
        self,
        platform: str,
        participant: str,
        source_environment: str,
    ) -> "ConversationContext":
        """Ensure a :class:`ConversationContext` exists with ``source`` marked.

        Called by :mod:`guardlens.environment` when a user in a public
        space specifically targets the child. Idempotent — a second
        promotion on the same (platform, participant) leaves the existing
        context alone.
        """
        key = self._normalize_key(platform, participant)
        with self._lock:
            existing = self._contexts.get(key)
            if existing is not None:
                logger.debug(
                    "ParticipantTracker.promote: %s/%s already tracked (source=%s)",
                    key[0],
                    key[1],
                    existing.source,
                )
                return existing
            ctx = self._ctx_cls(
                participant=participant.strip(),
                platform=platform.strip(),
                source=f"promoted_from_{source_environment}",
            )
            self._contexts[key] = ctx
            # Pre-create the per-participant store so this user appears in
            # participants() immediately, before they send another message.
            if key not in self._stores:
                self._stores[key] = ConversationStore()
        logger.info(
            "ParticipantTracker: promoted %s from %s → tracked conversation",
            participant,
            source_environment,
        )
        return ctx

    def update_context(
        self,
        platform: str,
        participant: str,
        **updates,
    ) -> "ConversationContext":
        """Merge field updates into the :class:`ConversationContext`.

        Creates the context on first access. Silent-ignores unknown
        fields (they cannot corrupt the model because we go through
        ``setattr`` with validation via the Pydantic field types).
        """
        key = self._normalize_key(platform, participant)
        ctx = self._get_or_create_context(key)
        with self._lock:
            for field, value in updates.items():
                if not hasattr(ctx, field):
                    continue
                setattr(ctx, field, value)
        logger.debug(
            "ParticipantTracker[%s/%s]: context updated — keys=%s",
            key[0],
            key[1],
            list(updates.keys()),
        )
        return ctx

    def reset(self) -> None:
        """Drop every tracked participant — call on session end."""
        with self._lock:
            for store in self._stores.values():
                store.reset()
            self._stores.clear()
            self._contexts.clear()
        logger.info("ParticipantTracker: reset")

    # ------------------------------------------------------------------ read

    def messages_for(self, platform: str, participant: str) -> list[ChatMessage]:
        """All accumulated messages for one participant, oldest first."""
        key = self._normalize_key(platform, participant)
        store = self._stores.get(key)
        return store.all_messages if store else []

    def context_for(
        self, platform: str, participant: str
    ) -> "ConversationContext | None":
        """Return the :class:`ConversationContext` or ``None`` if untracked."""
        key = self._normalize_key(platform, participant)
        with self._lock:
            return self._contexts.get(key)

    def participants(self) -> list[tuple[str, str]]:
        """Every tracked (platform, participant) pair."""
        with self._lock:
            return list(self._stores.keys())

    def contexts(self) -> list["ConversationContext"]:
        """Every tracked :class:`ConversationContext`, insertion order."""
        with self._lock:
            return list(self._contexts.values())

    # ------------------------------------------------------------------ internal

    def _get_or_create_store(self, key: tuple[str, str]) -> ConversationStore:
        with self._lock:
            store = self._stores.get(key)
            if store is None:
                store = ConversationStore()
                self._stores[key] = store
        return store

    def _get_or_create_context(
        self,
        key: tuple[str, str],
        *,
        display_name: str | None = None,
        display_platform: str | None = None,
    ) -> "ConversationContext":
        with self._lock:
            ctx = self._contexts.get(key)
            if ctx is None:
                ctx = self._ctx_cls(
                    participant=display_name or key[1],
                    platform=display_platform or key[0],
                )
                self._contexts[key] = ctx
                logger.info(
                    "ParticipantTracker: new context %s/%s (source=%s)",
                    ctx.platform,
                    ctx.participant,
                    ctx.source,
                )
            return ctx

    @staticmethod
    def _normalize_key(platform: str, participant: str) -> tuple[str, str]:
        """Lower+strip both sides so OCR case wobble can't fragment a user.

        The model's username OCR is inconsistent (``KidGamer09`` vs
        ``Kidgamer09``); without lowercasing, each spelling opens its
        own :class:`ConversationContext` and the dashboard ends up
        showing three cards for the same person. The context's
        ``participant`` field still stores the first-seen display name
        so the UI reads naturally.
        """
        return (platform.strip().lower(), participant.strip().lower())


__all__ = ["ConversationStore", "ParticipantTracker"]
