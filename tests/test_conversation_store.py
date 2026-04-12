"""Tests for the ConversationStore message deduplication."""

from __future__ import annotations

from guardlens.conversation_store import ConversationStore
from guardlens.schema import ChatMessage


def _msg(sender: str, text: str) -> ChatMessage:
    return ChatMessage(sender=sender, text=text)


def test_add_deduplicates_by_sender_and_text() -> None:
    store = ConversationStore()
    msgs = [_msg("Alice", "hey"), _msg("Bob", "hi"), _msg("Alice", "hey")]
    new = store.add(msgs)
    assert len(new) == 2
    assert store.size == 2


def test_add_deduplicates_case_insensitive_text() -> None:
    store = ConversationStore()
    store.add([_msg("Alice", "Hey there!")])
    new = store.add([_msg("Alice", "hey there!")])
    assert len(new) == 0
    assert store.size == 1


def test_add_skips_empty_messages() -> None:
    store = ConversationStore()
    new = store.add([_msg("", ""), _msg("Alice", "hello")])
    assert len(new) == 1
    assert store.size == 1


def test_all_messages_preserves_insertion_order() -> None:
    store = ConversationStore()
    store.add([_msg("A", "first")])
    store.add([_msg("B", "second")])
    store.add([_msg("C", "third")])
    msgs = store.all_messages
    assert [m.sender for m in msgs] == ["A", "B", "C"]


def test_recent_messages_returns_tail() -> None:
    store = ConversationStore()
    for i in range(10):
        store.add([_msg(f"user{i}", f"msg{i}")])
    recent = store.recent_messages(3)
    assert len(recent) == 3
    assert recent[0].sender == "user7"
    assert recent[2].sender == "user9"


def test_acknowledge_resets_counter() -> None:
    store = ConversationStore()
    store.add([_msg("A", "first"), _msg("B", "second")])
    assert store.unacknowledged_new == 2
    store.acknowledge()
    assert store.unacknowledged_new == 0


def test_acknowledge_partial_decrement() -> None:
    store = ConversationStore()
    store.add([_msg("A", "1"), _msg("B", "2"), _msg("C", "3")])
    store.acknowledge(count=2)
    assert store.unacknowledged_new == 1


def test_reset_clears_everything() -> None:
    store = ConversationStore()
    store.add([_msg("A", "hello")])
    store.reset()
    assert store.size == 0
    assert store.unacknowledged_new == 0
    # Re-adding the same message should work after reset.
    new = store.add([_msg("A", "hello")])
    assert len(new) == 1
