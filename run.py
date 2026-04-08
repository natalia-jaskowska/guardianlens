"""GuardianLens — single entry point.

Usage::

    python run.py
    python run.py --model gemma4:26b --interval 15 --dashboard-port 7860
    python run.py --config configs/default.yaml
    python run.py --use-finetuned          # use the Unsloth-trained variant
    python run.py --share                  # expose a public Gradio link

Starts the screen-capture monitor loop AND the Gradio dashboard in one
process. The monitor lives in a daemon thread; the Gradio server runs on
the main thread and shuts the monitor down on exit.

This file deliberately stays thin — all the real work lives in
``src/guardlens`` and ``app/dashboard.py``. Its job is to parse CLI flags,
build a :class:`GuardLensConfig` with the overrides applied, and hand off
to :func:`app.dashboard.main`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make ``src/`` importable when running this script directly from the repo
# root without installing the package. After ``pip install -e .`` this is a
# no-op, but it keeps ``python run.py`` working out of the box.
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="guardlens",
        description="Continuous on-device child safety monitor (Gemma 4 + Ollama).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "default.yaml",
        help="Path to a YAML config file (default: configs/default.yaml).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the Ollama inference model (e.g. gemma4:26b).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Override the screenshot capture interval, in seconds.",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=None,
        help="Override the Gradio dashboard port (default: 7860).",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Expose the Gradio dashboard via a public share link.",
    )
    parser.add_argument(
        "--use-finetuned",
        action="store_true",
        help="Use the fine-tuned `guardlens` model instead of the base inference model.",
    )
    parser.add_argument(
        "--demo-mode",
        action="store_true",
        help=(
            "Skip mss screen capture and feed the analyzer synthetic chat "
            "screenshots instead. Use on headless servers (no DISPLAY) and "
            "for video recording with deterministic content."
        ),
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        help="Override log level (DEBUG, INFO, WARNING, ERROR).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # Imports happen after the sys.path tweak above so the local src/
    # package wins over any globally installed `guardlens`.
    from guardlens.config import load_config
    from guardlens.utils import configure_logging, seed_everything

    config_path = args.config if args.config and args.config.exists() else None
    config = load_config(config_path)

    if args.model:
        config.ollama.inference_model = args.model
    if args.demo_mode:
        config.monitor.demo_mode = True
        # Faster default interval for demo mode so the UI feels live.
        # Respect an explicit --interval override if the user passed one.
        if args.interval is None:
            config.monitor.capture_interval_seconds = 8.0
    if args.interval is not None:
        config.monitor.capture_interval_seconds = args.interval
    if args.dashboard_port is not None:
        config.dashboard.server_port = args.dashboard_port
    if args.share:
        config.dashboard.share = True
    if args.log_level:
        config.log_level = args.log_level.upper()

    configure_logging(config.log_level)
    seed_everything(config.seed)

    log = logging.getLogger("guardlens.run")
    log.info(
        "Starting GuardianLens — model=%s interval=%ss port=%d share=%s db=%s",
        config.ollama.inference_model,
        config.monitor.capture_interval_seconds,
        config.dashboard.server_port,
        config.dashboard.share,
        config.database.path,
    )

    # Late imports so the CLI's --help stays fast and Gradio is not loaded
    # before logging is configured.
    from app.dashboard import MonitorWorker, build_app
    from guardlens.alerts import AlertSender
    from guardlens.analyzer import GuardLensAnalyzer
    from guardlens.database import GuardLensDatabase
    from guardlens.session_tracker import SessionTracker

    if args.use_finetuned:
        # Swap the inference model for the fine-tuned variant. The analyzer
        # accepts ``use_finetuned=True`` per-call, but flipping the default
        # here is simpler and matches the CLI flag's intent.
        config.ollama.inference_model = config.ollama.finetuned_model

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
