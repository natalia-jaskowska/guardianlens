"""In-process application state shared by the FastAPI handlers.

The :class:`AppState` is the only thing the FastAPI route handlers reach
for. Everything they need to render the dashboard is hanging off it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
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
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._paused_total: float = 0.0
        self._latest_screenshot: str | None = None
        self._latest_platform: str | None = None
        self._scan_count: int = 0
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

    # ------------------------------------------------------------------ thread body

    def _run(self) -> None:
        for screenshot_path in capture_loop(self._config.monitor):
            if self._stop_event.is_set():
                break
            while self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(1)
            if self._stop_event.is_set():
                break

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
                continue

            with self._lock:
                self._scan_count += 1
                self._latest_screenshot = str(screenshot_path)
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


def _serialize_db_conversation(row: Any) -> dict[str, Any]:
    """Flatten a conversations DB row into the dashboard JSON shape."""
    status = json.loads(row["status_json"]) if row["status_json"] else {}
    messages = json.loads(row["messages_json"])
    participants = json.loads(row["participants_json"])
    return {
        "conversation_id": row["id"],
        "participant": participants[0] if participants else "Unknown",
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
        "narrative": status.get("narrative", ""),
        "alert_sent": False,
        "telegram_delivered": False,
        "escalation": None,
    }


def _build_session_narrative(
    conversations: list[dict],
    duration_s: float,
    alerts_count: int,
) -> dict[str, Any]:
    """Build the right-panel session overview narrative."""
    non_safe = [
        c for c in conversations
        if c["threat_level"] in {"caution", "warning", "alert", "critical"}
    ]
    safe = [c for c in conversations if c["threat_level"] == "safe"]

    concerns: list[dict[str, str]] = []
    for c in non_safe:
        concerns.append({
            "kind": "conversation",
            "name": c["participant"],
            "platform": c["platform"],
            "level": c["threat_level"],
            "category": c["category"],
            "summary": (
                c["narrative"][:140]
                if c.get("narrative")
                else f"{c['category']} pattern on {c['platform']}"
            ),
        })

    if any(c["level"] in {"alert", "critical"} for c in concerns):
        tone = "alert"
        headline = "Alerts active"
        subhead = f"{len(concerns)} concern{'s' if len(concerns) != 1 else ''} — review now"
    elif concerns:
        tone = "warning"
        headline = "Concerning patterns"
        subhead = f"{len(concerns)} concern{'s' if len(concerns) != 1 else ''} flagged"
    else:
        tone = "safe"
        headline = "Currently safe"
        subhead = (
            f"Normal activity across {len(conversations)} "
            f"place{'s' if len(conversations) != 1 else ''}"
            if conversations
            else "Monitoring — nothing flagged yet"
        )

    platforms_seen = {c["platform"] for c in conversations}
    total = len(conversations)
    safe_rate = round(100 * len(safe) / total) if total > 0 else 100

    safe_tokens = [c["participant"] for c in safe[:5]]
    safe_summary = ", ".join(safe_tokens) if safe_tokens else "—"

    what_to_do: list[str] = []
    grooming_names = [c["name"] for c in concerns if "grooming" in c.get("category", "")]
    bullying_names = [c["name"] for c in concerns if "bullying" in c.get("category", "")]
    if grooming_names:
        what_to_do.append(
            f"Have a calm conversation with your child about the {grooming_names[0]} interaction"
        )
    elif bullying_names:
        what_to_do.append(
            f"Offer emotional support around the {bullying_names[0]} exchanges"
        )
    elif concerns:
        what_to_do.append("Review the concerning activity with your child")

    if len(concerns) >= 2:
        what_to_do.append(
            "Ask who " + " and ".join(f'"{c["name"]}"' for c in concerns[:2]) + " are"
        )
    elif concerns:
        what_to_do.append(f"Ask who \"{concerns[0]['name']}\" is")

    if concerns:
        what_to_do.append(
            "Block and report "
            + ("them together" if len(concerns) >= 2 else f"{concerns[0]['name']}")
        )

    if not what_to_do:
        what_to_do = ["Keep monitoring — nothing actionable yet"]

    return {
        "headline": headline,
        "subhead": subhead,
        "tone": tone,
        "monitored": _pretty_duration(duration_s),
        "platforms_count": len(platforms_seen),
        "safe_rate": safe_rate,
        "concerns": concerns,
        "safe_summary": safe_summary,
        "safe_count": len(safe),
        "what_to_do": what_to_do,
        "alerts_count": alerts_count,
    }


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
        worst = _worst_level(conv_list)

        latest_payload = None
        if latest_screenshot:
            latest_payload = {
                "screenshot_path": latest_screenshot,
                "platform": latest_platform or "Unknown",
                "threat_level": worst,
                "reasoning": "",
                "confidence": 0,
                "indicators_found": [],
                "category": "none",
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
            "alert_total": self.database.total_alert_count(),
            "summary": summary,
            "timeline": [],
            "latest": latest_payload,
            "latest_alert": None,
            "is_alert": worst in {"alert", "critical"},
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
            ),
            "privacy": {
                "network": self.network_report,
                "delete_screenshots": self.config.privacy.delete_screenshots_after_analysis,
                "strip_raw_text": self.config.privacy.strip_raw_text_from_storage,
                "anonymize_child": self.config.privacy.anonymize_child_username,
            },
        }
