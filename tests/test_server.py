"""Smoke tests for the FastAPI server.

These start the app via FastAPI's TestClient (no real network), patch
the analyzer so no Ollama call happens, and exercise the four
endpoints. Cheap enough to run on every commit.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from guardlens.config import GuardLensConfig
from guardlens.schema import (
    ScreenAnalysis,
    ThreatCategory,
    ThreatClassification,
    ThreatLevel,
)


@pytest.fixture
def config(tmp_path: Path) -> GuardLensConfig:
    cfg = GuardLensConfig()
    cfg.database.path = tmp_path / "test.db"
    cfg.monitor.screenshots_dir = tmp_path / "screenshots"
    cfg.monitor.demo_mode = True
    cfg.monitor.capture_interval_seconds = 60.0  # don't actually loop during tests
    cfg.dashboard.title = "Test"
    return cfg


@pytest.fixture
def client(config: GuardLensConfig) -> TestClient:
    # Patch the analyzer's HTTP client so no real Ollama call ever happens
    # while the FastAPI lifespan starts the worker thread.
    with patch("guardlens.analyzer.ollama.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.chat.return_value = {
            "message": {
                "role": "assistant",
                "content": "test reasoning",
                "tool_calls": [
                    {
                        "function": {
                            "name": "classify_threat",
                            "arguments": {
                                "threat_level": "safe",
                                "category": "none",
                                "confidence": 95.0,
                                "reasoning": "Safe gameplay",
                                "indicators_found": [],
                                "platform_detected": "Test",
                            },
                        }
                    }
                ],
            }
        }
        app = create_app(config)
        with TestClient(app) as test_client:
            yield test_client


def test_index_returns_html_with_initial_state(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "GuardianLens" in body
    assert 'id="initial-state"' in body
    assert "/static/dashboard.css" in body
    assert "/static/dashboard.js" in body


def test_static_assets_served(client: TestClient) -> None:
    css = client.get("/static/dashboard.css")
    assert css.status_code == 200
    assert "gl-shell" in css.text
    js = client.get("/static/dashboard.js")
    assert js.status_code == 200
    assert "EventSource" in js.text


def test_api_state_returns_snapshot(client: TestClient) -> None:
    response = client.get("/api/state")
    assert response.status_code == 200
    payload = response.json()
    # Required keys
    for key in ("monitoring", "metrics", "timeline", "latest", "is_alert", "model_name"):
        assert key in payload
    assert isinstance(payload["metrics"], dict)
    assert {"screenshots", "safe", "caution", "alerts"} <= set(payload["metrics"])


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_state_serializer_picks_up_latest_analysis(
    client: TestClient, config: GuardLensConfig
) -> None:
    """Inject an analysis directly into the worker queue and confirm
    it shows up in /api/state."""
    state = client.app.state.guardlens
    fake = ScreenAnalysis(
        timestamp=datetime.now(),
        screenshot_path=config.monitor.screenshots_dir / "fake.png",
        platform="Minecraft",
        classification=ThreatClassification(
            threat_level=ThreatLevel.ALERT,
            category=ThreatCategory.GROOMING,
            confidence=92.0,
            reasoning="Injected for the unit test.",
            indicators_found=["injected"],
        ),
        inference_seconds=0.1,
    )
    state.worker._queue.put(fake)

    response = client.get("/api/state")
    payload = response.json()
    assert payload["latest"] is not None
    assert payload["latest"]["threat_level"] == "alert"
    assert payload["is_alert"] is True
    assert payload["metrics"]["alerts"] >= 1
