"""Smoke tests for the FastAPI server.

These start the app via FastAPI's TestClient (no real network), patch
the pipeline so no Ollama call happens, and exercise the endpoints.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from app.server import create_app
from fastapi.testclient import TestClient

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
    cfg.monitor.capture_interval_seconds = 60.0
    cfg.dashboard.title = "Test"
    return cfg


@pytest.fixture
def client(config: GuardLensConfig) -> TestClient:
    with patch("guardlens.pipeline.ollama.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.chat.return_value = {
            "message": {
                "role": "assistant",
                "content": "test reasoning",
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
        app = create_app(config)
        with TestClient(app) as test_client:
            yield test_client


def test_index_returns_html_with_initial_state(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Guardian" in body
    assert 'id="activityList"' in body
    assert 'id="stateSession"' in body
    assert 'id="stateConversation"' in body
    assert 'id="stateEnvironment"' in body
    assert "/static/dashboard.css" in body
    assert "/static/dashboard.js" in body


def test_static_assets_served(client: TestClient) -> None:
    css = client.get("/static/dashboard.css")
    assert css.status_code == 200
    assert ".gl-activity" in css.text
    js = client.get("/static/dashboard.js")
    assert js.status_code == 200
    assert "EventSource" in js.text


def test_api_state_returns_snapshot(client: TestClient) -> None:
    response = client.get("/api/state")
    assert response.status_code == 200
    payload = response.json()
    for key in ("monitoring", "metrics", "timeline", "latest", "is_alert", "model_name"):
        assert key in payload
    assert isinstance(payload["metrics"], dict)
    assert {"screenshots", "safe", "caution", "alerts"} <= set(payload["metrics"])


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_state_shows_injected_conversation(client: TestClient, config: GuardLensConfig) -> None:
    """Inject a conversation into the DB and confirm it appears in /api/state."""
    state = client.app.state.guardlens
    state.database.create_conversation(
        platform="Minecraft",
        participants=["CoolGuy99"],
        first_seen=datetime.now().isoformat(),
        messages=[
            {"sender": "CoolGuy99", "text": "how old are you?"},
            {"sender": "child", "text": "12"},
        ],
        screenshots=[],
        status={
            "threat_level": "alert",
            "category": "grooming",
            "confidence": 92,
            "narrative": "CoolGuy99 asked age.",
            "reasoning": "age inquiry",
            "parent_alert_recommended": True,
            "certainty": "medium",
        },
    )

    response = client.get("/api/state")
    payload = response.json()
    assert len(payload["conversations"]) >= 1
    conv = payload["conversations"][0]
    assert conv["participant"] == "CoolGuy99"
    assert conv["threat_level"] == "alert"
    assert conv["platform"] == "Minecraft"


def test_hero_reflects_db_latest_when_worker_bypassed(
    client: TestClient, config: GuardLensConfig
) -> None:
    """Inserting a flagged conversation directly (bypassing MonitorWorker)
    should still drive the right-panel hero into an alert tone.

    Context: the Kaggle demo notebook runs the pipeline in the kernel and
    writes to SQLite while a separate dashboard subprocess reads it. That
    subprocess's worker.latest_conv_ids is never populated, so the hero
    must fall back to the DB-latest conversation. Without this fallback
    the hero stays on "Currently safe" even as toasts and the bell fire.
    """
    state = client.app.state.guardlens
    state.database.create_conversation(
        platform="Discord",
        participants=["ShadowPro"],
        first_seen=datetime.now().isoformat(),
        messages=[{"sender": "ShadowPro", "text": "how old are you?"}],
        screenshots=[],
        status={
            "threat_level": "alert",
            "category": "grooming",
            "confidence": 93,
            "narrative": "ShadowPro escalated to age inquiry.",
            "reasoning": "grooming pattern",
            "parent_alert_recommended": True,
            "certainty": "high",
        },
    )

    payload = client.get("/api/state").json()
    narrative = payload["session_narrative"]
    assert narrative["tone"] == "alert"
    assert narrative["headline"] == "Alert active"
    assert payload["is_alert"] is True


def test_push_frame_drops_stale_when_replaced(
    client: TestClient, config: GuardLensConfig
) -> None:
    """Receive mode is "process the latest screenshot". When a new
    frame arrives while one is already pending, the old pending frame
    is dropped — we don't pile up a backlog of stale snapshots.

    This test exercises the slot directly (not via the worker thread)
    so it deterministically verifies the replace semantics without
    depending on inference timing.
    """
    state = client.app.state.guardlens
    worker = state.worker
    a = config.monitor.screenshots_dir / "first.png"
    b = config.monitor.screenshots_dir / "second.png"
    a.write_bytes(b"\x89PNG\r\n\x1a\n")
    b.write_bytes(b"\x89PNG\r\n\x1a\n")

    worker.push_frame(a)
    worker.push_frame(b)

    # The slot now holds only `b`; `a` was replaced.
    assert worker._pending_frame == b
    assert worker._pending_event.is_set()


def test_pause_resume_endpoints(client: TestClient) -> None:
    assert client.get("/api/state").json()["paused"] is False

    response = client.post("/api/pause")
    assert response.status_code == 200
    assert response.json() == {"status": "paused"}
    state_after_pause = client.get("/api/state").json()
    assert state_after_pause["paused"] is True
    assert state_after_pause["monitoring"] is False

    response = client.post("/api/resume")
    assert response.status_code == 200
    assert response.json() == {"status": "running"}
    state_after_resume = client.get("/api/state").json()
    assert state_after_resume["paused"] is False
    assert state_after_resume["monitoring"] is True


def test_pause_is_idempotent(client: TestClient) -> None:
    client.post("/api/pause")
    client.post("/api/pause")
    assert client.get("/api/state").json()["paused"] is True
    client.post("/api/resume")
    assert client.get("/api/state").json()["paused"] is False


def test_api_analysis_not_found(client: TestClient) -> None:
    response = client.get("/api/analysis/999999")
    assert response.status_code == 404
    assert response.json() == {"error": "not found"}


def test_api_analysis_returns_full_payload(client: TestClient, config: GuardLensConfig) -> None:
    state = client.app.state.guardlens
    fake = ScreenAnalysis(
        timestamp=datetime.now(),
        screenshot_path=config.monitor.screenshots_dir / "fake.png",
        platform="Discord",
        classification=ThreatClassification(
            threat_level=ThreatLevel.ALERT,
            category=ThreatCategory.GROOMING,
            confidence=95.0,
            reasoning="Test alert.",
            indicators_found=["false age", "isolation"],
        ),
        inference_seconds=1.2,
    )
    analysis_id = state.database.record_analysis(fake)
    assert analysis_id > 0

    response = client.get(f"/api/analysis/{analysis_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["threat_level"] == "alert"
    assert payload["category"] == "grooming"


def test_state_has_alert_total_field(client: TestClient) -> None:
    response = client.get("/api/state")
    assert response.status_code == 200
    assert "alert_total" in response.json()
    assert isinstance(response.json()["alert_total"], int)


def test_state_has_conversations_and_session_narrative(client: TestClient) -> None:
    response = client.get("/api/state")
    assert response.status_code == 200
    payload = response.json()
    assert "conversations" in payload
    assert "session_narrative" in payload
    assert isinstance(payload["conversations"], list)
    assert "headline" in payload["session_narrative"]
    assert "what_to_do" in payload["session_narrative"]
