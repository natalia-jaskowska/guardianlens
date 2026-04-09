"""Screen capture loop for GuardianLens.

We use ``mss`` because it is lightweight, cross-platform, and (unlike
``pyautogui``) does not require a display server on Linux when running over
SSH with X forwarding. The capture loop is implemented as a generator so the
dashboard can drive it from its own event loop without spawning threads.

When ``MonitorConfig.demo_mode`` is True the loop swaps in synthetic Pillow
screenshots from :mod:`guardlens.demo` instead of calling ``mss``. This
keeps the dashboard launchable on headless servers (no ``DISPLAY``) and
gives the demo video deterministic, repeatable content.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Iterator
from pathlib import Path

import mss
import mss.tools

from guardlens.config import MonitorConfig
from guardlens.demo import DEMO_SCENARIO_SEQUENCE, render_demo_chat


def capture_screen(output_path: Path, monitor_index: int = 1) -> Path:
    """Grab one screenshot and save it as PNG.

    Parameters
    ----------
    output_path:
        Where to write the PNG. Parent directories are created if missing.
    monitor_index:
        ``mss`` monitor index. ``0`` is the virtual "all monitors" view,
        ``1`` is the primary display. Defaults to the primary display.

    Returns
    -------
    Path
        The path the screenshot was written to (same as ``output_path``).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        screenshot = sct.grab(monitor)
        mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(output_path))
    return output_path


def capture_loop(config: MonitorConfig) -> Iterator[Path]:
    """Yield screenshot paths forever, sleeping between captures.

    Branches on ``config.demo_mode``:

    - **Real mode** (default): grab the primary monitor with ``mss``.
    - **Demo mode**: render synthetic Pillow chat screenshots, cycling
      through :data:`guardlens.demo.DEMO_SCENARIOS`.

    The caller is responsible for breaking out of the loop (e.g. when the
    dashboard is closed). Old screenshots are pruned to ``keep_last_n`` to
    avoid filling the disk during long sessions.
    """
    config.screenshots_dir.mkdir(parents=True, exist_ok=True)
    if config.demo_mode:
        yield from _demo_capture_loop(config)
        return
    while True:
        timestamp = int(time.time())
        path = config.screenshots_dir / f"capture_{timestamp}.png"
        yield capture_screen(path, monitor_index=config.monitor_index)
        _prune_old_screenshots(config.screenshots_dir, keep_last_n=config.keep_last_n)
        time.sleep(config.capture_interval_seconds)


def _demo_capture_loop(config: MonitorConfig) -> Iterator[Path]:
    """Yield synthetic Pillow chat screenshots forever.

    Cycles through :data:`guardlens.demo.DEMO_SCENARIO_SEQUENCE` so the
    dashboard UI shows variety across both **platforms** (Minecraft,
    Discord, Instagram) and **scenarios** (safe, grooming, bullying).
    """
    sequence = itertools.cycle(DEMO_SCENARIO_SEQUENCE)
    while True:
        platform, scenario = next(sequence)
        timestamp = int(time.time())
        path = config.screenshots_dir / f"demo_{platform}_{scenario}_{timestamp}.png"
        yield render_demo_chat(path, scenario, platform=platform)
        _prune_old_screenshots(config.screenshots_dir, keep_last_n=config.keep_last_n)
        time.sleep(config.capture_interval_seconds)


def _prune_old_screenshots(screenshots_dir: Path, keep_last_n: int) -> None:
    """Delete all but the most recent ``keep_last_n`` PNGs in the directory."""
    if keep_last_n <= 0:
        return
    pngs = sorted(screenshots_dir.glob("capture_*.png"), key=lambda p: p.stat().st_mtime)
    for stale in pngs[:-keep_last_n]:
        try:
            stale.unlink()
        except OSError:
            # Best-effort cleanup; never crash the monitor loop.
            pass
