"""Conversation-first analysis pipeline.

One public entry point: :meth:`ConversationPipeline.push_screenshot`.
Each screenshot goes through up to 4 LLM calls:

1. Frame extraction — vision model identifies all visible conversations
2. Matching — fuzzy-match each fragment to existing conversations (or create new)
3. Message merge — deduplicate prior messages + new messages
4. Status update — reassess conversation safety from full history

All state lives in SQLite. No in-memory copies.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama

from guardlens.alerts import AlertSender
from guardlens.config import OllamaConfig
from guardlens.database import GuardLensDatabase
from guardlens.ollama_utils import extract_thinking, find_call, get_message, get_tool_calls
from guardlens.prompts import (
    FRAME_EXTRACT_SYSTEM_PROMPT,
    FRAME_EXTRACT_USER_PROMPT,
    MATCH_CONVERSATION_SYSTEM_PROMPT,
    MATCH_CONVERSATION_USER_TEMPLATE,
    MERGE_MESSAGES_SYSTEM_PROMPT,
    MERGE_MESSAGES_USER_TEMPLATE,
    STATUS_UPDATE_SYSTEM_PROMPT,
    STATUS_UPDATE_USER_TEMPLATE,
)
from guardlens.schema import (
    ChatMessage,
    ConversationFragment,
    ConversationStatus,
    FrameAnalysis,
    ThreatLevel,
)
from guardlens.tools import (
    PIPELINE_FRAME_TOOLS,
    PIPELINE_MATCH_TOOLS,
    PIPELINE_MERGE_TOOLS,
    PIPELINE_STATUS_TOOLS,
)

logger = logging.getLogger(__name__)


class ConversationPipeline:
    """Stateless pipeline that processes one screenshot at a time.

    All persistent state is in the ``database`` passed to :meth:`push_screenshot`.
    """

    def __init__(self, config: OllamaConfig) -> None:
        self._config = config
        self._client = ollama.Client(host=config.host, timeout=config.timeout_seconds)

    def push_screenshot(
        self,
        image_path: Path,
        database: GuardLensDatabase,
        alerts: AlertSender | None = None,
        *,
        stale_minutes: int = 30,
    ) -> list[int]:
        """Run the full pipeline for one screenshot.

        Returns the list of conversation IDs that were created or updated.
        """
        frame = self._analyze_frame(image_path)
        if not frame.conversations:
            logger.info("No conversations found in frame %s", image_path.name)
            return []

        updated_ids: list[int] = []

        for fragment in frame.conversations:
            try:
                conv_id = self._process_fragment(
                    fragment, image_path, database, alerts, stale_minutes
                )
                updated_ids.append(conv_id)
            except Exception:
                logger.exception("Failed to process fragment for %s", fragment.platform)

        return updated_ids

    # ------------------------------------------------------------------
    # Per-fragment processing (steps 2-6)
    # ------------------------------------------------------------------

    def _process_fragment(
        self,
        fragment: ConversationFragment,
        image_path: Path,
        database: GuardLensDatabase,
        alerts: AlertSender | None,
        stale_minutes: int,
    ) -> int:
        candidates = database.get_active_conversations(stale_minutes)
        conv_id = self._match_conversation(fragment, candidates)

        if conv_id is not None:
            row = database.get_conversation(conv_id)
            if row is None:
                conv_id = None
            else:
                prior_messages = json.loads(row["messages_json"])
                prior_status_raw = row["status_json"]
                prior_status = json.loads(prior_status_raw) if prior_status_raw else None
                prior_screenshots = json.loads(row["screenshots_json"])
                prior_participants = json.loads(row["participants_json"])
        else:
            prior_messages = []
            prior_status = None
            prior_screenshots = []
            prior_participants = []

        merged = self._merge_messages(prior_messages, fragment.messages)
        new_status = self._update_status(prior_status, merged)

        now = datetime.now().isoformat()
        screenshot_entry = {"path": str(image_path), "timestamp": now}
        screenshots = prior_screenshots + [screenshot_entry]

        all_participants = list(
            dict.fromkeys(prior_participants + fragment.participants)
        )

        if conv_id is None:
            conv_id = database.create_conversation(
                platform=fragment.platform,
                participants=all_participants,
                first_seen=now,
                messages=merged,
                screenshots=screenshots,
                status=new_status.model_dump(mode="json"),
                status_reasoning=new_status.reasoning,
            )
        else:
            database.update_conversation(
                conv_id,
                messages_json=json.dumps(merged),
                status_json=json.dumps(new_status.model_dump(mode="json")),
                status_reasoning=new_status.reasoning,
                screenshots_json=json.dumps(screenshots),
                last_seen=now,
                participants_json=json.dumps(all_participants),
            )

        database.insert_fragment(
            conversation_id=conv_id,
            timestamp=now,
            screenshot_path=str(image_path),
            raw_analysis_json=fragment.model_dump_json(),
        )

        if new_status.parent_alert_recommended and alerts is not None:
            self._fire_alert(conv_id, new_status, database, alerts)

        return conv_id

    # ------------------------------------------------------------------
    # Step 1: Frame extraction (vision LLM call)
    # ------------------------------------------------------------------

    def _analyze_frame(self, image_path: Path) -> FrameAnalysis:
        image_b64 = _encode_image(image_path)

        start = time.perf_counter()
        try:
            response = self._client.chat(
                model=self._config.inference_model,
                messages=[
                    {"role": "system", "content": FRAME_EXTRACT_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": FRAME_EXTRACT_USER_PROMPT,
                        "images": [image_b64],
                    },
                ],
                tools=PIPELINE_FRAME_TOOLS,
                options={
                    "temperature": self._config.temperature,
                    "num_ctx": self._config.num_ctx,
                },
            )
        except (ollama.RequestError, ollama.ResponseError, TimeoutError, ConnectionError) as exc:
            logger.error("Frame analysis failed: %s", exc)
            return FrameAnalysis()
        elapsed = time.perf_counter() - start

        message = get_message(response)
        tool_calls = get_tool_calls(message)
        args = find_call(tool_calls, "extract_conversations")

        if args is None:
            logger.warning("Model did not call extract_conversations — empty frame.")
            return FrameAnalysis(
                raw_thinking=extract_thinking(message),
                inference_seconds=elapsed,
            )

        fragments: list[ConversationFragment] = []
        for conv_raw in args.get("conversations", []):
            messages = [
                ChatMessage(sender=m.get("sender", "?"), text=m.get("text", ""))
                for m in conv_raw.get("messages", [])
                if isinstance(m, dict)
            ]
            fragments.append(
                ConversationFragment(
                    platform=conv_raw.get("platform", "Unknown"),
                    participants=conv_raw.get("participants", []),
                    messages=messages,
                )
            )

        return FrameAnalysis(
            conversations=fragments,
            raw_thinking=extract_thinking(message),
            inference_seconds=elapsed,
        )

    # ------------------------------------------------------------------
    # Step 3: Match conversation (text LLM call)
    # ------------------------------------------------------------------

    def _match_conversation(
        self,
        fragment: ConversationFragment,
        candidates: list[Any],
    ) -> int | None:
        if not candidates:
            return None

        messages_sample = _format_messages(fragment.messages[:5])
        candidates_text = _format_candidates(candidates)

        prompt = MATCH_CONVERSATION_USER_TEMPLATE.format(
            platform=fragment.platform,
            participants=", ".join(fragment.participants) or "(none visible)",
            msg_count=min(5, len(fragment.messages)),
            messages_sample=messages_sample,
            stale_minutes=30,
            candidates=candidates_text,
        )

        try:
            response = self._client.chat(
                model=self._config.inference_model,
                messages=[
                    {"role": "system", "content": MATCH_CONVERSATION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tools=PIPELINE_MATCH_TOOLS,
                options={"temperature": 0.1, "num_ctx": self._config.num_ctx},
            )
        except (ollama.RequestError, ollama.ResponseError, TimeoutError, ConnectionError) as exc:
            logger.error("Match call failed: %s — creating new conversation", exc)
            return None

        message = get_message(response)
        tool_calls = get_tool_calls(message)
        args = find_call(tool_calls, "match_conversation")

        if args is None:
            return None

        conv_id = args.get("conversation_id")
        if conv_id is None:
            return None

        try:
            return int(conv_id)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Step 4: Merge messages (text LLM call)
    # ------------------------------------------------------------------

    def _merge_messages(
        self,
        prior: list[dict[str, str]],
        new_messages: list[ChatMessage],
    ) -> list[dict[str, str]]:
        new_dicts = [{"sender": m.sender, "text": m.text} for m in new_messages]

        if not prior:
            return new_dicts
        if not new_dicts:
            return prior

        prior_transcript = _format_message_dicts(prior)
        new_transcript = _format_message_dicts(new_dicts)

        prompt = MERGE_MESSAGES_USER_TEMPLATE.format(
            prior_count=len(prior),
            prior_transcript=prior_transcript,
            new_count=len(new_dicts),
            new_transcript=new_transcript,
        )

        try:
            response = self._client.chat(
                model=self._config.inference_model,
                messages=[
                    {"role": "system", "content": MERGE_MESSAGES_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tools=PIPELINE_MERGE_TOOLS,
                options={"temperature": 0.0, "num_ctx": self._config.num_ctx},
            )
        except (ollama.RequestError, ollama.ResponseError, TimeoutError, ConnectionError) as exc:
            logger.error("Merge call failed: %s — naive fallback", exc)
            return _naive_merge(prior, new_dicts)

        message = get_message(response)
        tool_calls = get_tool_calls(message)
        args = find_call(tool_calls, "merge_messages")

        if args is None:
            logger.warning("Model did not call merge_messages — naive fallback.")
            return _naive_merge(prior, new_dicts)

        merged_raw = args.get("merged_messages", [])
        result = []
        for m in merged_raw:
            if isinstance(m, dict) and "sender" in m and "text" in m:
                result.append({"sender": m["sender"], "text": m["text"]})
        return result if result else _naive_merge(prior, new_dicts)

    # ------------------------------------------------------------------
    # Step 5: Update conversation status (text LLM call)
    # ------------------------------------------------------------------

    def _update_status(
        self,
        prior_status: dict | None,
        messages: list[dict[str, str]],
    ) -> ConversationStatus:
        if not messages:
            return ConversationStatus()

        transcript = _format_message_dicts(messages)
        prior_text = json.dumps(prior_status, indent=2) if prior_status else "null (first analysis)"

        prompt = STATUS_UPDATE_USER_TEMPLATE.format(
            prior_status=prior_text,
            total_count=len(messages),
            transcript=transcript,
        )

        try:
            response = self._client.chat(
                model=self._config.inference_model,
                messages=[
                    {"role": "system", "content": STATUS_UPDATE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tools=PIPELINE_STATUS_TOOLS,
                options={"temperature": 0.1, "num_ctx": self._config.num_ctx},
            )
        except (ollama.RequestError, ollama.ResponseError, TimeoutError, ConnectionError) as exc:
            logger.error("Status update call failed: %s — safe fallback", exc)
            return ConversationStatus()

        message = get_message(response)
        tool_calls = get_tool_calls(message)
        args = find_call(tool_calls, "update_conversation_status")

        if args is None:
            logger.warning("Model did not call update_conversation_status — safe fallback.")
            return ConversationStatus()

        try:
            return ConversationStatus.model_validate(args)
        except Exception as exc:
            logger.warning("Failed to parse status: %s", exc)
            return ConversationStatus()

    # ------------------------------------------------------------------
    # Alert dispatch
    # ------------------------------------------------------------------

    def _fire_alert(
        self,
        conv_id: int,
        status: ConversationStatus,
        database: GuardLensDatabase,
        alerts: AlertSender,
    ) -> None:
        from guardlens.schema import AlertUrgency, ParentAlert, ScreenAnalysis, ThreatClassification

        classification = ThreatClassification(
            threat_level=status.threat_level,
            category=status.category,
            confidence=status.confidence,
            reasoning=status.narrative,
            indicators_found=status.indicators,
        )
        parent_alert = ParentAlert(
            alert_title=f"Conversation alert: {status.category.value}",
            summary=status.narrative,
            recommended_action="Review your child's recent conversations.",
            urgency=(
                AlertUrgency.IMMEDIATE
                if status.threat_level in (ThreatLevel.ALERT, ThreatLevel.CRITICAL)
                else AlertUrgency.HIGH
            ),
        )

        row = database.get_conversation(conv_id)
        screenshot_path = Path("unknown")
        if row:
            screenshots = json.loads(row["screenshots_json"])
            if screenshots:
                screenshot_path = Path(screenshots[-1].get("path", "unknown"))

        stub = ScreenAnalysis(
            timestamp=datetime.now(),
            screenshot_path=screenshot_path,
            platform=row["platform"] if row else "Unknown",
            classification=classification,
            parent_alert=parent_alert,
            inference_seconds=0.0,
        )

        delivered = alerts.maybe_send(stub)
        analysis_id = database.record_analysis(stub)
        if analysis_id:
            database.record_alert(analysis_id, stub, delivered=delivered)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _encode_image(image_path: Path) -> str:
    with image_path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _format_messages(messages: list[ChatMessage]) -> str:
    lines = []
    for m in messages:
        lines.append(f"  {m.sender}: {m.text}")
    return "\n".join(lines) if lines else "  (no messages)"


def _format_message_dicts(messages: list[dict[str, str]]) -> str:
    lines = []
    for m in messages:
        lines.append(f"  {m.get('sender', '?')}: {m.get('text', '')}")
    return "\n".join(lines) if lines else "  (no messages)"


def _format_candidates(candidates: list[Any]) -> str:
    if not candidates:
        return "  (none)"
    lines = []
    for c in candidates:
        cid = c["id"]
        platform = c["platform"]
        participants = json.loads(c["participants_json"])
        last_seen = c["last_seen"]
        messages = json.loads(c["messages_json"])
        tail = messages[-3:] if messages else []
        tail_text = "; ".join(f'{m.get("sender","?")}: {m.get("text","")}' for m in tail)
        lines.append(
            f"  ID {cid}: platform={platform}, "
            f"participants={', '.join(participants)}, "
            f"last_seen={last_seen}, "
            f"last messages: [{tail_text}]"
        )
    return "\n".join(lines)


def _naive_merge(
    prior: list[dict[str, str]],
    new: list[dict[str, str]],
) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for m in prior + new:
        key = (m.get("sender", "").strip().lower(), m.get("text", "").strip().lower())
        if key not in seen:
            seen.add(key)
            result.append(m)
    return result
