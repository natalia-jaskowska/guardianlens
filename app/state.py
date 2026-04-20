"""In-process application state shared by the FastAPI handlers.

The :class:`AppState` is the only thing the FastAPI route handlers reach
for. Everything they need to render the dashboard is hanging off it.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

from app.serializers import (
    build_alert_history,
    build_session_health,
    empty_summary,
    format_session_duration,
    metric_sublabels,
    serialize_scan_history,
    session_totals,
)
from guardlens.alerts import AlertSender
from guardlens.config import GuardLensConfig
from guardlens.database import GuardLensDatabase
from guardlens.monitor import capture_loop
from guardlens.pipeline import ConversationPipeline
from guardlens.privacy import NetworkGuard, PrivacyGuard

logger = logging.getLogger(__name__)


class MonitorWorker:
    """Background thread that drives the capture → pipeline loop.

    All conversation state lives in SQLite via :class:`ConversationPipeline`.
    The worker tracks only lifecycle (start/stop/pause) and a lightweight
    latest-frame reference for the capture card.
    """

    def __init__(
        self,
        config: GuardLensConfig,
        pipeline: ConversationPipeline,
        alerts: AlertSender,
        database: GuardLensDatabase,
        privacy_guard: PrivacyGuard | None = None,
    ) -> None:
        self._config = config
        self._pipeline = pipeline
        self._alerts = alerts
        self._database = database
        self._privacy = privacy_guard or PrivacyGuard(config.privacy)
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._frame_queue: queue.Queue[Path | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._paused_total: float = 0.0
        self._latest_screenshot: str | None = None
        self._latest_platform: str | None = None
        self._latest_conv_ids: list[int] = []
        self._scan_count: int = 0
        self._session_peak: str = "safe"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._thread is not None:
            return
        self._database.start_session(notes="FastAPI dashboard launch")
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="guardlens-monitor", daemon=True)
        self._thread.start()
        logger.info("Monitor thread started.")

    def stop(self) -> None:
        self._stop_event.set()
        self._database.end_session()
        logger.info("Monitor thread stop requested.")

    def pause(self) -> None:
        with self._lock:
            if self._pause_event.is_set():
                return
            self._pause_event.set()
            self._paused_at = time.monotonic()
        logger.info("Monitor paused at %.1fs session time.", self.session_seconds)

    def resume(self) -> None:
        with self._lock:
            if not self._pause_event.is_set():
                return
            if self._paused_at is not None:
                paused_duration = time.monotonic() - self._paused_at
                self._paused_total += paused_duration
                self._paused_at = None
            self._pause_event.clear()
        logger.info("Monitor resumed (was paused for %.1fs total).", self._paused_total)

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    @property
    def session_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        elapsed = time.monotonic() - self._started_at - self._paused_total
        if self._paused_at is not None:
            elapsed -= time.monotonic() - self._paused_at
        return max(0.0, elapsed)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and not self._stop_event.is_set()

    @property
    def is_scanning(self) -> bool:
        return self.is_running and not self._pause_event.is_set()

    @property
    def scan_count(self) -> int:
        with self._lock:
            return self._scan_count

    @property
    def latest_screenshot(self) -> str | None:
        with self._lock:
            return self._latest_screenshot

    @property
    def latest_platform(self) -> str | None:
        with self._lock:
            return self._latest_platform

    @property
    def latest_conv_ids(self) -> list[int]:
        with self._lock:
            return list(self._latest_conv_ids)

    @property
    def session_peak(self) -> str:
        with self._lock:
            return self._session_peak

    def bump_peak(self, level: str) -> None:
        """Raise the session high-water mark if ``level`` is worse."""
        order = {"safe": 0, "caution": 1, "warning": 2, "alert": 3, "critical": 4}
        with self._lock:
            if order.get(level, 0) > order.get(self._session_peak, 0):
                self._session_peak = level

    # ------------------------------------------------------------------ thread body

    def push_frame(self, path: Path) -> None:
        """Enqueue an externally supplied frame for processing (receive mode)."""
        self._frame_queue.put(path)

    def _run(self) -> None:
        if self._config.monitor.receive_mode:
            self._run_receive_mode()
        else:
            self._run_capture_mode()

    def _run_receive_mode(self) -> None:
        logger.info("Monitor running in receive mode — waiting for frames via API.")
        while not self._stop_event.is_set():
            try:
                path = self._frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if path is None:
                break
            self._process_frame(path)

    def _run_capture_mode(self) -> None:
        for screenshot_path in capture_loop(self._config.monitor):
            if self._stop_event.is_set():
                break
            while self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(1)
            if self._stop_event.is_set():
                break
            self._process_frame(screenshot_path)

    def _process_frame(self, screenshot_path: Path) -> None:
        logger.info("Processing screenshot: %s", screenshot_path.name)
        try:
            conv_ids = self._pipeline.push_screenshot(
                screenshot_path,
                self._database,
                self._alerts,
                stale_minutes=self._config.conversation.stale_minutes,
            )
        except Exception:
            logger.exception("Pipeline failed for %s", screenshot_path)
            return

        with self._lock:
            self._scan_count += 1
            self._latest_screenshot = str(screenshot_path)
            self._latest_conv_ids = list(conv_ids)
            if conv_ids:
                row = self._database.get_conversation(conv_ids[0])
                if row:
                    self._latest_platform = row["platform"]

        self._privacy.delete_screenshot(screenshot_path)

        logger.info(
            "Pipeline done: %d conversation(s) updated — %s",
            len(conv_ids),
            screenshot_path.name,
        )


# ====================================================================== helpers


def _participant_label(c: dict) -> str:
    """Format the participant list like the activity card — up to 3, +N overflow."""
    names = c.get("participants") or ([c["participant"]] if c.get("participant") else [])
    if not names:
        return "Unknown"
    shown = ", ".join(names[:3])
    return f"{shown} +{len(names) - 3}" if len(names) > 3 else shown


def _serialize_db_conversation(row: Any) -> dict[str, Any]:
    """Flatten a conversations DB row into the dashboard JSON shape."""
    status = json.loads(row["status_json"]) if row["status_json"] else {}
    messages = json.loads(row["messages_json"])
    participants = json.loads(row["participants_json"])
    screenshots_raw = json.loads(row["screenshots_json"]) if row["screenshots_json"] else []
    screenshots = [
        {"url": f"/screenshots/{Path(s['path']).name}", "timestamp": s.get("timestamp", "")}
        for s in screenshots_raw if s.get("path")
    ]
    return {
        "conversation_id": row["id"],
        "participant": participants[0] if participants else "Unknown",
        "participants": participants,
        "platform": row["platform"],
        "source": "direct",
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "message_count": len(messages),
        "threat_level": status.get("threat_level", "safe"),
        "category": status.get("category", "none"),
        "grooming_stage": status.get("grooming_stage"),
        "indicators": status.get("indicators", []),
        "confidence": status.get("confidence", 0),
        "short_summary": status.get("short_summary", ""),
        "narrative": status.get("narrative", ""),
        "reasoning": status.get("reasoning", ""),
        "alert_sent": False,
        "telegram_delivered": False,
        "escalation": None,
        "screenshots": screenshots,
    }


def _build_session_narrative(
    conversations: list[dict],
    duration_s: float,
    alerts_count: int,
    peak: str = "safe",
    latest_level: str = "safe",
    latest_conv: dict | None = None,
) -> dict[str, Any]:
    """Build the right-panel session overview narrative.

    The hero (big headline + tone) reflects the LATEST frame so the
    right panel stays in sync with the live-capture tile on the left.
    The concerns list below still shows every conversation flagged
    during the session — that's the historical log, not the "now".
    """
    non_safe = [
        c for c in conversations
        if c["threat_level"] in {"caution", "warning", "alert", "critical"}
    ]
    safe = [c for c in conversations if c["threat_level"] == "safe"]

    concerns: list[dict[str, str]] = []
    for c in non_safe:
        concerns.append({
            "kind": "conversation",
            "name": _participant_label(c),
            "platform": c["platform"],
            "level": c["threat_level"],
            "category": c["category"],
            "conversation_id": c.get("conversation_id"),
            "participant": c.get("participant"),
            "summary": (
                c.get("short_summary")
                or c.get("narrative")
                or f"{c['category']} pattern on {c['platform']}"
            ),
        })

    if latest_level in {"alert", "critical"}:
        tone = "alert"
        headline = "Alert active"
        subhead = (
            latest_conv.get("short_summary") if latest_conv and latest_conv.get("short_summary")
            else "Latest capture shows a high-severity pattern"
        )
    elif latest_level in {"warning", "caution"}:
        tone = "warning"
        headline = "Concerning pattern"
        subhead = (
            latest_conv.get("short_summary") if latest_conv and latest_conv.get("short_summary")
            else "Latest capture flagged for review"
        )
    else:
        tone = "safe"
        if concerns:
            headline = "Currently safe"
            subhead = (
                f"Latest capture is clear — {len(concerns)} earlier "
                f"concern{'s' if len(concerns) != 1 else ''} still in view"
            )
        elif conversations:
            headline = "Currently safe"
            subhead = (
                f"Normal activity across {len(conversations)} "
                f"place{'s' if len(conversations) != 1 else ''}"
            )
        else:
            headline = "Currently safe"
            subhead = "Monitoring — nothing flagged yet"

    platforms_seen = {c["platform"] for c in conversations}
    total = len(conversations)
    safe_rate = round(100 * len(safe) / total) if total > 0 else 100

    safe_tokens = [c["participant"] for c in safe[:5]]
    safe_summary = ", ".join(safe_tokens) if safe_tokens else "—"

    what_to_do = _build_recommendations(
        latest_level=latest_level,
        latest_conv=latest_conv,
        concerns=concerns,
    )

    # Pick the conversation whose threat_level matches the session peak.
    # That's the one Peak links to so clicking it jumps to that detail.
    peak_rank = {"safe": 0, "caution": 1, "warning": 2, "alert": 3, "critical": 4}
    peak_conv_summary = None
    if peak != "safe":
        peak_conv = next(
            (c for c in conversations if c["threat_level"] == peak),
            None,
        )
        if peak_conv:
            peak_conv_summary = {
                "conversation_id": peak_conv.get("conversation_id"),
                "platform": peak_conv["platform"],
                "participant": peak_conv.get("participant"),
                "name": _participant_label(peak_conv),
                "short_summary": (
                    peak_conv.get("short_summary")
                    or peak_conv.get("narrative")
                    or f"{peak_conv.get('category', '')} pattern"
                ),
                "category": peak_conv.get("category"),
            }

    return {
        "headline": headline,
        "subhead": subhead,
        "tone": tone,
        "monitored": _pretty_duration(duration_s),
        "platforms_count": len(platforms_seen),
        "conversations_count": len(conversations),
        "peak": peak,
        "peak_conv": peak_conv_summary,
        "safe_rate": safe_rate,
        "concerns": concerns,
        "safe_summary": safe_summary,
        "safe_count": len(safe),
        "what_to_do": what_to_do,
        "alerts_count": alerts_count,
    }


def _build_recommendations(
    latest_level: str,
    latest_conv: dict | None,
    concerns: list[dict],
) -> list[str]:
    """Parent-facing action list for the right-panel Recommendations card.

    Priorities, in order:

    1. Ground the first line in the LATEST frame's verdict — not in any
       non-safe conversation ever seen in the session. Stale concerns
       should not keep telling the parent to "block" someone.
    2. Pull the conversation's own model-written ``short_summary`` into
       that first line so it's specific ("asked the child's age and
       offered exclusive coaching") instead of a generic "have a
       conversation".
    3. Branch by category — grooming, bullying, scam, other — with
       actionable, platform-aware follow-ups.
    4. Soft follow-up when the latest is safe but earlier concerns
       exist. No "block and report" calls when nothing is happening now.
    """
    level = latest_level or "safe"
    if level == "safe":
        if concerns:
            top = concerns[0]
            cat = (top.get("category") or "").lower()
            cat_label = (
                "grooming conversation" if "grooming" in cat
                else "bullying episode" if "bullying" in cat
                else "scam / phishing attempt" if "scam" in cat or "phish" in cat
                else "concerning activity"
            )
            return [
                f'Things look calm right now. Earlier "{top["name"]}" was flagged for a {cat_label} — review when you can.',
                "Stay available — your child may bring it up on their own.",
            ]
        return ["All clear. Keep monitoring — nothing actionable yet."]

    if not latest_conv:
        return ["Review the concerning activity with your child."]

    name = latest_conv.get("participant") or latest_conv.get("name") or "the user"
    platform = latest_conv.get("platform") or "the platform"
    summary = (
        latest_conv.get("short_summary")
        or latest_conv.get("narrative")
        or ""
    ).strip()
    category = (latest_conv.get("category") or "").lower()

    summary_tail = f" ({summary})" if summary and len(summary) <= 220 else ""

    recs: list[str] = []
    if "grooming" in category:
        recs.append(
            f"Talk to your child calmly about their chat with {name}{summary_tail}"
        )
        recs.append(
            f'Ask how they met {name} and whether {name} has asked personal questions or offered gifts.'
        )
        recs.append(
            f"Consider blocking and reporting {name} on {platform}."
        )
    elif "bullying" in category:
        recs.append(
            f"Check in emotionally about the exchange with {name}{summary_tail}"
        )
        recs.append(
            "Save screenshots before anything is deleted — they may be needed for the school or platform."
        )
        recs.append(
            f"Consider muting or blocking {name} and reporting the messages to {platform}."
        )
    elif "scam" in category or "phish" in category:
        recs.append(
            f"Make sure your child hasn't clicked any links from {name}{summary_tail}"
        )
        recs.append(
            "Remind them: real giveaways never require password or account verification."
        )
        recs.append(
            f"Report {name} as a scam on {platform} and block the account."
        )
    else:
        recs.append(
            f"Review the chat with {name} together{summary_tail}"
        )
        recs.append(
            f"Ask your child to walk you through what happened before and after the flagged moment."
        )

    if len(concerns) >= 2:
        others = [c["name"] for c in concerns if c.get("participant") != latest_conv.get("participant")][:2]
        if others:
            recs.append(
                f'Also check earlier concerns: {", ".join(others)}.'
            )

    return recs


def _pretty_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _worst_level(conversations: list[dict]) -> str:
    """Return the worst threat level across all conversations."""
    order = {"safe": 0, "caution": 1, "warning": 2, "alert": 3, "critical": 4}
    worst = "safe"
    for c in conversations:
        lvl = c.get("threat_level", "safe")
        if order.get(lvl, 0) > order.get(worst, 0):
            worst = lvl
    return worst


# ====================================================================== AppState


class AppState:
    """Container for everything the FastAPI handlers need."""

    def __init__(self, config: GuardLensConfig) -> None:
        self.config = config
        self.alerts = AlertSender(config.alerts)
        self.database = GuardLensDatabase(config.database.path)
        self.pipeline = ConversationPipeline(config.ollama)
        self.privacy_guard = PrivacyGuard(config.privacy)
        self.network_report = NetworkGuard.verify_no_egress(config.ollama.host)
        self.worker = MonitorWorker(
            config=config,
            pipeline=self.pipeline,
            alerts=self.alerts,
            database=self.database,
            privacy_guard=self.privacy_guard,
        )

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()
        self.database.close()

    def build_state(self) -> dict[str, Any]:
        """One JSON-friendly snapshot of the dashboard state.

        Called by both ``/api/state`` and the SSE ``/api/stream`` generator.
        All conversation data comes from SQLite — no in-memory trackers.
        """
        summary = self.database.session_summary() if self.worker.is_running else empty_summary()
        totals = session_totals(summary)
        # Override scan count with the worker's real screenshot count —
        # the analyses table only stores fired alerts now, not every frame.
        totals["screenshots"] = self.worker.scan_count

        session_id = self.database.session_id if self.worker.is_running else None
        session_health = build_session_health(
            totals=totals,
            session_duration=format_session_duration(self.worker.session_seconds),
            model_name=self.config.ollama.inference_model,
            platform_counts=self.database.session_platform_counts(session_id),
            avg_inference_seconds=self.database.session_avg_inference_seconds(session_id),
            monitoring=self.worker.is_running,
            last_alert=self.database.last_alert_summary(session_id=session_id),
        )

        alert_history = build_alert_history(self.database.recent_alert_analyses(limit=30))

        conv_rows = self.database.all_conversations(limit=50)
        conv_list = [_serialize_db_conversation(r) for r in conv_rows]

        latest_screenshot = self.worker.latest_screenshot
        latest_platform = self.worker.latest_platform
        alerting_count = sum(
            1 for c in conv_list
            if c["threat_level"] in {"warning", "alert", "critical"}
        )
        totals["alerts"] = alerting_count

        # Update session high-water mark.
        for c in conv_list:
            self.worker.bump_peak(c["threat_level"])
        peak = self.worker.session_peak

        # Live capture card reflects the LATEST frame, not the overall worst.
        # Pick the worst-level conversation from the most recently processed
        # screenshot (the pipeline returned its IDs).
        latest_conv_ids = set(self.worker.latest_conv_ids)
        latest_convs = [c for c in conv_list if c.get("conversation_id") in latest_conv_ids]
        latest_worst = _worst_level(latest_convs) if latest_convs else "safe"
        latest_worst_conv = next(
            (c for c in latest_convs if c["threat_level"] == latest_worst and latest_worst != "safe"),
            None,
        )

        latest_payload = None
        if latest_screenshot:
            filename = Path(latest_screenshot).name
            latest_payload = {
                "screenshot_path": latest_screenshot,
                "screenshot_url": f"/screenshots/{filename}",
                "platform": latest_platform or "Unknown",
                "threat_level": latest_worst,
                "reasoning": latest_worst_conv["short_summary"] if latest_worst_conv else "",
                "confidence": latest_worst_conv["confidence"] if latest_worst_conv else 0,
                "indicators_found": latest_worst_conv["indicators"] if latest_worst_conv else [],
                "category": latest_worst_conv["category"] if latest_worst_conv else "none",
            }

        return {
            "monitoring": self.worker.is_scanning,
            "paused": self.worker.is_paused,
            "capture_interval_seconds": self.config.monitor.capture_interval_seconds,
            "session_duration": format_session_duration(self.worker.session_seconds),
            "model_name": self.config.ollama.inference_model,
            "db_path": str(self.config.database.path),
            "current_session_id": session_id,
            "metrics": totals,
            "metric_sublabels": metric_sublabels(totals),
            "stat_boxes": [],
            "scan_history": serialize_scan_history(self.database.recent_threat_levels(limit=30)),
            "safe_streak": 0,
            "session_health": session_health,
            "alert_history": alert_history,
            "alert_total": alerting_count,
            "summary": summary,
            "timeline": [],
            "latest": latest_payload,
            "latest_alert": None,
            "is_alert": latest_worst in {"alert", "critical"},
            "session_verdict": None,
            "conversation_size": sum(c["message_count"] for c in conv_list),
            "conversation_pending": False,
            "alert_timestamps": [card["timestamp"] for card in alert_history],
            "conversations": conv_list,
            "environments": [],
            "session_narrative": _build_session_narrative(
                conv_list,
                self.worker.session_seconds,
                self.database.total_alert_count(),
                peak=peak,
                latest_level=latest_worst,
                latest_conv=latest_worst_conv,
            ),
            "privacy": {
                "network": self.network_report,
                "delete_screenshots": self.config.privacy.delete_screenshots_after_analysis,
                "strip_raw_text": self.config.privacy.strip_raw_text_from_storage,
                "anonymize_child": self.config.privacy.anonymize_child_username,
            },
        }
