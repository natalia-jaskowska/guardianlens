"""Centralized, validated configuration for GuardianLens.

All knobs live here. Never hardcode paths, model names, or thresholds in the
rest of the codebase — read them from a :class:`GuardLensConfig` instance.

Configuration sources are layered, lowest priority first:

1. Defaults declared on the Pydantic models below.
2. A YAML file passed to :func:`load_config` (e.g. ``configs/default.yaml``).
3. Environment variables prefixed with ``GUARDLENS_``. Nested fields use a
   double-underscore separator, e.g. ``GUARDLENS_OLLAMA__INFERENCE_MODEL``.

This three-layer pattern keeps the dev/demo flow simple while still allowing
the dashboard to be reconfigured at deploy time without code changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


class OllamaConfig(BaseModel):
    """Settings for the local Ollama server."""

    host: str = "http://localhost:11434"
    inference_model: str = "gemma4:26b"
    finetuned_model: str = "guardlens"
    timeout_seconds: float = 120.0
    temperature: float = 0.2
    num_ctx: int = 8192


class MonitorConfig(BaseModel):
    """Settings for the screen capture loop."""

    capture_interval_seconds: float = Field(15.0, gt=0)
    monitor_index: int = 1
    screenshots_dir: Path = PROJECT_ROOT / "outputs" / "screenshots"
    keep_last_n: int = 200
    demo_mode: bool = Field(
        False,
        description=(
            "If True, skip mss capture and yield synthetic Pillow chat "
            "screenshots instead. Use on headless servers (no DISPLAY) and "
            "for video recording with deterministic content."
        ),
    )
    watch_folder: Path | None = Field(
        None,
        description=(
            "If set, iterate through real image files in this folder "
            "instead of mss capture or demo synthesis. Useful for "
            "running the analyzer against scraped/staged screenshots."
        ),
    )


class SessionConfig(BaseModel):
    """Settings for cross-screenshot session tracking."""

    window_size: int = Field(5, ge=1)
    escalation_threshold: int = Field(
        2,
        ge=1,
        description="Number of consecutive non-safe analyses before flagging escalation.",
    )


class AlertConfig(BaseModel):
    """Settings for parent notification dispatch."""

    enable_email: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    parent_email: str = ""

    enable_webhook: bool = False
    webhook_url: str = ""

    minimum_urgency: str = Field(
        "high",
        description="Minimum alert urgency that triggers an external notification.",
    )


class DashboardConfig(BaseModel):
    """Settings for the Gradio dashboard."""

    server_name: str = "0.0.0.0"
    server_port: int = 7860
    share: bool = False
    title: str = "GuardianLens — Live Monitor"


class DatabaseConfig(BaseModel):
    """Settings for the SQLite analysis store."""

    path: Path = PROJECT_ROOT / "outputs" / "guardlens.db"


class GuardLensConfig(BaseSettings):
    """Top-level configuration object. Holds every other section."""

    model_config = SettingsConfigDict(
        env_prefix="GUARDLENS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_root: Path = PROJECT_ROOT
    log_level: str = "INFO"
    seed: int = 42

    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


def load_config(config_path: Path | None = None) -> GuardLensConfig:
    """Load and validate a :class:`GuardLensConfig`.

    Parameters
    ----------
    config_path:
        Optional YAML file to layer on top of the defaults. Environment
        variables (with the ``GUARDLENS_`` prefix) still override anything
        loaded from the file.
    """
    file_data: dict[str, Any] = {}
    if config_path is not None and config_path.exists():
        loaded = yaml.safe_load(config_path.read_text())
        if isinstance(loaded, dict):
            file_data = loaded
    return GuardLensConfig(**file_data)
