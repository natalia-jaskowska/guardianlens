"""Gradio live monitoring dashboard for GuardianLens.

Run with::

    python run.py
    # or
    uv run python -m app.dashboard

The dashboard:

1. Spins up a background thread that captures the screen every
   ``capture_interval_seconds`` and pushes each :class:`ScreenAnalysis` into
   a thread-safe queue.
2. Every analysis is persisted to SQLite via :class:`GuardLensDatabase`.
   This is what makes function calling "actually execute" — every
   ``classify_threat`` / ``generate_parent_alert`` result lands in a real,
   on-disk row that judges can inspect after the demo.
3. The Gradio UI polls the worker and renders:
   - A live status badge (SAFE / CAUTION / WARNING / ALERT / CRITICAL).
   - The latest screenshot.
   - A timeline of recent verdicts.
   - A clickable thinking-chain panel for the most recent analysis.
   - Per-threat-level session counts read from the database.
4. The :class:`AlertSender` is invoked for any analysis that meets the
   configured minimum urgency. Both attempts (successful or not) are
   recorded in the ``alerts`` SQLite table.

The Gradio code stays small on purpose. The "best demo > best benchmark"
principle from CONTEXT.md applies: a clean, fast UI matters more than
feature breadth.
"""

from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime
from pathlib import Path

import gradio as gr

from guardlens.alerts import AlertSender
from guardlens.analyzer import GuardLensAnalyzer
from guardlens.config import GuardLensConfig, load_config
from guardlens.database import GuardLensDatabase
from guardlens.monitor import capture_loop
from guardlens.schema import ScreenAnalysis, ThreatLevel
from guardlens.session_tracker import SessionTracker
from guardlens.utils import configure_logging, seed_everything

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------- worker


class MonitorWorker:
    """Background thread that drives the capture/analyze/persist loop."""

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
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._database.start_session(notes="Dashboard launch")
        self._thread = threading.Thread(target=self._run, name="guardlens-monitor", daemon=True)
        self._thread.start()
        logger.info("Monitor thread started.")

    def stop(self) -> None:
        self._stop_event.set()
        self._database.end_session()
        logger.info("Monitor thread stop requested.")

    def latest(self) -> ScreenAnalysis | None:
        """Drain the queue and return the most recent analysis (if any).

        Side effects, in order:
        1. Push every drained analysis into the in-memory session window.
        2. Persist it to SQLite.
        3. Dispatch an alert if it meets the urgency threshold; record the
           outcome in the alerts table.
        """
        latest: ScreenAnalysis | None = None
        drained: list[ScreenAnalysis] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                break
        for analysis in drained:
            self._session.add(analysis)
            analysis_id = self._database.record_analysis(analysis)
            delivered = self._alerts.maybe_send(analysis)
            if analysis.parent_alert is not None:
                self._database.record_alert(analysis_id, analysis, delivered=delivered)
            latest = analysis
        return latest

    def _run(self) -> None:
        for screenshot_path in capture_loop(self._config.monitor):
            if self._stop_event.is_set():
                break
            try:
                analysis = self._analyzer.analyze(screenshot_path)
            except Exception:  # noqa: BLE001 - never crash the loop
                logger.exception("Analyzer failed for %s", screenshot_path)
                continue
            self._queue.put(analysis)


# ----------------------------------------------------------------------- rendering


_LEVEL_COLOR: dict[ThreatLevel, str] = {
    ThreatLevel.SAFE: "#22c55e",
    ThreatLevel.CAUTION: "#eab308",
    ThreatLevel.WARNING: "#f97316",
    ThreatLevel.ALERT: "#ef4444",
    ThreatLevel.CRITICAL: "#b91c1c",
}


def _render_status(analysis: ScreenAnalysis | None) -> str:
    if analysis is None:
        return "<div style='padding:1em'>Waiting for first capture...</div>"
    level = analysis.classification.threat_level
    color = _LEVEL_COLOR[level]
    return (
        f"<div style='padding:1em;border-radius:0.5em;background:{color};color:white;font-size:1.4em'>"
        f"<strong>{level.value.upper()}</strong> &nbsp;"
        f"({analysis.classification.confidence:.0f}% confidence) &nbsp;"
        f"category: {analysis.classification.category.value}"
        f"</div>"
    )


def _render_timeline(session: SessionTracker) -> list[list[str]]:
    rows: list[list[str]] = []
    for analysis in session.recent():
        rows.append(
            [
                analysis.timestamp.strftime("%H:%M:%S"),
                analysis.classification.threat_level.value,
                analysis.classification.category.value,
                f"{analysis.classification.confidence:.0f}",
                analysis.platform or "Unknown",
            ]
        )
    return rows


def _render_session_stats(database: GuardLensDatabase) -> str:
    summary = database.session_summary()
    parts = []
    for level in ThreatLevel:
        color = _LEVEL_COLOR[level]
        parts.append(
            f"<span style='display:inline-block;padding:0.4em 0.8em;margin:0.2em;"
            f"border-radius:0.4em;background:{color};color:white'>"
            f"{level.value}: <strong>{summary[level.value]}</strong></span>"
        )
    return "<div>" + "".join(parts) + "</div>"


def _render_thinking(analysis: ScreenAnalysis | None) -> str:
    if analysis is None:
        return ""
    parts: list[str] = []
    parts.append(f"### Reasoning\n{analysis.classification.reasoning}")
    if analysis.classification.indicators_found:
        bullets = "\n".join(f"- {ind}" for ind in analysis.classification.indicators_found)
        parts.append(f"### Indicators\n{bullets}")
    if analysis.grooming_stage is not None:
        parts.append(
            f"### Grooming stage\n**{analysis.grooming_stage.stage.value}**"
            f" (escalating: {analysis.grooming_stage.risk_escalation})"
        )
        if analysis.grooming_stage.evidence:
            evidence = "\n".join(f"- {e}" for e in analysis.grooming_stage.evidence)
            parts.append(evidence)
    if analysis.parent_alert is not None:
        parts.append(
            f"### Parent alert\n**{analysis.parent_alert.alert_title}**\n\n"
            f"{analysis.parent_alert.summary}\n\n"
            f"Recommended action: {analysis.parent_alert.recommended_action}\n\n"
            f"Urgency: `{analysis.parent_alert.urgency.value}`"
        )
    if analysis.raw_thinking:
        parts.append(f"### Raw thinking\n```\n{analysis.raw_thinking}\n```")
    return "\n\n".join(parts)


# ----------------------------------------------------------------------- app


def build_app(
    config: GuardLensConfig,
    worker: MonitorWorker,
    session: SessionTracker,
    database: GuardLensDatabase,
) -> gr.Blocks:
    """Construct the Gradio Blocks interface."""
    last_analysis: dict[str, ScreenAnalysis | None] = {"value": None}

    def refresh() -> tuple[str, str | None, list[list[str]], str, str, str]:
        new = worker.latest()
        if new is not None:
            last_analysis["value"] = new
        current = last_analysis["value"]
        screenshot = str(current.screenshot_path) if current is not None else None
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        footer = f"Last refresh: {ts} &middot; window={len(session)}"
        return (
            _render_status(current),
            screenshot,
            _render_timeline(session),
            _render_thinking(current),
            _render_session_stats(database),
            footer,
        )

    with gr.Blocks(title=config.dashboard.title) as app:
        gr.Markdown(f"# {config.dashboard.title}")
        gr.Markdown(
            "On-device child safety monitor powered by Gemma 4 via Ollama. "
            "Captures the screen, analyzes for grooming/bullying/inappropriate content, "
            "and explains every decision."
        )
        status = gr.HTML()
        session_stats = gr.HTML(label="Session totals")
        with gr.Row():
            screenshot = gr.Image(label="Latest screenshot", type="filepath")
            thinking = gr.Markdown()
        timeline = gr.Dataframe(
            headers=["Time", "Level", "Category", "Confidence", "Platform"],
            label="Recent analyses",
            interactive=False,
        )
        footer = gr.Markdown()

        timer = gr.Timer(value=2.0)
        timer.tick(
            fn=refresh,
            inputs=None,
            outputs=[status, screenshot, timeline, thinking, session_stats, footer],
        )

    return app


# ----------------------------------------------------------------------- entry point


def main(config_path: Path | None = None) -> None:
    """Launch the dashboard. Used by both ``python -m app.dashboard`` and the CLI script."""
    config = load_config(config_path)
    configure_logging(config.log_level)
    seed_everything(config.seed)

    analyzer = GuardLensAnalyzer(config.ollama)
    session = SessionTracker(config.session)
    alerts = AlertSender(config.alerts)
    database = GuardLensDatabase(config.database.path)
    worker = MonitorWorker(config, analyzer, session, alerts, database)
    worker.start()

    try:
        app = build_app(config, worker, session, database)
        app.launch(
            server_name=config.dashboard.server_name,
            server_port=config.dashboard.server_port,
            share=config.dashboard.share,
        )
    finally:
        worker.stop()
        database.close()


if __name__ == "__main__":
    main()
