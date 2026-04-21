"""Screenshot capture loop for the GuardianLens client.

Supports two modes:
- Real mode: tries mss (X11) then grim (Wayland) automatically.
- Demo mode: cycles through synthetic PNG files in a provided folder.
"""

from __future__ import annotations

import contextlib
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

    # macOS built-in screencapture
    if shutil.which("screencapture"):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            probe_path = Path(f.name)
        try:
            result = subprocess.run(
                ["screencapture", "-x", str(probe_path)],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0 and probe_path.exists():
                probe_path.unlink(missing_ok=True)
                logger.info("Capture backend: screencapture (macOS)")
                return "screencapture"
        except Exception:
            pass
        probe_path.unlink(missing_ok=True)

    # Wayland / wlroots (Sway, Hyprland, …)
    if shutil.which("grim"):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as f:
            result = subprocess.run(["grim", f.name], capture_output=True, env=_wayland_env())
        if result.returncode == 0:
            logger.info("Capture backend: grim (wlroots)")
            return "grim"
        logger.info("grim found but compositor unsupported, trying other backends")

    # GNOME Wayland — call Shell DBus interface directly.
    # Probe with a real file in XDG_RUNTIME_DIR (GNOME Shell may refuse /tmp).
    if shutil.which("gdbus"):
        uid = os.getuid()
        probe_path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")) / "gl_probe.png"
        probe_path.unlink(missing_ok=True)
        result = subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell.Screenshot",
                "--object-path",
                "/org/gnome/Shell/Screenshot",
                "--method",
                "org.gnome.Shell.Screenshot.Screenshot",
                "false",
                "false",
                str(probe_path),
            ],
            capture_output=True,
            env=_wayland_env(),
            timeout=10,
        )
        probe_path.unlink(missing_ok=True)
        if result.returncode == 0:
            logger.info("Capture backend: gdbus GNOME Shell (GNOME Wayland)")
            return "gnome-shell-dbus"
        logger.info(
            "gdbus GNOME Shell probe failed (exit %d): %s",
            result.returncode,
            result.stderr.decode(errors="replace").strip(),
        )

    # KDE Wayland
    if shutil.which("spectacle"):
        logger.info("Capture backend: spectacle (KDE Wayland)")
        return "spectacle"

    # flameshot — works on GNOME/KDE Wayland via xdg-portal ScreenCast
    if shutil.which("flameshot"):
        uid = os.getuid()
        probe_path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")) / "gl_probe_fs.png"
        probe_path.unlink(missing_ok=True)
        result = subprocess.run(
            ["flameshot", "screen", "-p", str(probe_path)],
            capture_output=True,
            env=_wayland_env(),
            timeout=15,
        )
        if probe_path.exists():
            probe_path.unlink(missing_ok=True)
            logger.info("Capture backend: flameshot (Wayland via xdg-portal)")
            return "flameshot"
        logger.info(
            "flameshot probe failed (exit %d): %s",
            result.returncode,
            result.stderr.decode(errors="replace").strip(),
        )

    # XWayland fallback via scrot — NOTE: captures black on GNOME Wayland
    if shutil.which("scrot"):
        logger.warning(
            "Capture backend: scrot (XWayland) — will be BLACK on GNOME Wayland. "
            "Install flameshot: sudo pacman -S flameshot"
        )
        return "scrot"

    raise RuntimeError(
        "No capture backend available.\n"
        "  macOS:           pip install mss  (screencapture is built-in fallback)\n"
        "  Windows:         pip install mss\n"
        "  X11 / XWayland:  pip install mss   OR  sudo pacman -S scrot\n"
        "  Wayland/wlroots: sudo pacman -S grim\n"
        "  GNOME Wayland:   sudo pacman -S flameshot\n"
        "  KDE Wayland:     sudo pacman -S spectacle  OR  sudo pacman -S flameshot"
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

    elif _backend == "screencapture":
        result = subprocess.run(
            ["screencapture", "-x", str(output_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"screencapture failed (exit {result.returncode}): {err}")

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
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell.Screenshot",
                "--object-path",
                "/org/gnome/Shell/Screenshot",
                "--method",
                "org.gnome.Shell.Screenshot.Screenshot",
                "false",
                "false",
                str(output_path),
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

    elif _backend == "flameshot":
        result = subprocess.run(
            ["flameshot", "screen", "-p", str(output_path)],
            capture_output=True,
            env=_wayland_env(),
        )
        if not output_path.exists():
            err = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"flameshot failed (exit {result.returncode}): {err}")

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
        with contextlib.suppress(OSError):
            old.unlink()
