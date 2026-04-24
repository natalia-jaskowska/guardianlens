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
import difflib
import io
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama
from PIL import Image

from guardlens.alerts import AlertSender
from guardlens.config import OllamaConfig
from guardlens.database import GuardLensDatabase
from guardlens.ollama_utils import extract_thinking, find_call, get_message, get_tool_calls
from guardlens.prompts import (
    FRAME_EXTRACT_SYSTEM_PROMPT,
    FRAME_EXTRACT_USER_PROMPT,
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
    PIPELINE_STATUS_TOOLS,
)

MATCH_LONG_MSG_MIN = 15
"""Normalized length at which a single message is considered distinctive enough
to serve as a standalone merge signal."""

MATCH_MIN_RUN = 2
"""Minimum number of contiguous in-order message matches to count as a run."""

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
        stale_minutes: int = 1,
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
        screenshots = [*prior_screenshots, screenshot_entry]

        all_participants = _dedup_participants(prior_participants + fragment.participants)

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
            logger.exception("Frame analysis failed (%s): %s", type(exc).__name__, exc)
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
    # Step 3: Match conversation (deterministic, no LLM)
    # ------------------------------------------------------------------

    def _match_conversation(
        self,
        fragment: ConversationFragment,
        candidates: list[Any],
    ) -> int | None:
        return _score_match(fragment, candidates)

    # ------------------------------------------------------------------
    # Step 4: Merge messages (text LLM call)
    # ------------------------------------------------------------------

    def _merge_messages(
        self,
        prior: list[dict[str, str]],
        new_messages: list[ChatMessage],
    ) -> list[dict[str, str]]:
        new_dicts = [{"sender": m.sender, "text": m.text} for m in new_messages]
        return _fuzzy_merge(prior, new_dicts)

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

        # Some models return confidence as a fraction (0.99) instead of
        # a percentage (99). Normalize: anything ≤ 1.0 is treated as 0-1.
        conf = args.get("confidence")
        if isinstance(conf, (int, float)) and 0 < conf <= 1.0:
            args["confidence"] = conf * 100

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


_MAX_EDGE_PX = 1280


def _encode_image(image_path: Path) -> str:
    # Cap the longest edge at 1280 px before sending to the vision model.
    # Gemma 3/4 vision tiles at 896x896; sending a raw 1920x1080 frame
    # either downscales internally (wasting the bytes we sent) or triggers
    # multi-tile Pan&Scan (multiplying prefill cost). 1280 keeps in-game
    # chat text readable (~10 px on a 1920x1080 source) while staying in
    # the two-tile budget.
    with Image.open(image_path) as img:
        img.load()
    w, h = img.size
    longest = max(w, h)
    if longest > _MAX_EDGE_PX:
        scale = _MAX_EDGE_PX / longest
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _format_message_dicts(messages: list[dict[str, str]]) -> str:
    lines = []
    for m in messages:
        lines.append(f"  {m.get('sender', '?')}: {m.get('text', '')}")
    return "\n".join(lines) if lines else "  (no messages)"


def _normalize_text(text: str) -> str:
    s = text.strip().lower()
    return "".join(ch for ch in s if ch.isalnum())


def _fuzzy_name_match(a: str, b: str) -> bool:
    """True if two normalized names are the same person modulo OCR noise."""
    if not a or not b:
        return False
    if a == b:
        return True
    # One is a prefix of the other (Max / Maxx / Maxxx after collapse).
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 3 and longer.startswith(shorter):
        return True
    # Close OCR drift (one char added/changed on short names).
    return bool(abs(len(a) - len(b)) <= 2 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)


def _score_match(
    fragment: ConversationFragment,
    candidates: list[Any],
) -> int | None:
    """Deterministic fragment→conversation matcher.

    A merge requires at least one of these "strong" signals with the
    candidate, computed on normalized message text:

    * ≥1 "long" exact match (normalized length ≥ :data:`MATCH_LONG_MSG_MIN`)
    * ≥2 total message hits (exact + fuzzy)
    * a contiguous in-order run of ≥ :data:`MATCH_MIN_RUN` matching messages

    Short single-message fragments only merge when the single message
    is long and distinctive — an isolated "lol" or "yes" never merges
    a new frame into an existing conversation.

    Score (used only for tie-breaking among eligible candidates):

    * +6 per exact hit, +5 extra for each "long" exact hit
    * +3 per fuzzy hit (SequenceMatcher ratio ≥ 0.85, both ≥ 10 chars)
    * +4 per non-child participant overlap
    * +8 per additional matched step in the longest contiguous run
    """
    if not candidates:
        return None

    frag_parts = [_normalize_name(p) for p in fragment.participants if p and p.lower() != "child"]
    frag_parts = [p for p in frag_parts if p]

    frag_texts_raw = [
        _normalize_text(m.text)
        for m in fragment.messages
    ]
    frag_texts = [t for t in frag_texts_raw if len(t) >= 4]
    frag_size = len(fragment.messages)

    best_id: int | None = None
    best_score = 0
    breakdowns: list[str] = []

    for c in candidates:
        if c["platform"] != fragment.platform:
            continue

        cand_parts = [
            _normalize_name(p)
            for p in json.loads(c["participants_json"])
            if p and p.lower() != "child"
        ]
        cand_parts = [p for p in cand_parts if p]

        cand_messages = json.loads(c["messages_json"])
        cand_texts_raw = [_normalize_text(m.get("text", "")) for m in cand_messages]
        cand_texts_set = {t for t in cand_texts_raw if t}

        part_hits = 0
        seen_cand: set[str] = set()
        for fp in frag_parts:
            for cp in cand_parts:
                if cp in seen_cand:
                    continue
                if _fuzzy_name_match(fp, cp):
                    part_hits += 1
                    seen_cand.add(cp)
                    break

        exact_hits = 0
        long_hits = 0
        for t in frag_texts:
            if t in cand_texts_set:
                exact_hits += 1
                if len(t) >= MATCH_LONG_MSG_MIN:
                    long_hits += 1

        fuzzy_hits = 0
        remaining = [t for t in frag_texts if t not in cand_texts_set and len(t) >= 10]
        if remaining:
            cand_long = [t for t in cand_texts_set if len(t) >= 10]
            for t in remaining:
                for ct in cand_long:
                    if difflib.SequenceMatcher(None, t, ct).ratio() >= 0.85:
                        fuzzy_hits += 1
                        break

        run_len = _longest_contiguous_run(frag_texts_raw, cand_texts_raw)

        total_hits = exact_hits + fuzzy_hits
        strong = long_hits >= 1 or total_hits >= 2 or run_len >= MATCH_MIN_RUN

        if frag_size == 1:
            # Only accept a single-message fragment when the one message
            # is itself distinctive (long exact / fuzzy / inside a run).
            single_ok = long_hits >= 1 or (run_len >= 1 and total_hits >= 1)
            strong = strong and single_ok

        score = (
            4 * part_hits
            + 6 * exact_hits
            + 5 * long_hits
            + 3 * fuzzy_hits
            + 8 * max(0, run_len - 1)
        )

        breakdowns.append(
            f"  conv={c['id']} parts={part_hits} exact={exact_hits} "
            f"long={long_hits} fuzzy={fuzzy_hits} run={run_len} "
            f"score={score} strong={strong}"
        )

        if not strong:
            continue
        if score > best_score:
            best_score = score
            best_id = int(c["id"])

    if logger.isEnabledFor(logging.DEBUG) and breakdowns:
        logger.debug("Match scoring:\n%s", "\n".join(breakdowns))

    if best_id is not None:
        logger.info(
            "Matched fragment (size=%d) to conv=%d (score=%d)",
            frag_size,
            best_id,
            best_score,
        )
        return best_id

    logger.info(
        "Creating new conversation (no candidate passed strong-match gate, fragment size=%d)",
        frag_size,
    )
    return None


def _longest_contiguous_run(frag_texts: list[str], cand_texts: list[str]) -> int:
    """Length of the longest contiguous in-order matching subsequence.

    Two positions match when their normalized texts are non-empty and
    equal. Used as a "prefix / sequence" signal: if the fragment's
    messages appear consecutively somewhere in the candidate (or vice
    versa), it is strong evidence of continuity even when individual
    messages on their own would be weak.
    """
    if not frag_texts or not cand_texts:
        return 0
    n, m = len(frag_texts), len(cand_texts)
    # Rolling DP on the previous row to keep memory small.
    prev = [0] * (m + 1)
    best = 0
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        fi = frag_texts[i - 1]
        if len(fi) < 4:
            # Short/empty fragment entries never contribute to a run.
            prev = cur
            continue
        for j in range(1, m + 1):
            if cand_texts[j - 1] and cand_texts[j - 1] == fi:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _messages_are_same(a_sender: str, a_text: str, b_sender: str, b_text: str) -> bool:
    """Are two messages the same real message modulo OCR noise?

    Senders must fuzzy-match (normalized + trailing digits/handles
    stripped). Then the texts must match by one of:
    - Identical normalized text
    - One normalized text is a prefix/suffix of the other (length >= 6)
    - Long messages (>= 10 chars) with SequenceMatcher ratio >= 0.85
    """
    sa = _normalize_name(a_sender)
    sb = _normalize_name(b_sender)
    if not _fuzzy_name_match(sa, sb):
        return False

    ta = _normalize_text(a_text)
    tb = _normalize_text(b_text)
    if not ta or not tb:
        return ta == tb
    if ta == tb:
        return True

    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(shorter) >= 6 and (longer.startswith(shorter) or longer.endswith(shorter)):
        return True

    return bool(
        min(len(ta), len(tb)) >= 10 and difflib.SequenceMatcher(None, ta, tb).ratio() >= 0.85
    )


def _better_sender(a: str, b: str) -> str:
    """Pick the fuller sender variant when OCR produced two readings."""
    if len(b) > len(a):
        return b
    return a


def _better_text(a: str, b: str) -> str:
    """Pick the fuller text variant when OCR truncated one reading."""
    na = _normalize_text(a)
    nb = _normalize_text(b)
    if len(nb) > len(na):
        return b
    if len(nb) < len(na):
        return a
    return b if len(b) > len(a) else a


def _fuzzy_merge(
    prior: list[dict[str, str]],
    new: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Deterministic OCR-tolerant message deduplication.

    Preserves prior chronological order; appends truly new messages at
    the end. When the same real-world message appears in both lists
    with OCR variation, the fuller sender and fuller text win.
    """
    if not prior:
        return _dedup_within(new)
    if not new:
        return _dedup_within(prior)

    result: list[dict[str, str]] = [dict(m) for m in prior]
    for nm in new:
        ns = nm.get("sender", "")
        nt = nm.get("text", "")
        match_idx = None
        for i, em in enumerate(result):
            if _messages_are_same(em.get("sender", ""), em.get("text", ""), ns, nt):
                match_idx = i
                break
        if match_idx is None:
            result.append({"sender": ns, "text": nt})
        else:
            em = result[match_idx]
            em["sender"] = _better_sender(em.get("sender", ""), ns)
            em["text"] = _better_text(em.get("text", ""), nt)

    return result


def _dedup_within(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse near-duplicate messages inside a single list (same OCR rules)."""
    result: list[dict[str, str]] = []
    for m in messages:
        s = m.get("sender", "")
        t = m.get("text", "")
        match_idx = None
        for i, em in enumerate(result):
            if _messages_are_same(em.get("sender", ""), em.get("text", ""), s, t):
                match_idx = i
                break
        if match_idx is None:
            result.append({"sender": s, "text": t})
        else:
            em = result[match_idx]
            em["sender"] = _better_sender(em.get("sender", ""), s)
            em["text"] = _better_text(em.get("text", ""), t)
    return result


def _normalize_name(s: str) -> str:
    """Collapse OCR variants of the same username to a single key.

    Strips trailing digits, punctuation, and short letter suffixes.
    ``Kidgamer09``, ``KidGamer09``, ``kidgamer`` all map to ``kidgamer``.
    ``Em``, ``Em_22`` map to ``em``. ``Lyla``, ``Lyla.x`` map to ``lyla``.
    """
    import re

    s = s.strip().lower()
    # strip trailing digit suffixes with optional punctuation (Em_22, 09)
    s = re.sub(r"[_\-\.\s]*\d+$", "", s)
    # strip trailing ".x" / ".y" style single-letter handles (Lyla.x)
    s = re.sub(r"[\.\-_][a-z]{1,2}$", "", s)
    # strip trailing punctuation
    s = re.sub(r"[\.\-_\s]+$", "", s)
    # collapse 3+ runs of same trailing letter (Maxxx → Max)
    s = re.sub(r"(.)\1{2,}$", r"\1", s)
    return s


def _dedup_participants(names: list[str]) -> list[str]:
    """Deduplicate a participant list, keeping the longest raw variant.

    Different OCR reads of the same username collapse to one entry so the
    dashboard doesn't render "Kidgamer09, KidGamer09, kidgamer" for what
    is really one person.
    """
    canonical: dict[str, str] = {}  # key → best display form
    for raw in names:
        name = (raw or "").strip()
        if not name:
            continue
        key = _normalize_name(name)
        if not key:
            continue
        existing = canonical.get(key)
        if existing is None or len(name) > len(existing):
            canonical[key] = name
    return list(canonical.values())
