"""GuardianLens client entry point.

Usage::

    guardlens-client --server 192.168.1.55:7860
    guardlens-client --server 192.168.1.55:7860 --interval 10
    guardlens-client --server 192.168.1.55:7860 --demo-folder /path/to/screenshots
    guardlens-client --server 192.168.1.55:7860 --monitor 2
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from guardlens_client.capture import capture_loop
from guardlens_client.sender import FrameSender

console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="guardlens-client",
        description="GuardianLens client — captures screenshots and sends them to the server.",
    )
    parser.add_argument(
        "--server",
        required=True,
        metavar="IP[:PORT]",
        help="GuardianLens server address, e.g. 192.168.1.55:7860",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=15.0,
        metavar="SECONDS",
        help="Capture interval in seconds (default: 15).",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=1,
        metavar="INDEX",
        help="Monitor index to capture (1 = primary, default: 1).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("client_screenshots"),
        metavar="DIR",
        help="Local directory for temporary screenshots (default: client_screenshots).",
    )
    parser.add_argument(
        "--demo-folder",
        type=Path,
        default=None,
        metavar="DIR",
        help="Use PNG/JPG files from this folder instead of live screen capture.",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=20,
        metavar="N",
        help="Keep last N screenshots locally (default: 20).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: INFO).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _setup_logging(args.log_level)
    log = logging.getLogger("guardlens_client")

    with FrameSender(args.server) as sender:
        console.print(f"[bold cyan]GuardianLens Client[/bold cyan] → [green]{args.server}[/green]")

        # Wait for server to become available
        for attempt in range(10):
            if sender.check_server():
                console.print("[green]Server reachable ✓[/green]")
                break
            wait = min(2 ** attempt, 30)
            console.print(f"[yellow]Server not ready, retrying in {wait}s…[/yellow]")
            time.sleep(wait)
        else:
            console.print("[red]Server unreachable after 10 attempts — aborting.[/red]")
            return 1

        mode = f"demo ({args.demo_folder})" if args.demo_folder else f"monitor {args.monitor}"
        console.print(f"Capturing every [bold]{args.interval}s[/bold] from {mode}")

        for frame_path in capture_loop(
            interval=args.interval,
            output_dir=args.output_dir,
            monitor_index=args.monitor,
            keep_last_n=args.keep,
            demo_folder=args.demo_folder,
        ):
            sender.send(frame_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
