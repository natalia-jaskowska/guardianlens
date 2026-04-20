"""Screenshot capture loop for the GuardianLens client.

Supports two modes:
- Real mode: uses mss to grab the primary monitor.
- Demo mode: cycles through synthetic PNG files in a provided folder.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)


def capture_screen(output_path: Path, monitor_index: int = 1) -> Path:
    """Grab a single screenshot with mss and save it as PNG."""
    import mss
    import mss.tools

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 1
        shot = sct.grab(monitors[monitor_index])
        mss.tools.to_png(shot.rgb, shot.size, output=str(output_path))
    return output_path


def capture_loop(
    interval: float,
    output_dir: Path,
    monitor_index: int = 1,
    keep_last_n: int = 50,
    demo_folder: Path | None = None,
) -> Iterator[Path]:
    """Yield screenshot paths indefinitely at the given interval.

    Args:
        interval: Seconds between captures.
        output_dir: Where to save screenshots.
        monitor_index: Monitor to capture (1 = primary).
        keep_last_n: Delete old screenshots to avoid disk bloat.
        demo_folder: If set, cycle through PNG files in this folder instead
                     of capturing the live screen.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if demo_folder is not None:
        yield from _demo_loop(demo_folder, interval, output_dir, keep_last_n)
        return

    while True:
        ts = int(time.time())
        dest = output_dir / f"screen_{ts}.png"
        try:
            capture_screen(dest, monitor_index)
            logger.debug("Captured %s", dest.name)
            _prune(output_dir, keep_last_n)
            yield dest
        except Exception:
            logger.exception("Screen capture failed")
        time.sleep(interval)


def _demo_loop(
    folder: Path,
    interval: float,
    output_dir: Path,
    keep_last_n: int,
) -> Iterator[Path]:
    images = sorted(folder.glob("*.png")) + sorted(folder.glob("*.jpg"))
    if not images:
        logger.error("Demo folder %s has no PNG/JPG files", folder)
        return
    idx = 0
    while True:
        src = images[idx % len(images)]
        ts = int(time.time())
        dest = output_dir / f"demo_{ts}_{src.stem}.png"
        try:
            from PIL import Image
            Image.open(src).save(dest, "PNG")
            logger.debug("Demo frame: %s", dest.name)
            _prune(output_dir, keep_last_n)
            yield dest
        except Exception:
            logger.exception("Demo frame failed for %s", src)
        idx += 1
        time.sleep(interval)


def _prune(directory: Path, keep: int) -> None:
    files = sorted(directory.glob("*.png"), key=lambda p: p.stat().st_mtime)
    for old in files[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
