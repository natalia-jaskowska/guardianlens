"""Screenshot capture loop for the GuardianLens client.

Supports two modes:
- Real mode: tries mss (X11) then grim (Wayland) automatically.
- Demo mode: cycles through synthetic PNG files in a provided folder.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolved once at first capture call.
_backend: str | None = None


def _wayland_env() -> dict[str, str]:
    """Return env with WAYLAND_DISPLAY and DBUS_SESSION_BUS_ADDRESS filled in if missing."""
    env = os.environ.copy()
    if "WAYLAND_DISPLAY" not in env:
        env["WAYLAND_DISPLAY"] = "wayland-1"
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        uid = os.getuid()
        socket = f"/run/user/{uid}/bus"
        if Path(socket).exists():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={socket}"
    return env


def _detect_backend() -> str:
    """Return backend name depending on what works."""
    import tempfile

    # X11 / XWayland
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0])
            with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as f:
                mss.tools.to_png(shot.rgb, shot.size, output=f.name)
        logger.info("Capture backend: mss (X11/XWayland)")
        return "mss"
    except Exception:
        pass

    # Wayland / wlroots (Sway, Hyprland, …)
    if shutil.which("grim"):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as f:
            result = subprocess.run(
                ["grim", f.name], capture_output=True, env=_wayland_env()
            )
        if result.returncode == 0:
            logger.info("Capture backend: grim (wlroots)")
            return "grim"
        logger.info("grim found but compositor unsupported, trying other backends")

    # GNOME Wayland — call Shell DBus interface directly (avoids gnome-screenshot wrapper)
    if shutil.which("gdbus"):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as f:
            result = subprocess.run(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.gnome.Shell.Screenshot",
                    "--object-path", "/org/gnome/Shell/Screenshot",
                    "--method", "org.gnome.Shell.Screenshot.Screenshot",
                    "false", "false", f.name,
                ],
                capture_output=True,
                env=_wayland_env(),
            )
        if result.returncode == 0:
            logger.info("Capture backend: gdbus GNOME Shell (GNOME Wayland)")
            return "gnome-shell-dbus"

    # KDE Wayland
    if shutil.which("spectacle"):
        logger.info("Capture backend: spectacle (KDE Wayland)")
        return "spectacle"

    # XWayland fallback via scrot
    if shutil.which("scrot"):
        logger.info("Capture backend: scrot (XWayland)")
        return "scrot"

    raise RuntimeError(
        "No capture backend available.\n"
        "  X11 / XWayland:  pip install mss   OR  sudo pacman -S scrot\n"
        "  Wayland/wlroots: sudo pacman -S grim\n"
        "  GNOME Wayland:   gdbus ships with glib2 (usually already installed)\n"
        "  KDE Wayland:     sudo pacman -S spectacle"
    )


def capture_screen(output_path: Path, monitor_index: int = 1) -> Path:
    """Grab a single screenshot and save it as PNG."""
    global _backend
    if _backend is None:
        _backend = _detect_backend()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if _backend == "mss":
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitors = sct.monitors
            idx = monitor_index if monitor_index < len(monitors) else 1
            shot = sct.grab(monitors[idx])
            mss.tools.to_png(shot.rgb, shot.size, output=str(output_path))

    elif _backend == "grim":
        env = _wayland_env()
        cmd = ["grim"]
        outputs = _grim_outputs()
        out_idx = monitor_index - 1
        if outputs and out_idx < len(outputs):
            cmd += ["-o", outputs[out_idx]]
        cmd.append(str(output_path))
        result = subprocess.run(cmd, capture_output=True, env=env)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"grim failed (exit {result.returncode}): {err}")

    elif _backend == "gnome-shell-dbus":
        env = _wayland_env()
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell.Screenshot",
                "--object-path", "/org/gnome/Shell/Screenshot",
                "--method", "org.gnome.Shell.Screenshot.Screenshot",
                "false", "false", str(output_path),
            ],
            capture_output=True,
            env=env,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"GNOME Shell screenshot failed (exit {result.returncode}): {err}")

    elif _backend == "spectacle":
        result = subprocess.run(
            ["spectacle", "-b", "-n", "-o", str(output_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"spectacle failed (exit {result.returncode}): {err}")

    elif _backend == "scrot":
        result = subprocess.run(
            ["scrot", str(output_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"scrot failed (exit {result.returncode}): {err}")

    return output_path


def _grim_outputs() -> list[str]:
    """Return list of Wayland output names via swaymsg/wlr-randr if available."""
    for tool, args in [
        ("swaymsg", ["-t", "get_outputs"]),
        ("wlr-randr", ["--json"]),
    ]:
        if not shutil.which(tool):
            continue
        try:
            import json
            result = subprocess.run([tool, *args], capture_output=True, text=True, timeout=3)
            data = json.loads(result.stdout)
            return [o["name"] for o in data if o.get("active", True)]
        except Exception:
            pass
    return []


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
