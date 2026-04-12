"""Browser-based integration tests using Playwright.

These tests start a real FastAPI server (with a mocked Ollama backend)
and drive a headless Chromium browser to verify that the dashboard
renders, updates via SSE, and all interactive elements work.

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
from playwright.sync_api import Page, expect

from app.server import create_app
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAFE_OLLAMA_RESPONSE: dict[str, Any] = {
    "message": {
        "role": "assistant",
        "content": "Normal Minecraft gameplay.",
        "tool_calls": [
            {
                "function": {
                    "name": "classify_threat",
                    "arguments": {
                        "threat_level": "safe",
                        "category": "none",
                        "confidence": 95.0,
                        "reasoning": "Normal gameplay visible.",
                        "indicators_found": [],
                        "platform_detected": "Minecraft",
                        "visible_messages": [
                            {"sender": "Steve", "text": "nice build!"},
                            {"sender": "Alex", "text": "thanks!"},
                        ],
                    },
                }
            }
        ],
    }
}


def _make_alert_analysis(tmp_path: Path) -> ScreenAnalysis:
    return ScreenAnalysis(
        timestamp=datetime.now(),
        screenshot_path=tmp_path / "screenshots" / "fake_alert.png",
        platform="Discord Chat",
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
        chat_messages=[
            ChatMessage(sender="ShadowPro", text="how old are you?", flag="age inquiry"),
            ChatMessage(sender="child", text="14"),
            ChatMessage(sender="ShadowPro", text="cool, wanna add me on snap?", flag="platform switch"),
        ],
        inference_seconds=8.5,
    )


@pytest.fixture(scope="module")
def server_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Start a real FastAPI server on a random port and return its URL.

    The server runs in a daemon thread and is shared across all tests
    in this module. Ollama is patched so no real inference happens.
    """
    from unittest.mock import patch

    tmp = tmp_path_factory.mktemp("browser")
    screenshots_dir = tmp / "screenshots"
    screenshots_dir.mkdir()
    # Create a dummy screenshot so the static mount doesn't 404.
    (screenshots_dir / "fake_alert.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    )

    cfg = GuardLensConfig()
    cfg.database.path = tmp / "test.db"
    cfg.monitor.screenshots_dir = screenshots_dir
    cfg.monitor.demo_mode = True
    cfg.monitor.capture_interval_seconds = 300.0  # effectively never auto-capture
    cfg.dashboard.server_port = 0  # let OS pick a free port
    cfg.dashboard.title = "GuardianLens — Test"

    with patch("guardlens.analyzer.ollama.Client") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.chat.return_value = _SAFE_OLLAMA_RESPONSE

        app = create_app(cfg)

        # We need to discover the actual port after binding.
        # Use uvicorn's Server class directly.
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

        # Wait for server to start and discover the port.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("Server did not start within 10 seconds")

        # Get the actual port from the server's socket.
        sockets = server.servers[0].sockets
        port = sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"

        # Inject an alert analysis so the dashboard has content to show.
        state = app.state.guardlens
        alert = _make_alert_analysis(tmp)
        state.worker._queue.put(alert)
        # Also record it as an alert in the DB so alert_history populates.
        analysis_id = state.database.record_analysis(alert)
        state.database.record_alert(analysis_id, alert, delivered=False)

        yield base_url

        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPageLoad:
    """Verify the dashboard loads and renders initial content."""

    def test_page_title(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page).to_have_title("GuardianLens — Test")

    def test_header_elements_visible(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator(".gl-logo-text")).to_have_text("GuardianLens")
        expect(page.locator("#header-pause")).to_be_visible()
        expect(page.locator("#header-gear")).to_be_visible()

    def test_footer_visible(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator(".gl-footer")).to_be_visible()
        expect(page.locator(".gl-footer")).to_contain_text("On-device only")

    def test_initial_state_script_tag_present(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        script = page.locator("#initial-state")
        expect(script).to_be_attached()

    def test_capture_card_renders(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator("#capture-card")).to_be_visible()

    def test_timeline_section_exists(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator("#timeline")).to_be_visible()

    def test_sidebar_exists(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        expect(page.locator(".gl-sidebar")).to_be_visible()


class TestSSEUpdates:
    """Verify the SSE stream connects and updates the DOM."""

    def test_status_changes_from_connecting(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # After SSE connects, "Connecting..." should change.
        status = page.locator("#header-status")
        # Wait for the status text to change away from "Connecting..."
        expect(status).not_to_have_text("Connecting...", timeout=10_000)

    def test_stats_row_populates(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # Wait for at least one scan to appear in stats.
        scans = page.locator("#status-scans .gl-stat-val")
        # The value should be a number (not "—" or empty).
        expect(scans).not_to_have_text("—", timeout=10_000)

    def test_no_js_errors_on_render(self, page: Page, server_url: str) -> None:
        """No uncaught JS errors should occur during SSE-driven rendering."""
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server_url)
        # Wait for at least one SSE render cycle.
        expect(page.locator("#header-status")).not_to_have_text("Connecting...", timeout=10_000)
        # Give a bit more time for session verdict rendering.
        page.wait_for_timeout(2000)
        assert errors == [], f"JS errors during rendering: {errors}"


class TestPauseResume:
    """Verify the pause/resume button toggles monitoring state."""

    def test_pause_and_resume(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        btn = page.locator("#header-pause")
        expect(btn).to_be_visible()

        # Click pause.
        btn.click()
        # The shell should gain a paused class or the status should change.
        # Wait for the paused state to reflect.
        expect(page.locator("#shell")).to_have_class(re.compile(r"gl-shell-paused"), timeout=5_000)

        # Click resume.
        btn.click()
        expect(page.locator("#shell")).not_to_have_class(re.compile(r"gl-shell-paused"), timeout=5_000)


class TestSettingsDrawer:
    """Verify the settings drawer opens and closes."""

    def test_open_and_close_drawer(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        drawer = page.locator("#settings-drawer")

        # Drawer starts closed.
        expect(drawer).not_to_have_class(re.compile(r"gl-drawer-open"))

        # Click gear to open.
        page.locator("#header-gear").click()
        expect(drawer).to_have_class(re.compile(r"gl-drawer-open"), timeout=3_000)

        # Model picker should be visible.
        expect(page.locator("#model-picker")).to_be_visible()

        # Interval pills should be visible.
        pills = page.locator(".gl-drawer-pill")
        expect(pills.first).to_be_visible()

        # Close via the X button.
        page.locator("#drawer-close").click()
        expect(drawer).not_to_have_class(re.compile(r"gl-drawer-open"), timeout=3_000)

    def test_close_drawer_via_backdrop(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        page.locator("#header-gear").click()
        expect(page.locator("#settings-drawer")).to_have_class(re.compile(r"gl-drawer-open"), timeout=3_000)

        # Click the backdrop to close.
        page.locator("#drawer-backdrop").click(force=True)
        expect(page.locator("#settings-drawer")).not_to_have_class(re.compile(r"gl-drawer-open"), timeout=3_000)

    def test_interval_pill_is_clickable(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        page.locator("#header-gear").click()
        expect(page.locator("#settings-drawer")).to_have_class(re.compile(r"gl-drawer-open"), timeout=3_000)

        # Click the "1m" pill.
        pill = page.locator('.gl-drawer-pill[data-seconds="60"]')
        expect(pill).to_be_visible()
        pill.click()
        # The pill should become active.
        expect(pill).to_have_class(re.compile(r"gl-drawer-pill-active"), timeout=3_000)


class TestAlertHistory:
    """Verify alert cards render and are clickable."""

    def test_alert_cards_appear(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # Wait for SSE to deliver data. Alert cards should appear.
        cards = page.locator(".gl-alert-card")
        expect(cards.first).to_be_visible(timeout=10_000)

    def test_alert_card_shows_threat_type(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-alert-card").first
        expect(card).to_be_visible(timeout=10_000)
        # Card should show the threat type (grooming).
        expect(card).to_contain_text(re.compile(r"rooming", re.IGNORECASE))

    def test_click_alert_card_opens_detail(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-alert-card").first
        expect(card).to_be_visible(timeout=10_000)

        card.click()

        # Detail panel should become visible.
        detail = page.locator("#detail-panel")
        expect(detail).to_be_visible(timeout=5_000)

        # The analysis hero card should appear.
        expect(page.locator("#analysis-card")).to_be_visible()

    def test_back_button_returns_to_overview(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-alert-card").first
        expect(card).to_be_visible(timeout=10_000)
        card.click()
        expect(page.locator("#detail-panel")).to_be_visible(timeout=5_000)

        # Click back.
        page.locator("#analysis-back").click()

        # Overview panel should be visible again.
        expect(page.locator("#overview-panel")).to_be_visible(timeout=3_000)
        expect(page.locator("#detail-panel")).to_be_hidden()


class TestDetailView:
    """Verify the detail analysis view renders correctly."""

    def test_reasoning_chain_renders(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-alert-card").first
        expect(card).to_be_visible(timeout=10_000)
        card.click()
        expect(page.locator("#detail-panel")).to_be_visible(timeout=5_000)

        # Reasoning chain should have steps.
        chain = page.locator("#reasoning-chain")
        expect(chain).to_be_visible()
        # Should contain threat level and confidence from the analysis.
        expect(chain).to_contain_text("GROOMING")

    def test_detail_hero_shows_confidence(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        card = page.locator(".gl-alert-card").first
        expect(card).to_be_visible(timeout=10_000)
        card.click()
        expect(page.locator("#detail-panel")).to_be_visible(timeout=5_000)

        # Hero should show a confidence percentage.
        hero = page.locator("#analysis-card")
        expect(hero).to_contain_text("%")


class TestTimeline:
    """Verify the timeline renders scan entries."""

    def test_timeline_has_entries(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        entries = page.locator(".gl-timeline-entry")
        # Wait for at least one entry.
        expect(entries.first).to_be_visible(timeout=10_000)

    def test_timeline_entries_have_platform(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        entry = page.locator(".gl-timeline-entry").first
        expect(entry).to_be_visible(timeout=10_000)
        # Each entry should show a platform name.
        platform = entry.locator(".gl-timeline-platform")
        expect(platform).to_be_visible()

    def test_timeline_entries_have_time(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        entry = page.locator(".gl-timeline-entry").first
        expect(entry).to_be_visible(timeout=10_000)
        time_el = entry.locator(".gl-timeline-time")
        expect(time_el).to_be_visible()
        # Time should match HH:MM:SS pattern.
        expect(time_el).to_have_text(re.compile(r"\d{2}:\d{2}:\d{2}"))


class TestCaptureCard:
    """Verify the main capture card renders."""

    def test_capture_bar_shows_status(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        # Wait for first SSE update to populate capture card.
        bar_title = page.locator("#capture-bar-title")
        # Should show some text after SSE delivers data.
        expect(bar_title).not_to_be_empty(timeout=10_000)

    def test_capture_time_label(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        time_el = page.locator("#capture-bar-time")
        expect(time_el).to_be_visible(timeout=10_000)
