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


__all__ = ["ConversationStore"]
