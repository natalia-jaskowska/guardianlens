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
    serialize_session_verdict,
    serialize_timeline,
    session_totals,
    stat_boxes,
)
from guardlens.alerts import AlertSender
from guardlens.analyzer import GuardLensAnalyzer
from guardlens.classifier import ContentClassifier
from guardlens.config import GuardLensConfig
from guardlens.conversation_analyzer import ConversationAnalyzer
from guardlens.conversation_store import ConversationStore, ParticipantTracker
from guardlens.database import GuardLensDatabase
from guardlens.demo import build_chat_messages
from guardlens.environment import EnvironmentMonitor
from guardlens.escalation import EscalationTracker
from guardlens.monitor import capture_loop
from guardlens.privacy import NetworkGuard, PrivacyGuard
from guardlens.schema import (
    AlertUrgency,
    ChatMessage,
    ContentType,
    ParentAlert,
    ScreenAnalysis,
    SessionCertainty,
    SessionVerdict,
    ThreatLevel,
)
from guardlens.session_tracker import SessionTracker

logger = logging.getLogger(__name__)


# MVP threshold: re-run the conversation analyzer every N new unique
# messages accumulated in the store. Low = responsive but noisy; high =
# rare but stable. 3 is a reasonable starting point for demo pacing.
CONVERSATION_ANALYSIS_EVERY_N_NEW_MESSAGES = 3

# Sliding window: only feed the last N messages to the conversation
# analyzer. Old messages from earlier, unrelated conversations age out.
CONVERSATION_WINDOW_SIZE = 25

# Ordering used by the session-alert high-water dedup. Higher rank =
# more severe. Must include every :class:`ThreatLevel` value.
_LEVEL_RANK: dict[ThreatLevel, int] = {
    ThreatLevel.SAFE: 0,
    ThreatLevel.CAUTION: 1,
    ThreatLevel.WARNING: 2,
    ThreatLevel.ALERT: 3,
    ThreatLevel.CRITICAL: 4,
}


class MonitorWorker:
    """Background thread that drives the capture/analyze/persist loop.

    The FastAPI SSE generator (``/api/stream``) polls the worker's queue
    to push fresh state snapshots to the browser.
    """

    def __init__(
        self,
        config: GuardLensConfig,
        analyzer: GuardLensAnalyzer,
        session: SessionTracker,
        alerts: AlertSender,
        database: GuardLensDatabase,
        conversation_store: ConversationStore,
        conversation_analyzer: ConversationAnalyzer,
        classifier: ContentClassifier | None = None,
        participant_tracker: ParticipantTracker | None = None,
        environment_monitor: EnvironmentMonitor | None = None,
        escalation_tracker: EscalationTracker | None = None,
        privacy_guard: PrivacyGuard | None = None,
    ) -> None:
        self._config = config
        self._analyzer = analyzer
        self._session = session
        self._alerts = alerts
        self._database = database
        self._conversation_store = conversation_store
        self._conversation_analyzer = conversation_analyzer
        # New conversation-centric helpers. Kept optional so the
        # existing pipeline tests that predate them don't need to
        # know they exist — but in the real AppState wiring they are
        # always supplied.
        self._classifier = classifier or ContentClassifier()
        self._participants = participant_tracker or ParticipantTracker()
        self._environments = environment_monitor or EnvironmentMonitor(
            tracker=self._participants
        )
        self._escalation = escalation_tracker or EscalationTracker()
        self._privacy = privacy_guard or PrivacyGuard(config.privacy)
        self._queue: queue.Queue[ScreenAnalysis] = queue.Queue()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._paused_total: float = 0.0
        self._latest: ScreenAnalysis | None = None
        self._latest_alert: ScreenAnalysis | None = None
        self._latest_session_verdict: SessionVerdict | None = None
        # Per-category "high-water mark" of the highest level we've already
        # fired a session alert for. A session alert only fires when the
        # current verdict's level STRICTLY EXCEEDS the previous max for its
        # category — so safe→warning→alert fires twice (ratcheting up), but
        # alert→warning→alert fires zero more times (regression + re-peak
        # are both silent). This prevents spam from model oscillation.
        self._session_alert_high_water: dict[str, int] = {}
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
        """True when the session is active (running or paused). Used for data queries."""
        return self._thread is not None and not self._stop_event.is_set()

    @property
    def is_scanning(self) -> bool:
        """True when actively capturing and analyzing. False when paused."""
        return self.is_running and not self._pause_event.is_set()

    # ------------------------------------------------------------------ drain

    def drain(self) -> ScreenAnalysis | None:
        """Pop everything off the queue, persist it, return the most recent.

        Side effects:
        1. Push every drained analysis into the in-memory session window.
        2. Persist it to SQLite.
        3. Dispatch an alert if it meets the urgency threshold; record the
           outcome in the alerts table.
        4. Cache the most recent for the SSE stream.
        5. Feed visible_messages into the ConversationStore and,
           if enough new messages have accumulated, trigger a text-only
           conversation-level re-analysis.
        """
        drained: list[ScreenAnalysis] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                break
        latest: ScreenAnalysis | None = None
        latest_analysis_id: int | None = None
        for analysis in drained:
            # Canonicalize the platform string up front so DB rows, the
            # capture status bar (reads self._latest), and the
            # conversation/environment cards all render the same name.
            # Without this, a verbose model output like
            # "chat/messaging platform (likely discord)" lands raw in
            # the DB and the status bar while the cards show "discord".
            raw_platform = (
                analysis.platform
                or analysis.classification.platform_detected
                or "unknown"
            )
            canonical = _canonical_platform(raw_platform)
            if canonical and canonical != raw_platform:
                analysis = analysis.model_copy(update={"platform": canonical})

            self._session.add(analysis)
            analysis_id = self._database.record_analysis(analysis)
            latest_analysis_id = analysis_id
            # Per-frame alerts are DISABLED — we only fire session-level
            # alerts from _maybe_fire_session_alert() after the
            # ConversationAnalyzer has accumulated enough cross-message
            # context.  Per-frame parent_alert (if any) is still logged
            # but NOT persisted or delivered.
            if analysis.parent_alert is not None:
                logger.debug(
                    "Per-frame alert SKIPPED (frame=%s, urgency=%s) — "
                    "waiting for session-level context",
                    analysis.screenshot_path.name,
                    analysis.parent_alert.urgency.value,
                )
            latest = analysis
            # Publish the current frame as _latest BEFORE the conversation
            # analyzer runs. _maybe_fire_session_alert reads self._latest
            # to build the session-alert stub; if _latest is stale (or
            # None on the first frame) the stub is missing and the alert
            # is silently dropped.
            with self._lock:
                self._latest = analysis

            # Feed the conversation store from whichever source has messages.
            # Demo mode (synthetic scenarios) pre-populates
            # ``analysis.chat_messages`` from the known scenario script.
            # Real vision mode fills ``classification.visible_messages`` via
            # the model's OCR. Prefer classification.visible_messages because
            # that's what the real pipeline will produce; fall back to
            # chat_messages so demo mode keeps working.
            extracted = (
                analysis.classification.visible_messages
                or analysis.chat_messages
                or []
            )
            logger.info(
                "Frame messages: %d extracted (source=%s, frame=%s)",
                len(extracted),
                "visible_messages" if analysis.classification.visible_messages else (
                    "chat_messages" if analysis.chat_messages else "none"
                ),
                analysis.screenshot_path.name,
            )
            if extracted:
                self._conversation_store.add(extracted)

            # --- Conversation-centric routing --------------------------------
            # Stamp content_type on the analysis, then route the frame.
            # CONVERSATION  → accumulate under a per-participant store and
            #                 update the per-participant ConversationContext.
            # ENVIRONMENT   → observe the space and let the monitor decide
            #                 whether any user should be promoted to a
            #                 tracked conversation (targeting detection).
            # Escalation is tracked per-participant on the CONVERSATION
            # path and per-environment on the ENVIRONMENT path.
            self._route_frame(analysis, extracted)

            # Privacy: delete the screenshot once analysis is done, if the
            # config flag is set. The watch-folder mode runs against
            # real sample images we want to keep, so the flag stays off
            # by default — turn it on for live capture / privacy-strict
            # demos.
            self._privacy.delete_screenshot(analysis.screenshot_path)

            # Decide whether to trigger conversation-level re-analysis.
            # The conversation analyzer should stay aligned with the
            # current frame. We always pass the frame's classification
            # as context so the model knows what's on screen NOW.
            #
            # Triggers:
            #  A) Enough new unique messages accumulated (steady-state).
            #  B) Non-safe frame — always re-run.
            #  C) Safe frame but stale non-safe verdict — re-run so the
            #     verdict can downgrade.
            threshold = CONVERSATION_ANALYSIS_EVERY_N_NEW_MESSAGES
            frame_level = analysis.classification.threat_level

            # Always build frame context so the conversation analyzer
            # knows what's currently on screen.
            frame_hint: dict[str, str] = {
                "level": frame_level.value,
                "category": analysis.classification.category.value,
                "confidence": str(round(analysis.classification.confidence)),
                "reasoning": analysis.classification.reasoning or "",
            }

            should_run = False
            if self._conversation_store.unacknowledged_new >= threshold:
                should_run = True

            with self._lock:
                sv = self._latest_session_verdict

            if frame_level != ThreatLevel.SAFE:
                should_run = True
            elif sv is not None and sv.overall_level != ThreatLevel.SAFE:
                should_run = True

            if should_run and self._conversation_store.size > 0:
                self._run_conversation_analysis(latest_analysis_id, frame_hint=frame_hint)

        # self._latest is kept in sync inside the loop so the
        # conversation analyzer can anchor alerts on the current frame.
        return latest

    def _route_frame(
        self,
        analysis: ScreenAnalysis,
        extracted: list[ChatMessage],
    ) -> None:
        """Route a per-frame analysis to conversation or environment tracking.

        Side effects:

        - Sets ``analysis.content_type`` (via the classifier).
        - Updates :class:`ParticipantTracker` for CONVERSATION frames.
        - Updates :class:`EnvironmentMonitor` for ENVIRONMENT frames, and
          may promote targeting users into participant tracking.
        - Feeds :class:`EscalationTracker` with the per-participant level
          so the dashboard can flag rising trajectories.
        """
        ct = self._classifier.classify(analysis)
        # The platform has already been canonicalized in drain() before
        # this frame was persisted, so every consumer below sees the
        # same string.
        platform = (
            analysis.platform
            or analysis.classification.platform_detected
            or "unknown"
        )
        cls = analysis.classification

        if ct == ContentType.CONVERSATION:
            participants = self._non_child_senders(extracted)
            # In a DM there is normally one non-child participant. If the
            # model surfaces more (e.g., a small group DM), track each.
            if not participants and analysis.classification.extracted_users:
                participants = [
                    u for u in analysis.classification.extracted_users
                    if u and u.lower() not in {"you", "me", "child"}
                ]

            if not participants:
                logger.debug(
                    "Conversation frame has no identifiable participant — "
                    "skipping per-participant tracking (frame=%s).",
                    analysis.screenshot_path.name,
                )
                return

            for participant in participants:
                messages_for_user = [
                    m for m in extracted
                    if (m.sender or "").strip() == participant
                ] or extracted  # fall back to all messages if none match
                self._participants.add_for_participant(
                    platform, participant, messages_for_user
                )
                self._participants.update_context(
                    platform,
                    participant,
                    threat_level=cls.threat_level,
                    category=cls.category,
                    confidence=cls.confidence,
                    narrative=cls.reasoning or "",
                    indicators=list({*cls.indicators_found}),
                    grooming_stage=(
                        analysis.grooming_stage.stage
                        if analysis.grooming_stage
                        else None
                    ),
                )
                verdict = self._escalation.observe(
                    platform, participant, cls.threat_level, cls.indicators_found
                )
                if verdict.escalating:
                    logger.info(
                        "Escalation flagged: %s/%s — speed=%.2f highest=%s",
                        platform,
                        participant,
                        verdict.escalation_speed,
                        verdict.highest_level.value,
                    )
            return

        # ENVIRONMENT path
        env_ctx = self._environments.observe(analysis)
        promoted = self._environments.detect_and_promote(analysis)
        for user in promoted:
            # Promoted users inherit the environment's current level so
            # the escalation tracker has a starting point.
            self._escalation.observe(
                env_ctx.platform, user, cls.threat_level, cls.indicators_found
            )

    @staticmethod
    def _non_child_senders(messages: list[ChatMessage]) -> list[str]:
        """Distinct non-child senders in frame order."""
        out: list[str] = []
        for m in messages:
            s = (m.sender or "").strip()
            if not s or s.lower() in {"you", "me", "child"}:
                continue
            if s not in out:
                out.append(s)
        return out

    def _run_conversation_analysis(
        self,
        last_analysis_id: int | None = None,
        frame_hint: dict[str, str] | None = None,
    ) -> None:
        """Call the text-only analyzer and cache the resulting verdict.

        *frame_hint* carries the current frame's classification so the
        conversation analyzer can align its verdict with what's on screen.
        """
        conversation = self._conversation_store.recent_messages(CONVERSATION_WINDOW_SIZE)
        logger.info(
            "Triggering conversation analyzer over %d messages "
            "(window=%d, total=%d, unacknowledged=%d, frame_hint=%s)",
            len(conversation),
            CONVERSATION_WINDOW_SIZE,
            self._conversation_store.size,
            self._conversation_store.unacknowledged_new,
            bool(frame_hint),
        )
        verdict = self._conversation_analyzer.analyze(conversation, frame_hint=frame_hint)
        if verdict is not None:
            with self._lock:
                self._latest_session_verdict = verdict
            self._maybe_fire_session_alert(verdict, last_analysis_id)
        self._conversation_store.acknowledge()

    def _maybe_fire_session_alert(
        self,
        verdict: SessionVerdict,
        last_analysis_id: int | None,
    ) -> None:
        """Synthesize a parent alert from a session verdict and persist it.

        Gating rules (in order):

        1. Verdict must explicitly flag ``parent_alert_recommended``.
        2. Certainty must be MEDIUM or HIGH — we never fire on LOW
           certainty, even if the level is critical. The rationale is
           that a single suspicious message should not escalate the
           parent; wait for cross-message evidence.
        3. Overall level must be WARNING or higher.
        4. Dedup: only fire when the (level, category, certainty) tuple
           differs from the last alert we fired. This prevents spam as
           the same verdict is re-confirmed across successive conversation
           analyzer runs.

        When all gates pass, we synthesize a :class:`ParentAlert` from
        the verdict's narrative and reuse the existing DB path
        (``database.record_alert``) by attaching the synthetic alert to a
        copy of the latest frame analysis.
        """
        if not verdict.parent_alert_recommended:
            logger.debug("Session alert gate: parent_alert_recommended=False")
            return
        if verdict.certainty == SessionCertainty.LOW:
            logger.debug(
                "Session alert gate: certainty=LOW (level=%s)",
                verdict.overall_level.value,
            )
            return
        if verdict.overall_level not in {
            ThreatLevel.WARNING,
            ThreatLevel.ALERT,
            ThreatLevel.CRITICAL,
        }:
            logger.debug(
                "Session alert gate: level=%s below threshold",
                verdict.overall_level.value,
            )
            return

        # Monotonic high-water-mark dedup per category.
        # Only fire if the current level STRICTLY EXCEEDS the previous max
        # for this category. This absorbs the model's wobble between
        # warning/alert for the same conversation without suppressing
        # legitimate escalation from warning to alert to critical.
        category = verdict.overall_category.value
        level_rank = _LEVEL_RANK[verdict.overall_level]
        previous_max = self._session_alert_high_water.get(category, -1)
        if level_rank <= previous_max:
            logger.debug(
                "Session alert gate: dedup — %s=%d is not above previous max %d",
                verdict.overall_level.value,
                level_rank,
                previous_max,
            )
            return
        self._session_alert_high_water[category] = level_rank

        synthetic = _build_session_parent_alert(verdict)

        # Reuse the existing record_alert path by attaching the synthetic
        # alert to a copy of the latest frame analysis. This keeps the
        # DB schema unchanged and puts the session alert in the same
        # alerts table the dashboard already reads from.
        stub_analysis: ScreenAnalysis | None = None
        with self._lock:
            if self._latest is not None:
                stub_analysis = self._latest.model_copy(
                    update={"parent_alert": synthetic}
                )

        if last_analysis_id is None or stub_analysis is None:
            logger.warning(
                "Session alert fired but no analysis_id to anchor it "
                "(category=%s level=%s)",
                category,
                verdict.overall_level.value,
            )
            return

        alert_id = self._database.record_alert(
            last_analysis_id, stub_analysis, delivered=False
        )

        # Update the "latest alert" pointer so the right panel shows
        # the session alert immediately, not the stale frame alert.
        with self._lock:
            self._latest_alert = stub_analysis

        logger.warning(
            "SESSION ALERT fired (alert_id=%d, category=%s level=%s certainty=%s): %s",
            alert_id,
            category,
            verdict.overall_level.value,
            verdict.certainty.value,
            verdict.narrative[:120],
        )

    @property
    def latest(self) -> ScreenAnalysis | None:
        with self._lock:
            return self._latest

    @property
    def latest_alert(self) -> ScreenAnalysis | None:
        with self._lock:
            return self._latest_alert

    @property
    def latest_session_verdict(self) -> SessionVerdict | None:
        with self._lock:
            return self._latest_session_verdict

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
            logger.info("Analyzing screenshot: %s", screenshot_path.name)
            try:
                analysis = self._analyzer.analyze(screenshot_path)
            except Exception:  # noqa: BLE001 — broad by design: daemon thread must not crash
                logger.exception("Analyzer failed for %s", screenshot_path)
                continue
            level = analysis.classification.threat_level.value
            category = analysis.classification.category.value
            confidence = round(analysis.classification.confidence)
            logger.info(
                "Scan result: %s · %s · %d%% · %.2fs",
                level.upper(),
                category,
                confidence,
                analysis.inference_seconds,
            )
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


def _serialize_conversation(
    ctx,
    escalation: EscalationTracker,
) -> dict[str, Any]:
    """Flatten one :class:`ConversationContext` into dashboard JSON.

    Overlays the latest :class:`EscalationVerdict` so the card can show
    "escalating" / "speed" without the JS having to compute it.
    """
    verdict = escalation.verdict_for(ctx.platform, ctx.participant)
    return {
        "participant": ctx.participant,
        "platform": ctx.platform,
        "source": ctx.source,
        "first_seen": ctx.first_seen.isoformat(),
        "last_seen": ctx.last_seen.isoformat(),
        "message_count": ctx.message_count,
        "threat_level": ctx.threat_level.value,
        "category": ctx.category.value,
        "grooming_stage": ctx.grooming_stage.value if ctx.grooming_stage else None,
        "indicators": list(ctx.indicators),
        "confidence": ctx.confidence,
        "narrative": ctx.narrative,
        "alert_sent": ctx.alert_sent,
        "telegram_delivered": ctx.telegram_delivered,
        "escalation": (
            {
                "escalating": verdict.escalating,
                "speed": verdict.escalation_speed,
                "highest_level": verdict.highest_level.value,
                "indicators_growth": verdict.indicators_growth,
                "observations": verdict.observation_count,
            }
            if verdict is not None
            else None
        ),
    }


def _serialize_environment(ctx) -> dict[str, Any]:
    """Flatten one :class:`EnvironmentContext` into dashboard JSON."""
    return {
        "platform": ctx.platform,
        "context": ctx.context,
        "content_type": ctx.content_type_label,
        "first_seen": ctx.first_seen.isoformat(),
        "last_seen": ctx.last_seen.isoformat(),
        "user_count": ctx.user_count,
        "overall_safety": ctx.overall_safety.value,
        "content_summary": ctx.content_summary,
        "promoted_users": list(ctx.promoted_users),
        "indicators": list(ctx.indicators),
    }


_DEMO_SECTION_LABELS: dict[str, str] = {
    "minecraft": "Minecraft Chat",
    "discord": "Discord Chat",
    "instagram": "Instagram DM",
    "tiktok": "TikTok Comments",
}


def _build_session_narrative(
    conversations: list,
    environments: list,
    duration_s: float,
    alerts_count: int,
) -> dict[str, Any]:
    """Build the right-panel "Session overview" narrative for the dashboard.

    Produces the plain-language parent-facing story described in
    DASHBOARD_DESIGN_FINAL.md.  Intentionally non-LLM for now — we have
    structured per-participant / per-environment state already, so a
    deterministic template is faster and as legible. A future revision
    can swap in a Gemma 4 call without changing the return shape.

    Returns a dict with:
      - headline: "Currently safe" / "Alerts active" / "Concerning patterns"
      - subhead: one-liner context ("Normal gameplay" / "3 concerns detected")
      - monitored: pretty duration
      - platforms_count: int
      - safe_rate: float (0-100)
      - concerns: list of {name, platform, summary, level} newest first
      - safe_summary: string ("TikTok, Instagram feed, PixelBuilder")
      - what_to_do: list of consolidated action strings
      - tone: one of safe|warning|alert
    """
    non_safe_convs = [
        c for c in conversations
        if c["threat_level"] in {"caution", "warning", "alert", "critical"}
    ]
    non_safe_envs = [
        e for e in environments
        if e["overall_safety"] in {"caution", "warning", "alert", "critical"}
    ]
    safe_convs = [c for c in conversations if c["threat_level"] == "safe"]
    safe_envs = [e for e in environments if e["overall_safety"] == "safe"]

    # Concerns are per-USER. An environment is concerning because of the
    # people in it (surfaced via promoted users, which are already in
    # conversations). Listing both would double-count: "NitroBot on
    # Discord" would show up a second time as "Discord environment".
    concerns: list[dict[str, str]] = []
    for c in non_safe_convs:
        concerns.append(
            {
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
            }
        )
    # Environments are context, not concerns. If a space has something
    # worth alerting on, the promoted-user mechanism surfaces it as a
    # per-user concern. The narrative talks about PEOPLE.

    # Overall tone
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
            f"Normal activity across {len(conversations) + len(environments)} "
            f"place{'s' if len(conversations) + len(environments) != 1 else ''}"
            if conversations or environments
            else "Monitoring — nothing flagged yet"
        )

    # Platform count (union of platforms seen)
    platforms_seen = {c["platform"] for c in conversations} | {
        e["platform"] for e in environments
    }
    total_obs = len(conversations) + len(environments)
    safe_rate = (
        round(100 * (len(safe_convs) + len(safe_envs)) / total_obs)
        if total_obs > 0
        else 100
    )

    # Safe summary line
    safe_tokens: list[str] = []
    for e in safe_envs[:3]:
        safe_tokens.append(e["platform"])
    for c in safe_convs[:3]:
        safe_tokens.append(c["participant"])
    safe_summary = ", ".join(safe_tokens) if safe_tokens else "—"

    # Consolidated "what to do" — references ALL concerning parties
    what_to_do: list[str] = []
    grooming_names = [c["name"] for c in concerns if "grooming" in c.get("category", "")]
    bullying_names = [c["name"] for c in concerns if "bullying" in c.get("category", "")]
    other_names = [
        c["name"] for c in concerns
        if not any(k in c.get("category", "") for k in ("grooming", "bullying"))
    ]
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
        "safe_count": len(safe_convs) + len(safe_envs),
        "what_to_do": what_to_do,
        "alerts_count": alerts_count,
    }


_PLATFORM_CANON: list[tuple[tuple[str, ...], str]] = [
    # (fragments that must appear in the raw string, canonical name)
    (("instagram",), "instagram"),
    (("discord",), "discord"),
    (("minecraft",), "minecraft"),
    (("roblox",), "roblox"),
    (("fortnite",), "fortnite"),
    (("tiktok",), "tiktok"),
    (("youtube",), "youtube"),
    (("snapchat",), "snapchat"),
    (("whatsapp",), "whatsapp"),
    (("telegram",), "telegram"),
    (("messenger", "facebook"), "messenger"),
    (("imessage",), "imessage"),
]


def _canonical_platform(raw: str) -> str:
    """Collapse verbose model outputs to a single canonical platform name.

    The vision model sometimes returns strings like
    ``"chat/messaging platform (likely discord)"`` — each variant would
    otherwise open its own :class:`EnvironmentContext`, so the dashboard
    ends up with a fan of near-duplicate cards. This helper maps any
    string containing a known platform fragment to that platform's
    canonical lowercase name.  Generic chat-like descriptions with no
    identifiable brand collapse into a single ``chat`` bucket so they
    don't each spawn their own environment card.
    """
    if not raw:
        return "unknown"
    low = raw.strip().lower()
    # 1) Brand hit.
    for fragments, canon in _PLATFORM_CANON:
        if any(frag in low for frag in fragments):
            return canon
    # 2) Generic chat-like description — collapse to a single "chat"
    #    bucket instead of keeping each variant phrase separate.
    chat_hints = ("chat", "messaging", "group chat", "dm")
    if any(h in low for h in chat_hints):
        return "chat"
    # 3) Feed-like description.
    if any(h in low for h in ("feed", "video", "stream")):
        return "feed"
    # 4) Nothing matched — return the stripped original.
    return low


def _pretty_duration(seconds: float) -> str:
    """Format 4327s → '1h 12m'. Used by the session narrative."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _build_session_parent_alert(verdict: SessionVerdict) -> ParentAlert:
    """Synthesize a :class:`ParentAlert` from a conversation-level verdict.

    Mapping:

    - ``alert_title`` -> "Session: <category> pattern detected"
    - ``summary``     -> verdict.narrative (already parent-appropriate)
    - ``recommended_action`` -> heuristic based on category
    - ``urgency``     -> derived from (level, certainty)
    """
    category = verdict.overall_category.value
    level = verdict.overall_level
    certainty = verdict.certainty

    # Urgency mapping. Certainty=HIGH + level=CRITICAL is immediate;
    # everything else steps down one notch from its frame-level analogue
    # so that session alerts don't out-shout true per-frame critical hits.
    if level == ThreatLevel.CRITICAL and certainty == SessionCertainty.HIGH:
        urgency = AlertUrgency.IMMEDIATE
    elif level in {ThreatLevel.CRITICAL, ThreatLevel.ALERT}:
        urgency = AlertUrgency.HIGH
    elif level == ThreatLevel.WARNING:
        urgency = AlertUrgency.MEDIUM
    else:
        urgency = AlertUrgency.LOW

    title = f"Session: {category.replace('_', ' ')} pattern detected"

    # Pick a recommended action per category. Generic fallback if none.
    action = {
        "grooming": (
            "Review the conversation with your child. Explain why this "
            "pattern (age questions, platform migration, secrecy) is "
            "dangerous. Consider blocking the contact."
        ),
        "bullying": (
            "Talk to your child about what you've seen. Screenshot the "
            "conversation for the school if the attacker is a classmate. "
            "Offer support — this is not your child's fault."
        ),
        "scam": (
            "Do not click any links or share credentials. Show your child "
            "how to recognise phishing. Report the account to the platform."
        ),
        "personal_info_sharing": (
            "Check what personal details have been shared (school, address, "
            "phone, photos). Tighten privacy settings and review who can "
            "contact your child."
        ),
        "inappropriate_content": (
            "Review the content with your child in an age-appropriate way. "
            "Consider enabling platform-level content filters."
        ),
    }.get(category, "Review the full conversation and decide next steps.")

    return ParentAlert(
        alert_title=title,
        summary=verdict.narrative,
        recommended_action=action,
        urgency=urgency,
    )


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
        self.conversation_store = ConversationStore()
        self.conversation_analyzer = ConversationAnalyzer(config.ollama)
        # New conversation-centric components.
        self.classifier = ContentClassifier()
        self.participant_tracker = ParticipantTracker()
        self.environment_monitor = EnvironmentMonitor(tracker=self.participant_tracker)
        self.escalation_tracker = EscalationTracker()
        self.privacy_guard = PrivacyGuard(config.privacy)
        # Audit the network stance at startup so the dashboard can
        # surface "Fully local" with confidence.
        self.network_report = NetworkGuard.verify_no_egress(config.ollama.host)
        self.worker = MonitorWorker(
            config=config,
            analyzer=self.analyzer,
            session=self.session,
            alerts=self.alerts,
            database=self.database,
            conversation_store=self.conversation_store,
            conversation_analyzer=self.conversation_analyzer,
            classifier=self.classifier,
            participant_tracker=self.participant_tracker,
            environment_monitor=self.environment_monitor,
            escalation_tracker=self.escalation_tracker,
            privacy_guard=self.privacy_guard,
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
        # Query once, reuse for both payloads.
        _alert_rows: list | None = None
        for payload in (latest_payload, latest_alert_payload):
            if payload is not None and payload.get("parent_alert"):
                if _alert_rows is None:
                    _alert_rows = self.database.recent_alerts(limit=1)
                delivered_at = _alert_rows[0]["sent_at"] if _alert_rows else None
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
            "monitoring": self.worker.is_scanning,
            "paused": self.worker.is_paused,
            "capture_interval_seconds": self.config.monitor.capture_interval_seconds,
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
            # benefits from more rows. recent_analyses_models returns
            # newest-first; serialize_timeline expects oldest-first.
            "timeline": serialize_timeline(
                reversed(self.database.recent_analyses_models(limit=25))
            ),
            "latest": latest_payload,
            "latest_alert": latest_alert_payload,
            "is_alert": latest is not None and latest.classification.threat_level.value
            in {"alert", "critical"},
            "session_verdict": serialize_session_verdict(
                self.worker.latest_session_verdict
            ),
            "conversation_size": self.conversation_store.size,
            "conversation_pending": self.conversation_store.unacknowledged_new > 0,
            "alert_timestamps": [card["timestamp"] for card in alert_history],
            # Conversation-centric state: one card per tracked participant,
            # one card per tracked public space. Serializers turn these
            # into the dashboard's circle-avatar / square-icon cards.
            "conversations": (_conv_list := [
                _serialize_conversation(ctx, self.escalation_tracker)
                for ctx in self.participant_tracker.contexts()
            ]),
            "environments": (_env_list := [
                _serialize_environment(ctx)
                for ctx in self.environment_monitor.environments()
            ]),
            "session_narrative": _build_session_narrative(
                _conv_list,
                _env_list,
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
