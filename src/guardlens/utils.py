"""Small shared utilities.

Two things live here:

- :func:`seed_everything` — reproducibility helper. Call once at the start of
  any script that does anything stochastic (model inference is mostly
  deterministic on Ollama, but eval notebooks shuffle datasets).
- :func:`configure_logging` — one-line ``rich`` logging setup so the dashboard
  and CLI tools share a consistent format.
"""

from __future__ import annotations

import logging
import os
import random


def seed_everything(seed: int = 42) -> None:
    """Seed every RNG we know about. Safe to call without optional deps."""
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np
    except ImportError:
        pass
    else:
        np.random.seed(seed)
    try:
        import torch
    except ImportError:
        return
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def configure_logging(level: str = "INFO") -> None:
    """Set up a single root logger using ``rich`` if available."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    try:
        from rich.logging import RichHandler
    except ImportError:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        return
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
