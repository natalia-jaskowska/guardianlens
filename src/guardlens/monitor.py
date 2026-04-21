"""Screen capture loop for GuardianLens.

We use ``mss`` for real screen capture because it is lightweight and
cross-platform. The capture loop is implemented as a generator so the
worker thread can drive it without additional concurrency.

When ``MonitorConfig.demo_mode`` is True the loop swaps in synthetic Pillow
screenshots from :mod:`guardlens.demo` instead of calling ``mss``. This
keeps the dashboard launchable on headless servers (no ``DISPLAY``) and
gives the demo video deterministic, repeatable content.
"""

from __future__ import annotations

import contextlib
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

    Branches on the monitor config:

    - ``watch_folder`` set: iterate through real image files on disk.
    - ``demo_mode`` True: render synthetic Pillow chat screenshots,
      cycling through :data:`guardlens.demo.DEMO_SCENARIO_SEQUENCE`.
    - **Real mode** (default): grab the primary monitor with ``mss``.

    The caller is responsible for breaking out of the loop (e.g. when the
    dashboard is closed). Old demo screenshots are pruned to
    ``keep_last_n`` to avoid filling the disk during long sessions.
    """
    config.screenshots_dir.mkdir(parents=True, exist_ok=True)
    if config.watch_folder is not None:
        yield from _watch_folder_loop(config)
        return
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


_IMAGE_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})


def _watch_folder_loop(config: MonitorConfig) -> Iterator[Path]:
    """Yield real image files from ``config.watch_folder`` in a loop.

    Iterates through every image in the folder (sorted by filename) and
    cycles back to the start indefinitely so the dashboard keeps fresh
    content. Each image is symlinked into ``screenshots_dir`` so the
    FastAPI ``/screenshots/`` static mount can serve it directly to the
    fake browser without needing a second mount.

    A symlink is preferred over a copy so we don't waste disk on large
    images. Falls back to a hard copy if the filesystem refuses
    symlinks.
    """
    watch = config.watch_folder
    if watch is None:
        return
    if not watch.exists():
        raise FileNotFoundError(f"watch_folder does not exist: {watch}")

    images = sorted(p for p in watch.iterdir() if p.suffix.lower() in _IMAGE_EXTS)
    if not images:
        raise FileNotFoundError(f"watch_folder {watch} has no .jpg/.jpeg/.png/.webp files")

    # Group by scenario prefix (everything before the trailing _NNNN suffix),
    # then shuffle the group order — so different scenarios interleave
    # instead of processing all 01_safe_* frames before 02_grooming_*.
    # Within each group, frame order is preserved (they tell a progression).
    import random
    import re

    groups: dict[str, list[Path]] = {}
    for p in images:
        key = re.sub(r"_\d+$", "", p.stem)
        groups.setdefault(key, []).append(p)
    group_order = list(groups.keys())
    random.shuffle(group_order)
    shuffled = [img for key in group_order for img in groups[key]]

    while True:
        for source in shuffled:
            target = _link_into_screenshots_dir(source, config.screenshots_dir)
            yield target
            time.sleep(config.capture_interval_seconds)


def _link_into_screenshots_dir(source: Path, screenshots_dir: Path) -> Path:
    """Symlink ``source`` into ``screenshots_dir`` (or copy as fallback).

    Returns the destination path that the dashboard can serve via the
    ``/screenshots/`` static mount.
    """
    target = screenshots_dir / source.name
    if target.exists() or target.is_symlink():
        return target
    try:
        target.symlink_to(source.resolve())
    except OSError:
        target.write_bytes(source.read_bytes())
    return target


def _prune_old_screenshots(screenshots_dir: Path, keep_last_n: int) -> None:
    """Delete all but the most recent ``keep_last_n`` PNGs in the directory.

    Covers both real captures (``capture_*.png``) and demo-mode images
    (``demo_*.png``).
    """
    if keep_last_n <= 0:
        return
    pngs = sorted(screenshots_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
    for stale in pngs[:-keep_last_n]:
        with contextlib.suppress(OSError):
            stale.unlink()
