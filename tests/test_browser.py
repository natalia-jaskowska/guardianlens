"""Browser-based integration tests using Playwright.

These tests start a real FastAPI server (with a mocked Ollama backend)
and drive a headless Chromium browser to verify that the dashboard
renders, updates via SSE, and interactive elements work.

The dashboard uses a conversation-first layout:
  Left panel:  live capture card, stats row, activity list
  Right panel: 3 states — session overview | conversation detail | environment detail

Requires: ``pip install playwright pytest-playwright``
          ``playwright install chromium``
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from app.server import create_app
from playwright.sync_api import Page, expect

from guardlens.config import GuardLensConfig
from guardlens.schema import (
    AlertUrgency,
    ChatMessage,
    GroomingStage,
    GroomingStageResult,
    ParentAlert,
    ScreenAnalysis,
    ThreatCategory,
    ThreatClassification,
    ThreatLevel,
)

_PIPELINE_OLLAMA_RESPONSE: dict[str, Any] = {
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "function": {
                    "name": "extract_conversations",
                    "arguments": {"conversations": []},
                }
            }
        ],
    }
}


def _make_alert_analysis(tmp_path: Path) -> ScreenAnalysis:
    return ScreenAnalysis(
        timestamp=datetime.now(),
        screenshot_path=tmp_path / "screenshots" / "fake_alert.png",
        platform="Discord",
        classification=ThreatClassification(
            threat_level=ThreatLevel.ALERT,
            category=ThreatCategory.GROOMING,
            confidence=92.0,
            reasoning="User asked age, offered gifts, suggested private DM.",
            indicators_found=["age inquiry", "gift offer", "platform switch"],
            platform_detected="Discord",
            visible_messages=[
                ChatMessage(sender="ShadowPro", text="how old are you?"),
                ChatMessage(sender="child", text="14"),
                ChatMessage(sender="ShadowPro", text="cool, wanna add me on snap?"),
            ],
        ),
        grooming_stage=GroomingStageResult(
            stage=GroomingStage.TRUST_BUILDING,
            evidence=["asked age", "platform migration"],
            risk_escalation=True,
        ),
        parent_alert=ParentAlert(
            alert_title="Session: grooming pattern detected",
            summary="ShadowPro escalated from greeting to age inquiry to platform migration.",
            recommended_action="Review the conversation with your child.",
            urgency=AlertUrgency.HIGH,
        ),
        inference_seconds=8.5,
    )


@pytest.fixture(scope="module")
def server_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Start a real FastAPI server on a random port and return its URL."""
    from unittest.mock import patch

    tmp = tmp_path_factory.mktemp("browser")
    screenshots_dir = tmp / "screenshots"
    screenshots_dir.mkdir()
    (screenshots_dir / "fake_alert.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    cfg = GuardLensConfig()
    cfg.database.path = tmp / "test.db"
    cfg.monitor.screenshots_dir = screenshots_dir
    cfg.monitor.demo_mode = True
    cfg.monitor.capture_interval_seconds = 300.0  # effectively never auto-capture
    cfg.dashboard.server_port = 0
    cfg.dashboard.title = "GuardianLens — Test"

    with patch("guardlens.pipeline.ollama.Client") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.chat.return_value = _PIPELINE_OLLAMA_RESPONSE

        app = create_app(cfg)

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)

        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("Server did not start within 10 seconds")

        sockets = server.servers[0].sockets
        port = sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"

        # Inject a conversation + alert so the dashboard has content to render.
        state = app.state.guardlens
        alert = _make_alert_analysis(tmp)
        analysis_id = state.database.record_analysis(alert)
        state.database.record_alert(analysis_id, alert, delivered=False)
        state.database.create_conversation(
            platform="Discord",
            participants=["ShadowPro"],
            first_seen=datetime.now().isoformat(),
            messages=[
                {"sender": "ShadowPro", "text": "how old are you?"},
                {"sender": "child", "text": "14"},
                {"sender": "ShadowPro", "text": "cool, wanna add me on snap?"},
            ],
            screenshots=[
                {
                    "path": str(tmp / "screenshots" / "fake_alert.png"),
                    "timestamp": datetime.now().isoformat(),
                }
            ],
            status={
                "threat_level": "alert",
                "category": "grooming",
                "confidence": 92,
                "grooming_stage": "trust_building",
                "indicators": ["age inquiry", "gift offer", "platform switch"],
                "narrative": "ShadowPro escalated from greeting to age inquiry to platform migration.",
                "reasoning": "User asked age, offered gifts, suggested private DM.",
                "parent_alert_recommended": True,
                "certainty": "high",
            },
            status_reasoning="User asked age, offered gifts, suggested private DM.",
        )

        yield base_url

        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPageLoad:
    """Verify the dashboard loads and renders the conversation-first shell."""

    def test_page_title(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page).to_have_title("GuardianLens — Test")

    def test_header_brand_visible(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator(".gl-brand")).to_contain_text("GuardianLens")

    def test_pause_button_visible(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator("#pauseBtn")).to_be_visible()

    def test_alerts_bell_visible(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator("#bellWrap")).to_be_visible()

    def test_overview_hero_renders(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator("#overviewHero")).to_be_visible()

    def test_left_panel_has_activity_list(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator("#activityList")).to_be_attached()

    def test_right_panel_has_three_states(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # All three right-panel states are attached; exactly one is visible
        # at any time (controlled by the [hidden] attribute).
        expect(page.locator("#stateSession")).to_be_attached()
        expect(page.locator("#stateConversation")).to_be_attached()
        expect(page.locator("#stateEnvironment")).to_be_attached()

    def test_environment_state_starts_hidden(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator("#stateEnvironment")).to_be_hidden()

    def test_privacy_pill_visible(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator(".gl-privacy-pill").first).to_be_visible()


class TestSSEUpdates:
    """Verify the SSE stream connects and updates the DOM."""

    def test_activity_list_populates(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # After SSE delivers the first snapshot, our injected conversation
        # should show up as a .gl-card.
        card = page.locator(".gl-card").first
        expect(card).to_be_visible(timeout=10_000)

    def test_conversation_card_shows_participant(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-card").first
        expect(card).to_be_visible(timeout=10_000)
        expect(card).to_contain_text("ShadowPro")

    def test_stats_row_has_values(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # Wait for SSE to render — stat cells should be attached.
        expect(page.locator("#ovMonitored")).to_be_visible(timeout=10_000)
        expect(page.locator("#ovConversations")).to_be_visible()
        expect(page.locator("#ovSafeRate")).to_be_visible()

    def test_no_js_errors_on_render(self, page: Page, server_url: str) -> None:
        """No uncaught JS errors during SSE-driven rendering."""
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        # Wait for first render cycle via the conversation card.
        expect(page.locator(".gl-card").first).to_be_visible(timeout=10_000)
        page.wait_for_timeout(2000)
        assert errors == [], f"JS errors during rendering: {errors}"


class TestPauseResume:
    """Verify the pause/resume button toggles monitoring state."""

    def test_pause_and_resume(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        btn = page.locator("#pauseBtn")
        expect(btn).to_be_visible()

        # Click pause — button gets .paused class.
        btn.click()
        page.wait_for_function(
            "() => document.getElementById('pauseBtn').classList.contains('paused')",
            timeout=5_000,
        )
        expect(btn).to_have_class(re.compile(r"paused"))

        # Click resume — .paused class is removed.
        btn.click()
        page.wait_for_function(
            "() => !document.getElementById('pauseBtn').classList.contains('paused')",
            timeout=5_000,
        )


class TestAlertsBell:
    """Verify the alerts bell menu toggles and shows alert count."""

    def test_bell_opens_alerts_menu(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # Wait for initial render.
        expect(page.locator(".gl-card").first).to_be_visible(timeout=10_000)

        menu = page.locator("#alertsMenu")
        expect(menu).to_be_hidden()

        page.locator("#bellWrap").click()
        expect(menu).to_be_visible(timeout=3_000)

    def test_alerts_close_button_works(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator(".gl-card").first).to_be_visible(timeout=10_000)

        page.locator("#bellWrap").click()
        expect(page.locator("#alertsMenu")).to_be_visible(timeout=3_000)

        page.locator("#alertsClose").click()
        expect(page.locator("#alertsMenu")).to_be_hidden(timeout=3_000)


class TestConversationDetail:
    """Verify clicking a conversation card opens the detail view."""

    def test_click_conversation_opens_detail(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-card.conv").first
        expect(card).to_be_visible(timeout=10_000)
        card.click()

        # stateConversation becomes visible, stateSession becomes hidden.
        expect(page.locator("#stateConversation")).to_be_visible(timeout=5_000)
        expect(page.locator("#stateSession")).to_be_hidden()

    def test_detail_shows_participant_name(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-card.conv").first
        expect(card).to_be_visible(timeout=10_000)
        card.click()
        expect(page.locator("#stateConversation")).to_be_visible(timeout=5_000)
        expect(page.locator("#convName")).to_contain_text("ShadowPro")

    def test_back_button_returns_to_session(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-card.conv").first
        expect(card).to_be_visible(timeout=10_000)
        card.click()
        expect(page.locator("#stateConversation")).to_be_visible(timeout=5_000)

        # Click the back button inside stateConversation.
        page.locator("#stateConversation [data-back]").click()

        expect(page.locator("#stateSession")).to_be_visible(timeout=3_000)
        expect(page.locator("#stateConversation")).to_be_hidden()


class TestSessionOverview:
    """Verify the session overview right panel renders narrative content.

    The dashboard auto-pops the conversation detail when a high-severity
    alert is present, so each test first navigates back to the session view.
    """

    def _goto_session(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator("#stateSession")).to_be_visible(timeout=5_000)

    def test_hero_renders(self, page: Page, server_url: str) -> None:
        self._goto_session(page, server_url)
        expect(page.locator("#overviewHero")).to_be_visible()
        expect(page.locator("#heroTitle")).to_be_visible()

    def test_narrative_card_present(self, page: Page, server_url: str) -> None:
        self._goto_session(page, server_url)
        expect(page.locator("#narrativePanel")).to_be_visible()

    def test_actions_list_present(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # Attached check works from any right-panel state.
        expect(page.locator("#actionsList")).to_be_attached()


# ---------------------------------------------------------------------------
# Live-alert toast: new alert arrives *after* page load
# ---------------------------------------------------------------------------


class _Injectable:
    """Bundle of (url, state, tmp) returned by the injectable_server fixture.

    The module-scoped ``server_url`` fixture above pre-seeds a conversation
    before the browser connects, which is the right shape for static
    rendering tests but cannot exercise the "new alert just landed"
    codepath — by the time the page loads, the alert is already present.
    This fixture starts a server with an empty database so tests can
    inject a conversation *after* the dashboard has connected and
    primed its ``knownAlerts`` set.
    """

    def __init__(self, url: str, state: Any, tmp: Path) -> None:
        self.url = url
        self.state = state
        self.tmp = tmp


@pytest.fixture(scope="class")
def injectable_server(tmp_path_factory: pytest.TempPathFactory) -> _Injectable:
    """Start a server with an empty DB; tests inject alerts post-load."""
    from unittest.mock import patch

    tmp = tmp_path_factory.mktemp("browser_live")
    screenshots_dir = tmp / "screenshots"
    screenshots_dir.mkdir()
    (screenshots_dir / "live_alert.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    cfg = GuardLensConfig()
    cfg.database.path = tmp / "live.db"
    cfg.monitor.screenshots_dir = screenshots_dir
    cfg.monitor.demo_mode = True
    cfg.monitor.capture_interval_seconds = 300.0
    cfg.dashboard.server_port = 0
    cfg.dashboard.title = "GuardianLens — Live Test"

    with patch("guardlens.pipeline.ollama.Client") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.chat.return_value = _PIPELINE_OLLAMA_RESPONSE

        app = create_app(cfg)
        config = uvicorn.Config(app, host="127.0.0.1", port=0,
                                log_level="warning", access_log=False)
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("Server did not start within 10 seconds")

        port = server.servers[0].sockets[0].getsockname()[1]
        yield _Injectable(
            url=f"http://127.0.0.1:{port}",
            state=app.state.guardlens,
            tmp=tmp,
        )

        server.should_exit = True
        thread.join(timeout=5)


def _inject_conversation(
    state: Any,
    *,
    platform: str,
    participant: str,
    level: str = "alert",
    narrative: str = "User asked age, then pushed private contact.",
) -> None:
    """Insert a flagged conversation into the live DB. The next SSE tick
    will carry it to the browser, which should fire a toast."""
    state.database.create_conversation(
        platform=platform,
        participants=[participant],
        first_seen=datetime.now().isoformat(),
        messages=[{"sender": participant, "text": "hey how old are you?"}],
        screenshots=[],
        status={
            "threat_level": level,
            "category": "grooming",
            "confidence": 91,
            "grooming_stage": "trust_building",
            "indicators": ["age inquiry", "platform switch"],
            "narrative": narrative,
            "reasoning": narrative,
            "parent_alert_recommended": True,
            "certainty": "high",
        },
        status_reasoning=narrative,
    )


class TestLiveAlertToast:
    """The "ding" moment: a flagged conversation appearing in a fresh SSE
    snapshot should slide a toast in. Clicking the toast opens detail
    and scrolls it into view; the × button dismisses without navigating."""

    def test_toast_spawns_on_new_alert(
        self, page: Page, injectable_server: _Injectable
    ) -> None:
        page.goto(injectable_server.url)
        # Let the first render prime ui.knownAlerts. `ui` is a top-level
        # `const` in a classic script, so it is accessible by bare name
        # inside the page context but NOT as window.ui.
        page.wait_for_function(
            "() => typeof ui !== 'undefined' && ui.knownAlerts instanceof Set",
            timeout=10_000,
        )
        # No toast until we inject something.
        expect(page.locator(".gl-toast")).to_have_count(0)

        _inject_conversation(
            injectable_server.state,
            platform="Discord",
            participant="NewPredator",
        )
        # SSE tick is 2s — give it a bit more for the round-trip.
        expect(page.locator(".gl-toast")).to_have_count(1, timeout=6_000)
        expect(page.locator(".gl-toast .gl-toast-title")).to_contain_text(
            "NewPredator"
        )

    def test_clicking_toast_opens_conversation_detail(
        self, page: Page, injectable_server: _Injectable
    ) -> None:
        page.goto(injectable_server.url)
        page.wait_for_function(
            "() => typeof ui !== 'undefined' && ui.knownAlerts instanceof Set",
            timeout=10_000,
        )
        _inject_conversation(
            injectable_server.state,
            platform="Instagram",
            participant="ClickTargetUser",
            narrative="Flattery escalating to private-DM ask.",
        )
        toast = page.locator(".gl-toast").filter(has_text="ClickTargetUser").first
        expect(toast).to_be_visible(timeout=6_000)
        # Click the body of the toast (not the close button).
        toast.locator(".gl-toast-body").click()
        expect(page.locator("#stateConversation")).to_be_visible(timeout=3_000)
        expect(page.locator("#convName")).to_contain_text("ClickTargetUser")

    def test_close_button_dismisses_without_navigating(
        self, page: Page, injectable_server: _Injectable
    ) -> None:
        page.goto(injectable_server.url)
        page.wait_for_function(
            "() => typeof ui !== 'undefined' && ui.knownAlerts instanceof Set",
            timeout=10_000,
        )
        _inject_conversation(
            injectable_server.state,
            platform="Minecraft",
            participant="DismissTargetUser",
        )
        toast = page.locator(".gl-toast").filter(has_text="DismissTargetUser").first
        expect(toast).to_be_visible(timeout=6_000)
        # Session overview remains visible before we click the X.
        expect(page.locator("#stateSession")).to_be_visible()
        toast.locator(".gl-toast-close").click()
        # After the dismissal animation, the toast is gone.
        expect(toast).to_have_count(0, timeout=3_000)
        # And we're still on the session overview — the close button did NOT open detail.
        expect(page.locator("#stateSession")).to_be_visible()
        expect(page.locator("#stateConversation")).to_be_hidden()


class TestFreshAlertItemsHelper:
    """Exercise the pure `findFreshAlertItems` helper directly in the
    browser context. Keeps the diff logic honest without requiring a
    full SSE round-trip."""

    def test_finds_only_new_keys(
        self, page: Page, injectable_server: _Injectable
    ) -> None:
        page.goto(injectable_server.url)
        page.wait_for_function(
            "() => typeof findFreshAlertItems === 'function'",
            timeout=10_000,
        )
        # Two items, one whose key is already known.
        result = page.evaluate(
            """() => {
              const items = [
                {kind: 'conversation', data: {platform: 'Discord', participant: 'A', threat_level: 'alert'}, level: 'alert'},
                {kind: 'conversation', data: {platform: 'Discord', participant: 'B', threat_level: 'alert'}, level: 'alert'},
              ];
              const known = new Set([alertId('conversation', items[0].data)]);
              return findFreshAlertItems(items, known).map(it => it.data.participant);
            }"""
        )
        assert result == ["B"]
