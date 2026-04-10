"""GuardianLens — single entry point.

Usage::

    python run.py
    python run.py --model gemma4 --interval 8 --dashboard-port 7860
    python run.py --config configs/default.yaml
    python run.py --use-finetuned          # use the Unsloth-trained variant
    python run.py --demo-mode              # synthetic chat screenshots, no display required

Starts the FastAPI dashboard server (uvicorn) which spins up the
monitor thread inside its lifespan handler. The monitor lives in a
daemon thread; uvicorn runs the event loop on the main thread and
shuts the worker down on exit.

This file deliberately stays thin — all the real work lives in
``src/guardlens`` and ``app/``. Its job is to parse CLI flags, build a
:class:`GuardLensConfig` with the overrides applied, and hand off to
``app.server.create_app`` + uvicorn.
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
        help="Override the Ollama inference model (e.g. gemma4 or gemma4:26b).",
    )
    parser.add_argument(
        "--ollama-host",
        type=str,
        default=None,
        help="Override the Ollama base URL (e.g. http://192.168.1.55:11434).",
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
        help="Override the FastAPI dashboard port (default: 7860).",
    )
    parser.add_argument(
        "--bind",
        type=str,
        default=None,
        help="Override the FastAPI bind address (default: 0.0.0.0).",
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
        "--watch-folder",
        type=Path,
        default=None,
        help=(
            "Iterate through real image files in this folder instead of "
            "running mss capture or the demo synthesizer. Each image is "
            "symlinked into outputs/screenshots/ so the dashboard can "
            "serve it. Useful for running the analyzer against scraped "
            "or staged screenshots."
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
    if args.ollama_host:
        config.ollama.host = args.ollama_host
    if args.demo_mode:
        config.monitor.demo_mode = True
        # Faster default interval for demo mode so the UI feels live.
        # Respect an explicit --interval override if the user passed one.
        if args.interval is None:
            config.monitor.capture_interval_seconds = 180.0
    if args.watch_folder is not None:
        config.monitor.watch_folder = args.watch_folder.resolve()
        # Folder mode trumps demo mode if both flags are passed.
        config.monitor.demo_mode = False
        # Real images are larger and Ollama vision takes longer on them.
        if args.interval is None:
            config.monitor.capture_interval_seconds = 12.0
    if args.interval is not None:
        config.monitor.capture_interval_seconds = args.interval
    if args.dashboard_port is not None:
        config.dashboard.server_port = args.dashboard_port
    if args.bind:
        config.dashboard.server_name = args.bind
    if args.use_finetuned:
        # Swap the inference model for the fine-tuned variant.
        config.ollama.inference_model = config.ollama.finetuned_model
    if args.log_level:
        config.log_level = args.log_level.upper()

    configure_logging(config.log_level)
    seed_everything(config.seed)

    log = logging.getLogger("guardlens.run")
    log.info(
        "Starting GuardianLens — model=%s host=%s interval=%ss bind=%s:%d db=%s",
        config.ollama.inference_model,
        config.ollama.host,
        config.monitor.capture_interval_seconds,
        config.dashboard.server_name,
        config.dashboard.server_port,
        config.database.path,
    )

    # Late imports so the CLI's --help stays fast and uvicorn / FastAPI
    # are not loaded before logging is configured.
    import uvicorn

    from app.server import create_app

    app = create_app(config)
    uvicorn.run(
        app,
        host=config.dashboard.server_name,
        port=config.dashboard.server_port,
        log_level=config.log_level.lower(),
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
