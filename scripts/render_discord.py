"""Render high-fidelity Discord chat scenarios as frame sequences.

Produces a directory of numbered PNGs — one per message in the scenario,
plus optional typing indicators — ready to drop into
``outputs/video_feeds/<name>/`` and feed into the app's ``--watch-folder``
mode.

Usage::

    .venv/bin/python scripts/render_discord.py --scenario grooming
    .venv/bin/python scripts/render_discord.py --scenario all
    .venv/bin/python scripts/render_discord.py --scenario safe \\
        --out outputs/video_feeds/discord_safe

From there, feed a scenario into the live pipeline::

    .venv/bin/python run.py --watch-folder outputs/video_feeds/discord_grooming \\
                            --interval 2 --model gemma4
"""

from __future__ import annotations

import argparse
from pathlib import Path

from guardlens.discord_chat import SCENARIO_BUILDERS, render_scenario


DEFAULT_ROOT = Path("outputs/video_feeds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(*sorted(SCENARIO_BUILDERS), "all"),
        default="grooming",
        help="which scenario to render (or 'all' for every scenario)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "output directory; defaults to "
            "outputs/video_feeds/discord_<scenario>/ per scenario"
        ),
    )
    parser.add_argument(
        "--prefix",
        default="frame",
        help="filename prefix for frames (default: frame)",
    )
    args = parser.parse_args()

    scenarios: list[str]
    if args.scenario == "all":
        scenarios = sorted(SCENARIO_BUILDERS)
    else:
        scenarios = [args.scenario]

    for name in scenarios:
        if args.out is not None and args.scenario != "all":
            out_dir = args.out
        else:
            out_dir = DEFAULT_ROOT / f"discord_{name}"
        paths = render_scenario(name, out_dir, filename_prefix=args.prefix)  # type: ignore[arg-type]
        print(f"[discord:{name}] {len(paths)} frames -> {out_dir}")
        for p in paths:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
