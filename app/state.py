"""In-process application state shared by the FastAPI handlers.

Why a state object instead of module-level globals: it lets the lifespan
context manager own the worker / database lifecycle (start on app
startup, stop on shutdown) and gives the test suite an easy injection
point.

The :class:`AppState` is the only thing the FastAPI route handlers reach
for. Everything they need to render the dashboard is hanging off it.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from app.serializers import (
    build_alert_history,
    build_session_health,
    compute_safe_streak,
    empty_summary,
    format_session_duration,
    metric_sublabels,
    serialize_analysis,
    serialize_scan_history,
    serialize_timeline,
    session_totals,
    stat_boxes,
)
from guardlens.alerts import AlertSender
from guardlens.analyzer import GuardLensAnalyzer
from guardlens.config import GuardLensConfig
from guardlens.database import GuardLensDatabase
from guardlens.demo import build_chat_messages
from guardlens.monitor import capture_loop
from guardlens.schema import ChatMessage, ScreenAnalysis
from guardlens.session_tracker import SessionTracker

logger = logging.getLogger(__name__)


class MonitorWorker:
    """Background thread that drives the capture/analyze/persist loop.

    Identical responsibilities to the previous Gradio worker — only the
    consumer changed (FastAPI SSE generator instead of Gradio Timer).
    """

    def __init__(
        self,
        config: GuardLensConfig,
        analyzer: GuardLensAnalyzer,
        session: SessionTracker,
        alerts: AlertSender,
        database: GuardLensDatabase,
    ) -> None:
        self._config = config
        self._analyzer = analyzer
        self._session = session
        self._alerts = alerts
        self._database = database
        self._queue: queue.Queue[ScreenAnalysis] = queue.Queue()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._paused_total: float = 0.0
        self._latest: ScreenAnalysis | None = None
        self._latest_alert: ScreenAnalysis | None = None
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
        if self._pause_event.is_set():
            return
        self._pause_event.set()
        self._paused_at = time.monotonic()
        logger.info("Monitor paused.")

    def resume(self) -> None:
        if not self._pause_event.is_set():
            return
        if self._paused_at is not None:
            self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None
        self._pause_event.clear()
        logger.info("Monitor resumed.")

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
        return self._thread is not None and not self._stop_event.is_set() and not self._pause_event.is_set()

    # ------------------------------------------------------------------ drain

    def drain(self) -> ScreenAnalysis | None:
        """Pop everything off the queue, persist it, return the most recent.

        Side effects:
        1. Push every drained analysis into the in-memory session window.
        2. Persist it to SQLite.
        3. Dispatch an alert if it meets the urgency threshold; record the
           outcome in the alerts table.
        4. Cache the most recent for the SSE stream.
        """
        drained: list[ScreenAnalysis] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                break
        latest: ScreenAnalysis | None = None
        for analysis in drained:
            self._session.add(analysis)
            analysis_id = self._database.record_analysis(analysis)
            delivered = self._alerts.maybe_send(analysis)
            if analysis.parent_alert is not None:
                self._database.record_alert(analysis_id, analysis, delivered=delivered)
            latest = analysis
            if analysis.classification.threat_level.value in {"alert", "critical"}:
                with self._lock:
                    self._latest_alert = analysis
        if latest is not None:
            with self._lock:
                self._latest = latest
        return latest

    @property
    def latest(self) -> ScreenAnalysis | None:
        with self._lock:
            return self._latest

    @property
    def latest_alert(self) -> ScreenAnalysis | None:
        with self._lock:
            return self._latest_alert

    def bootstrap_latest_alert(self, analysis: ScreenAnalysis | None) -> None:
        """Pre-populate ``_latest_alert`` from a previous DB session.

        Called by :class:`AppState` once on startup so the dashboard's
        right panel has content immediately instead of waiting for a
        new alert to land.
        """
        if analysis is None:
            return
        with self._lock:
            if self._latest_alert is None:
                self._latest_alert = analysis

    # ------------------------------------------------------------------ thread body

    def _run(self) -> None:
        for screenshot_path in capture_loop(self._config.monitor):
            if self._stop_event.is_set():
                break
            # Wait while paused — check every second for stop/resume
            while self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(1)
            if self._stop_event.is_set():
                break
            try:
                analysis = self._analyzer.analyze(screenshot_path)
            except Exception:  # noqa: BLE001 - never crash the loop
                logger.exception("Analyzer failed for %s", screenshot_path)
                continue
            # In demo mode the screenshot filename encodes the platform
            # and scenario (e.g. "demo_instagram_grooming_<ts>.png").
            # Use that to (1) override the platform with a section label
            # and (2) attach the structured chat messages so the
            # dashboard can render the fake-browser capture view.
            demo_meta = _parse_demo_filename(screenshot_path.name)
            updates: dict[str, object] = {}
            if demo_meta is not None:
                platform_key, scenario = demo_meta
                hint = _DEMO_SECTION_LABELS.get(platform_key)
                if hint is not None:
                    updates["platform"] = hint
                messages = [
                    ChatMessage(**msg) for msg in build_chat_messages(platform_key, scenario)
                ]
                if messages:
                    updates["chat_messages"] = messages
            if updates:
                analysis = analysis.model_copy(update=updates)
            self._queue.put(analysis)


_DEMO_SECTION_LABELS: dict[str, str] = {
    "minecraft": "Minecraft Chat",
    "discord": "Discord Chat",
    "instagram": "Instagram DM",
    "tiktok": "TikTok Comments",
}


def _parse_demo_filename(filename: str) -> tuple[str, str] | None:
    """Parse ``demo_<platform>_<scenario>_<timestamp>.png`` into (platform, scenario).

    Returns ``None`` if the filename doesn't match the demo naming
    pattern, leaving the model's own platform identification intact.
    """
    if not filename.startswith("demo_"):
        return None
    parts = filename.split("_", 3)
    if len(parts) < 4:
        return None
    return parts[1], parts[2]


class AppState:
    """Container for everything the FastAPI handlers need.

    One instance lives on ``app.state.guardlens`` for the duration of the
    process. Constructed inside the FastAPI lifespan handler so that the
    monitor thread starts when the server starts and stops cleanly when
    the server shuts down.
    """

    def __init__(self, config: GuardLensConfig) -> None:
        self.config = config
        self.analyzer = GuardLensAnalyzer(config.ollama)
        self.session = SessionTracker(config.session)
        self.alerts = AlertSender(config.alerts)
        self.database = GuardLensDatabase(config.database.path)
        self.worker = MonitorWorker(
            config=config,
            analyzer=self.analyzer,
            session=self.session,
            alerts=self.alerts,
            database=self.database,
        )

    # ------------------------------------------------------------------ lifecycle helpers

    def start(self) -> None:
        self.worker.start()
        # Bootstrap the right panel's "latest alert" from the database so it
        # has content immediately on restart instead of waiting for a new
        # alert to land. SKIP this in watch-folder mode — the user is
        # debugging real images that are mostly safe, and a stale
        # bootstrapped alert from a previous demo session would freeze
        # the right panel on irrelevant content. The JS falls back to
        # the latest scan when latest_alert is None.
        if self.config.monitor.watch_folder is None:
            self.worker.bootstrap_latest_alert(self.database.most_recent_alert_analysis())

    def stop(self) -> None:
        self.worker.stop()
        self.database.close()

    # ------------------------------------------------------------------ snapshot

    def build_state(self) -> dict[str, Any]:
        """One JSON-friendly snapshot of the dashboard state.

        Called by both the one-shot ``/api/state`` endpoint and the
        long-lived ``/api/stream`` SSE generator. Side effect: drains
        the worker queue.
        """
        self.worker.drain()
        latest = self.worker.latest
        latest_alert = self.worker.latest_alert
        summary = self.database.session_summary() if self.worker.is_running else empty_summary()
        totals = session_totals(summary)
        history = self.session.recent()
        latest_payload = serialize_analysis(latest, history=history) if latest is not None else None
        latest_alert_payload = (
            serialize_analysis(latest_alert, history=history) if latest_alert is not None else None
        )

        # Telegram-style delivered timestamp for the parent alert preview.
        for payload in (latest_payload, latest_alert_payload):
            if payload is not None and payload.get("parent_alert"):
                recent_alert_rows = self.database.recent_alerts(limit=1)
                delivered_at: str | None = None
                if recent_alert_rows:
                    delivered_at = recent_alert_rows[0]["sent_at"]
                payload["parent_alert"]["delivered_at"] = delivered_at
                payload["parent_alert"]["channel"] = "Telegram"

        session_id = self.database.session_id if self.worker.is_running else None
        session_health = build_session_health(
            totals=totals,
            session_duration=format_session_duration(self.worker.session_seconds),
            model_name=self.config.ollama.inference_model,
            platform_counts=self.database.session_platform_counts(session_id),
            avg_inference_seconds=self.database.session_avg_inference_seconds(session_id),
            monitoring=self.worker.is_running,
            # Scope the "last alert" reference to the current session so a
            # fresh restart doesn't surface a stale alert from yesterday.
            last_alert=self.database.last_alert_summary(session_id=session_id),
        )

        alert_history = build_alert_history(self.database.recent_alert_analyses(limit=30))

        return {
            "monitoring": self.worker.is_running,
            "paused": self.worker.is_paused,
            "session_duration": format_session_duration(self.worker.session_seconds),
            "model_name": self.config.ollama.inference_model,
            "db_path": str(self.config.database.path),
            "current_session_id": session_id,
            "metrics": totals,
            "metric_sublabels": metric_sublabels(totals),
            "stat_boxes": stat_boxes(latest, history),
            "scan_history": serialize_scan_history(self.database.recent_threat_levels(limit=30)),
            "safe_streak": compute_safe_streak(history),
            "session_health": session_health,
            "alert_history": alert_history,
            "alert_total": self.database.total_alert_count(),
            "summary": summary,
            # Timeline display is decoupled from SessionTracker's
            # in-memory window — that one is sized for the AI's
            # cross-reference logic, this one is a UX surface and
            # benefits from more rows. Pulled straight from the DB,
            # then reversed because serialize_timeline expects
            # oldest-first input.
            "timeline": serialize_timeline(
                list(reversed(self.database.recent_analyses_models(limit=15)))
            ),
            "latest": latest_payload,
            "latest_alert": latest_alert_payload,
            "is_alert": latest is not None and latest.classification.threat_level.value
            in {"alert", "critical"},
        }
